r"""App configuration.

Non-secret defaults live in config.toml beside the code (the repo root, or
inside the installed app); machine-specific secrets (ICS feed URL, ntfy
credentials) are read from the git-ignored local/ directory via paths named
in config.toml.

Everything the app keeps (the database, its logs and backups, local/, the
nutrition files) lives under its home: the installed desktop app's is
%LOCALAPPDATA%\Personal Calendar, a run from the repo's is the repo itself,
and PC_HOME names another. Relative paths in the config resolve against it,
and a config.toml there overrides the defaults key by key. So does the
install.toml the installer writes there: the modules ticked (InstallConfig).
"""

from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

# The code's root: the repo, or the installed app's bundle (frozen).
REPO_ROOT = Path(__file__).resolve().parent.parent
FROZEN = getattr(sys, "frozen", False)


def app_home() -> Path:
    """Where the app keeps its data and its machine's config (see above)."""
    if os.environ.get("PC_HOME"):
        return Path(os.environ["PC_HOME"])
    if FROZEN:
        return Path(os.environ["LOCALAPPDATA"]) / "Personal Calendar"
    return REPO_ROOT


HOME = app_home()


class ServerConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8377
    # The machine's Tailscale 100.x interface address; set to also bind and
    # serve there so the phone can reach the app over the tailnet. Its
    # MagicDNS name and IP still need listing in extra_hosts for the browser
    # guard to accept them.
    tailscale_ip: str | None = None
    # Extra hostnames/IPs the browser may address the app by (e.g. the
    # machine's Tailscale MagicDNS name and 100.x address).
    extra_hosts: list[str] = []


class StorageConfig(BaseModel):
    db_path: str = "data/personal-calendar.db"


class WorkCalendarConfig(BaseModel):
    ics_url_file: str = "local/work-calendar-ics-url.txt"
    poll_times: list[str] = ["06:30", "12:30", "16:30"]


class PushConfig(BaseModel):
    ntfy_server: str = "https://ntfy.sh"
    ntfy_topic_file: str = "local/ntfy-topic.txt"
    ntfy_token_file: str = "local/ntfy-token.txt"
    digest_time: str = "07:45"


class BackupConfig(BaseModel):
    # Point this at a cloud-synced folder; actual path TBD by Oscar.
    dir: str = "backups"
    retain: int = 30


class NutritionConfig(BaseModel):
    # The folder of Markdown files nutrition lives in: plan.md, meals/, log/.
    dir: str = "nutrition"


class GarminConfig(BaseModel):
    # Where Garmin's sign-in token is kept (git-ignored); the password never is.
    token_dir: str = "local/garmin"
    # How often the day's figures are fetched again while connected.
    sync_minutes: int = 30
    # How far back a first sync reaches, and the most a later one catches up.
    backfill_days: int = 30


class GitHubConfig(BaseModel):
    # A token pasted on Repositories is kept in this folder (git-ignored), a
    # file per account; connected through the GitHub CLI, the app keeps none
    # and asks gh each time.
    tokens_dir: str = "local/github-tokens"
    # The GitHub CLI. Empty: `gh` on PATH, else where its installer puts it.
    cli: str = ""
    # How often the repositories are fetched again while connected.
    sync_minutes: int = 60


class ImproveConfig(BaseModel):
    # The daily scan for what to improve in the app (improve/ in the repo),
    # started by the installed app from its repo (app/jobs/improve.py).
    enabled: bool = True
    # The day's scan starts after this time, or as soon as the app is up and
    # awake after it.
    after: str = "02:30"
    # The project the app's work is planned on, when no project lists its repo.
    project: str = ""
    # The agent system the pick is handed to for fixing (app/services/
    # agent_runs.py), "t3", or "" to only scan; the model it runs; and the
    # most picks being fixed at once (one pull request waiting on Oscar's
    # review holds the next).
    runner: str = "t3"
    model: str = "claude-opus-5-5"
    max_open: int = 1


# The modules an install can leave out, each a section of the sidebar
# (app/services/rail.py); Planner and Projects are always in.
OptionalModule = Literal["health", "finances", "code"]


class InstallConfig(BaseModel):
    # The modules this machine is installed without, e.g. ["finances"]: their
    # pages, Claude's tools for them and their jobs are left out of the app.
    # The installer writes it to install.toml in the home, from the modules
    # left unticked.
    without: list[OptionalModule] = []


class Settings(BaseSettings):
    # Env vars override config.toml, e.g. PC_STORAGE__DB_PATH=...; the home's
    # config.toml overrides the defaults beside the code (the same file when
    # run from the repo), and the installer's install.toml overrides both.
    model_config = SettingsConfigDict(
        toml_file=list(
            dict.fromkeys(
                [REPO_ROOT / "config.toml", HOME / "config.toml", HOME / "install.toml"]
            )
        ),
        env_prefix="PC_",
        env_nested_delimiter="__",
        # A key the app no longer reads (a machine's config.toml written for
        # an older version) is passed over, not a reason to refuse to start.
        extra="ignore",
    )

    server: ServerConfig = ServerConfig()
    storage: StorageConfig = StorageConfig()
    work_calendar: WorkCalendarConfig = WorkCalendarConfig()
    push: PushConfig = PushConfig()
    backup: BackupConfig = BackupConfig()
    nutrition: NutritionConfig = NutritionConfig()
    garmin: GarminConfig = GarminConfig()
    github: GitHubConfig = GitHubConfig()
    improve: ImproveConfig = ImproveConfig()
    install: InstallConfig = InstallConfig()

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        toml = TomlConfigSettingsSource(settings_cls, deep_merge=True)
        return (init_settings, env_settings, toml)

    def installed(self, module: str) -> bool:
        """Whether this machine has a module: Planner and Projects always, an
        optional one unless it was installed without it."""
        return module not in self.install.without

    @staticmethod
    def resolve(path: str) -> Path:
        """A configured path, relative ones under the app's home."""
        return Path(path) if Path(path).is_absolute() else HOME / path

    @property
    def db_path(self) -> Path:
        return self.resolve(self.storage.db_path)

    @property
    def backup_dir(self) -> Path:
        return self.resolve(self.backup.dir)

    @property
    def nutrition_dir(self) -> Path:
        return self.resolve(self.nutrition.dir)

    @property
    def garmin_token_dir(self) -> Path:
        return self.resolve(self.garmin.token_dir)

    @property
    def github_tokens_dir(self) -> Path:
        return self.resolve(self.github.tokens_dir)

    @property
    def ics_url(self) -> str | None:
        path = self.resolve(self.work_calendar.ics_url_file)
        if not path.exists():
            return None
        url = path.read_text(encoding="utf-8").strip()
        return url or None


@lru_cache
def get_settings() -> Settings:
    return Settings()
