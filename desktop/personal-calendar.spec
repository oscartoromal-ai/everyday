# PyInstaller spec for the desktop app: Python, the app and what it reads at
# runtime (templates, static files, migrations, the default config.toml),
# in one folder the installer ships (desktop/installer.iss). Built by
# desktop/build.ps1.
# ruff: noqa

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

ROOT = Path(SPECPATH).parent

datas = [
    (str(ROOT / "app" / "templates"), "app/templates"),
    (str(ROOT / "app" / "static"), "app/static"),
    (str(ROOT / "migrations"), "migrations"),
    (str(ROOT / "config.toml"), "."),
    # Written by build.ps1: the commit and repo it was built from.
    (str(ROOT / "build" / "build-info.json"), "."),
    # What the Update button runs (app/desktop/update.py).
    (str(ROOT / "desktop" / "update.ps1"), "desktop"),
]
datas += collect_data_files("tzdata")
datas += collect_data_files("webview")
datas += collect_data_files("fastmcp")
datas += collect_data_files("mcp")
for package in (
    "fastmcp", "mcp", "claude-agent-sdk", "garminconnect", "uvicorn", "fastapi", "pydantic",
    "pydantic-settings", "sqlalchemy", "alembic", "icalendar", "recurring-ical-events", "httpx",
):
    datas += copy_metadata(package)

hiddenimports = [
    *collect_submodules("app"),
    *collect_submodules("uvicorn"),
    *collect_submodules("alembic"),
    # Read only by the migrations, which are files, not imported modules.
    "logging.config",
    "pystray._win32",
]

a = Analysis(
    [str(ROOT / "desktop" / "main.py")],
    pathex=[str(ROOT)],
    datas=datas,
    hiddenimports=hiddenimports,
    # Development only.
    excludes=["pytest", "playwright", "ruff", "tkinter"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Personal Calendar",
    icon=str(ROOT / "app" / "static" / "icons" / "app.ico"),
    console=False,
    version=str(ROOT / "build" / "version.txt"),
)
coll = COLLECT(exe, a.binaries, a.datas, name="Personal Calendar")
