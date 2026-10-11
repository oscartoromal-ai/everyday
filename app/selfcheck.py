"""A build of the installed app checking itself before it is offered.

`Personal Calendar.exe --self-check <report>` (desktop/main.py), run by
desktop/build.ps1 on what it built. The app's code is in its bundle as source
files (desktop/personal-calendar.spec), so that an update whose libraries
are the same can put its code in a copy of the running version rather than
freeze anew (build.ps1 -Reuse). This makes sure such a build works, and that
any build starts without compiling:

- every module of the app compiled, beside its source;
- every module imported;
- every module the app's code imports anywhere, a function's own imports
  included, found in the bundle: one the libraries frozen with the running
  version lack would otherwise fail only once that code runs;
- the SQLite it was frozen with indexing words (FTS5), which the everyday
  files' index needs (app.services.documents).

What fails goes into <report>, a line each, and it exits 1; else 0. Its data
goes to a folder of its own (PC_HOME), never the app's.
"""

from __future__ import annotations

import dis
import importlib
import importlib.util
import os
import py_compile
import sys
import tempfile
import types
from collections.abc import Iterator
from pathlib import Path

APP = Path(__file__).resolve().parent


def main(argv: list[str]) -> None:
    report = Path(argv[0])
    # Before app.config reads it, as the app's modules import.
    os.environ["PC_HOME"] = tempfile.mkdtemp(prefix="personal-calendar-self-check-")
    # pythonnet's .NET namespaces (System, for app/desktop) import once it is loaded.
    import clr  # noqa: F401

    problems = check(APP, write=True)
    report.write_text("".join(f"{line}\n" for line in problems), encoding="utf-8")
    # Not a clean exit: the threads of what it imported (the CLR's) need not end.
    os._exit(1 if problems else 0)


def modules(root: Path) -> dict[str, Path]:
    """Every module of the package at `root`, by name, and its source."""
    found = {}
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        parts = path.relative_to(root.parent).with_suffix("").parts
        if parts[-1] == "__init__":
            parts = parts[:-1]
        found[".".join(parts)] = path
    return found


def imports_of(code: types.CodeType) -> Iterator[tuple[str, int, tuple[str, ...]]]:
    """What `code` imports, its functions' and classes' code included: each
    import's module, its level (dots, for a relative one) and the names it
    takes from it."""
    instructions = list(dis.get_instructions(code))
    for index, instruction in enumerate(instructions):
        if instruction.opname == "IMPORT_NAME" and index >= 2:
            level, fromlist = instructions[index - 2].argval, instructions[index - 1].argval
            yield instruction.argval, level if isinstance(level, int) else 0, tuple(fromlist or ())
    for const in code.co_consts:
        if isinstance(const, types.CodeType):
            yield from imports_of(const)


def _find(name: str) -> bool:
    if name in sys.modules:
        # Imported already, maybe without a spec to find (clr).
        return True
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def missing(module: str, fromlist: tuple[str, ...]) -> str | None:
    """What of an import is not there to import: the module, or a submodule
    it takes from it; None when all of it is."""
    if not _find(module):
        return module
    for name in fromlist:
        if name == "*":
            continue
        try:
            if hasattr(importlib.import_module(module), name):
                continue
        except Exception:
            return module
        if not _find(f"{module}.{name}"):
            return f"{module}.{name}"
    return None


def check(root: Path, write: bool) -> list[str]:
    """What is wrong with the package at `root`, a line each; its modules
    compiled beside their sources when `write`."""
    problems = []
    found = modules(root)
    imports = {}
    for name, path in found.items():
        try:
            imports[name] = list(imports_of(compile(path.read_bytes(), str(path), "exec")))
            if write:
                # Taken as it is: a version's sources never change in place.
                py_compile.compile(
                    str(path), doraise=True,
                    invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH,
                )
        except (SyntaxError, ValueError, OSError, py_compile.PyCompileError) as exc:
            problems.append(f"{name}: does not compile: {exc}")
    for name in imports:
        try:
            importlib.import_module(name)
        except Exception as exc:
            problems.append(f"{name}: does not import: {type(exc).__name__}: {exc}")
    for name, found_imports in imports.items():
        package = name if found[name].name == "__init__.py" else name.rpartition(".")[0]
        for module, level, fromlist in found_imports:
            target = importlib.util.resolve_name("." * level + module, package) if level else module
            lacking = missing(target, fromlist)
            if lacking:
                problems.append(f"{name}: imports {lacking}, which is not there")
    problems += sqlite_problems()
    return sorted(set(problems), key=problems.index)


def sqlite_problems() -> list[str]:
    """What the SQLite the app runs on cannot do that it needs: FTS5."""
    import sqlite3

    try:
        with sqlite3.connect(":memory:") as db:
            db.execute("CREATE VIRTUAL TABLE t USING fts5(body)")
    except sqlite3.Error as exc:
        return [f"sqlite3: no full-text index (FTS5): {exc}"]
    return []
