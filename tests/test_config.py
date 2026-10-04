from pathlib import Path

from app import config


def test_the_home_is_the_repo_from_source_and_appdata_installed(monkeypatch) -> None:
    monkeypatch.delenv("PC_HOME", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\someone\AppData\Local")

    monkeypatch.setattr(config, "FROZEN", False)
    assert config.app_home() == config.REPO_ROOT

    monkeypatch.setattr(config, "FROZEN", True)
    assert config.app_home() == Path(r"C:\Users\someone\AppData\Local") / "Personal Calendar"

    monkeypatch.setenv("PC_HOME", r"D:\elsewhere")
    assert config.app_home() == Path(r"D:\elsewhere")


def test_the_homes_config_overrides_the_defaults_key_by_key(tmp_path, monkeypatch) -> None:
    (tmp_path / "config.toml").write_text(
        '[server]\ntailscale_ip = "100.64.0.1"\n\n[nutrition]\ndir = "D:/notes/nutrition"\n'
        # Keys an older version read: passed over, not a reason to refuse to start.
        'model = "claude-opus-5-5"\n\n[claude]\ncli = ""\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "HOME", tmp_path)
    monkeypatch.setitem(
        config.Settings.model_config,
        "toml_file",
        [config.REPO_ROOT / "config.toml", tmp_path / "config.toml"],
    )

    settings = config.Settings()

    assert settings.server.tailscale_ip == "100.64.0.1"
    assert settings.server.port == 8377  # the default's, untouched
    assert settings.server.host == "127.0.0.1"  # its table's other keys kept
    assert settings.nutrition_dir == Path("D:/notes/nutrition")
    # Relative paths land in the home.
    assert settings.db_path == tmp_path / "data" / "personal-calendar.db"
    assert settings.garmin_token_dir == tmp_path / "local" / "garmin"
