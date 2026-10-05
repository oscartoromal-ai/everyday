"""A build checking itself (app/selfcheck.py), on packages of the test's
own, and on the app's code, which has to pass it for an update to reuse the
running version."""

import importlib.util
import textwrap
from pathlib import Path

import pytest

from app import selfcheck


@pytest.fixture
def package(tmp_path, monkeypatch):  # noqa: ANN201
    """A package `name` of the test's own, its modules' sources given."""

    def make(name: str, sources: dict[str, str]):  # noqa: ANN202
        root = tmp_path / name
        root.mkdir()
        for module, source in {"__init__": "", **sources}.items():
            (root / f"{module}.py").write_text(textwrap.dedent(source), encoding="utf-8")
        monkeypatch.syspath_prepend(str(tmp_path))
        return root

    return make


def test_a_package_whose_imports_are_all_there_passes(package) -> None:
    root = package("whole", {
        "a": """
            import json
            from collections import abc

            from . import b
            from .b import helper
        """,
        "b": """
            def helper():
                from os import path
                return path
        """,
    })
    assert selfcheck.check(root, write=False) == []


def test_an_import_inside_a_function_that_is_not_there_fails(package) -> None:
    root = package("lacking", {
        "jobs": """
            def run():
                import nowhere_to_be_found
                from json import no_such_submodule
        """,
    })
    assert selfcheck.check(root, write=False) == [
        "lacking.jobs: imports nowhere_to_be_found, which is not there",
        "lacking.jobs: imports json.no_such_submodule, which is not there",
    ]


def test_a_module_that_does_not_import_or_compile_fails(package) -> None:
    root = package("broken", {"bad": "def (:\n", "fails": "raise RuntimeError('at import')\n"})
    problems = selfcheck.check(root, write=False)
    assert problems[0].startswith("broken.bad: does not compile")
    assert problems[1] == "broken.fails: does not import: RuntimeError: at import"


def test_its_modules_are_compiled_beside_their_sources(package) -> None:
    root = package("compiled", {"a": "VALUE = 1\n"})
    assert selfcheck.check(root, write=True) == []
    assert Path(importlib.util.cache_from_source(str(root / "a.py"))).is_file()


def test_the_apps_own_code_passes() -> None:
    # pythonnet's namespaces (System, in app/desktop), as the installed app has them.
    import clr  # noqa: F401

    assert selfcheck.check(selfcheck.APP, write=False) == []
