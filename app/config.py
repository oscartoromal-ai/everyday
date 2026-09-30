"""App configuration.

Non-secret defaults live in config.toml at the repo root; machine-specific
secrets (ICS feed URL, ntfy credentials) are read from the git-ignored local/
directory via paths named in config.toml.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


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
    quiet_hours: tuple[str, str] = ("22:30", "07:30")
    digest_time: str = "07:45"


class BackupConfig(BaseModel):
    # Point this at a cloud-synced folder; actual path TBD by Oscar.
    dir: str = "backups"
    retain: int = 30


class NutritionConfig(BaseModel):
    # The folder of Markdown files nutrition lives in: plan.md, meals/, log/.
    dir: str = "nutrition"
    # The Claude Code executable the chat runs. Empty: `claude` on PATH, or,
    # when that is npm's claude.cmd (which the Agent SDK refuses to run), the
    # native claude.exe npm installed beside it.
    claude_cli: str = ""
    model: str = "claude-opus-5-5"


class Settings(BaseSettings):
    # Env vars override config.toml, e.g. PC_STORAGE__DB_PATH=...
    model_config = SettingsConfigDict(
        toml_file=REPO_ROOT / "config.toml",
        env_prefix="PC_",
        env_nested_delimiter="__",
    )

    server: ServerConfig = ServerConfig()
    storage: StorageConfig = StorageConfig()
    work_calendar: WorkCalendarConfig = WorkCalendarConfig()
    push: PushConfig = PushConfig()
    backup: BackupConfig = BackupConfig()
    nutrition: NutritionConfig = NutritionConfig()

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (init_settings, env_settings, TomlConfigSettingsSource(settings_cls))

    @property
    def db_path(self) -> Path:
        path = Path(self.storage.db_path)
        return path if path.is_absolute() else REPO_ROOT / path

    @property
    def backup_dir(self) -> Path:
        path = Path(self.backup.dir)
        return path if path.is_absolute() else REPO_ROOT / path

    @property
    def nutrition_dir(self) -> Path:
        path = Path(self.nutrition.dir)
        return path if path.is_absolute() else REPO_ROOT / path

    @property
    def ics_url(self) -> str | None:
        path = Path(self.work_calendar.ics_url_file)
        if not path.is_absolute():
            path = REPO_ROOT / path
        if not path.exists():
            return None
        url = path.read_text(encoding="utf-8").strip()
        return url or None


@lru_cache
def get_settings() -> Settings:
    return Settings()
