r"""App configuration.

Non-secret defaults live in config.toml beside the code (the repo root, or
inside the installed app); machine-specific secrets (ICS feed URL, ntfy
credentials) are read from the git-ignored local/ directory via paths named
in config.toml.

Everything the app keeps (the database, its logs and backups, local/, the
nutrition files) lives under its home: the installed desktop app's is
%LOCALAPPDATA%\Personal Calendar, a run from the repo's is the repo itself,
and PC_HOME names another. Relative paths in the config resolve against it,
and a config.toml there overrides the defaults key by key.
"""

from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path

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


class ClaudeConfig(BaseModel):
    # The Claude Code executable the chats run (Nutrition, Spending). Empty:
    # `claude` on PATH, or, when that is npm's claude.cmd (which the Agent
    # SDK refuses to run), the native claude.exe npm installed beside it.
    cli: str = ""


class NutritionConfig(BaseModel):
    # The folder of Markdown files nutrition lives in: plan.md, meals/, log/.
    dir: str = "nutrition"
    model: str = "claude-opus-5-5"


class MoneyConfig(BaseModel):
    # The model behind Spending's chat.
    model: str = "claude-opus-5-5"


class GarminConfig(BaseModel):
    # Where Garmin's sign-in token is kept (git-ignored); the password never is.
    token_dir: str = "local/garmin"
    # How often the day's figures are fetched again while connected.
    sync_minutes: int = 30
    # How far back a first sync reaches, and the most a later one catches up.
    backfill_days: int = 30


class Settings(BaseSettings):
    # Env vars override config.toml, e.g. PC_STORAGE__DB_PATH=...; the home's
    # config.toml overrides the defaults beside the code (the same file when
    # run from the repo).
    model_config = SettingsConfigDict(
        toml_file=list(dict.fromkeys([REPO_ROOT / "config.toml", HOME / "config.toml"])),
        env_prefix="PC_",
        env_nested_delimiter="__",
    )

    server: ServerConfig = ServerConfig()
    storage: StorageConfig = StorageConfig()
    work_calendar: WorkCalendarConfig = WorkCalendarConfig()
    push: PushConfig = PushConfig()
    backup: BackupConfig = BackupConfig()
    claude: ClaudeConfig = ClaudeConfig()
    nutrition: NutritionConfig = NutritionConfig()
    money: MoneyConfig = MoneyConfig()
    garmin: GarminConfig = GarminConfig()

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
    def ics_url(self) -> str | None:
        path = self.resolve(self.work_calendar.ics_url_file)
        if not path.exists():
            return None
        url = path.read_text(encoding="utf-8").strip()
        return url or None


@lru_cache
def get_settings() -> Settings:
    return Settings()
