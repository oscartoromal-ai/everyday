# PyInstaller spec for the desktop app: Python, the app and what it reads at
# runtime (templates, static files, migrations, the default config.toml),
# in one folder the installer ships (desktop/installer.iss). Built by
# desktop/build.ps1.
#
# The app's own code goes in as source files beside its templates and static
# files (app/ whole, in _internal/app), not into the archive with Python and
# the libraries: an update whose libraries are the same puts its app/ and
# its other files (app-files.txt) in a copy of the running version rather
# than freeze anew (build.ps1 -Reuse), and the build's self-check compiles
# them (app/selfcheck.py).
# ruff: noqa

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

ROOT = Path(SPECPATH).parent
APP = ROOT / "app"

# app/ but its code, which goes in through the analysis (module_collection_mode).
datas = [
    (str(path), str(path.parent.relative_to(ROOT)))
    for path in APP.rglob("*")
    if path.is_file() and path.suffix not in (".py", ".pyc") and "__pycache__" not in path.parts
]
for line in (ROOT / "desktop" / "app-files.txt").read_text(encoding="utf-8").splitlines():
    if line.strip() and not line.startswith("#"):
        source, folder = line.split()
        datas.append((str(ROOT / source), folder))
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
    module_collection_mode={"app": "py"},
    excludes=[
        # Development only.
        "pytest", "playwright", "ruff", "tkinter",
        # httpx's command line, which `import httpx` would load (rich,
        # pygments, click) only to offer `httpx` in a terminal.
        "httpx._main",
    ],
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
    version=str(ROOT / "desktop" / "version-info.txt"),
)
coll = COLLECT(exe, a.binaries, a.datas, name="Personal Calendar")
