"""The app's keys (app/services/keys.py): a key written any way is the one
key, every action's defaults, the keys chosen in keys.toml over them (by hand
or by Keyboard's page), what in the file can't be used, and the routes that
read and set them. `keys_file` is conftest.py's: each test's own keys.toml."""

import json
import os
import time

import pytest

from app.services import DomainError
from app.services import keys as keys_svc


@pytest.mark.parametrize(
    ("written", "key"),
    [
        ("ctrl+k", "Ctrl+K"),
        ("Shift+Ctrl+k", "Ctrl+Shift+K"),
        ("cmd+alt+1", "Ctrl+Alt+1"),
        ("Ctrl++", "Ctrl++"),
        ("ctrl+plus", "Ctrl++"),
        ("Ctrl+-", "Ctrl+-"),
        ("shift+?", "?"),
        ("esc", "Escape"),
        ("alt+left", "Alt+ArrowLeft"),
        ("space", "Space"),
        ("f2", "F2"),
        ("n", "N"),
    ],
)
def test_a_key_written_any_way_is_the_one_key(written: str, key: str) -> None:
    assert keys_svc.parse(written) == key


@pytest.mark.parametrize("written", ["", "Ctrl", "Ctrl+Shift", "Hyper+K", "Ctrl+Banana"])
def test_what_is_not_a_key_is_said(written: str) -> None:
    with pytest.raises(DomainError):
        keys_svc.parse(written)


def test_every_action_has_an_id_of_its_own_and_its_keys_written_as_parse_writes_them() -> None:
    ids = [e.id for s in keys_svc.SCOPES for e in s.entries if isinstance(e, keys_svc.Action)]
    assert len(ids) == len(set(ids))
    for action in keys_svc.ACTIONS.values():
        for key in action.keys:
            assert keys_svc.parse(key) == key, action.id
    # No two actions in a scope share a key by default.
    assert keys_svc.load().conflicts() == {}


def test_with_no_file_every_key_is_its_default(keys_file) -> None:
    keymap = keys_svc.load()
    assert not keys_file.exists()
    assert keymap.of("app.search") == ("Ctrl+K",)
    assert keymap.of("task.new") == ("N", "Shift+N")
    assert keymap.chosen == {} and keymap.problems == []


def test_the_file_chooses_keys_over_the_defaults_action_by_action(keys_file) -> None:
    keys_file.write_text(
        '[keys]\n"app.search" = "ctrl+p"\n"task.new" = ["N", "Alt+N"]\n"app.density" = []\n',
        encoding="utf-8",
    )
    keymap = keys_svc.load()
    assert keymap.of("app.search") == ("Ctrl+P",)
    assert keymap.of("task.new") == ("N", "Alt+N")
    assert keymap.of("app.density") == ()
    assert keymap.of("app.keys") == ("?",)  # untouched
    assert set(keymap.chosen) == {"app.search", "task.new", "app.density"}


def test_what_the_file_has_wrong_is_said_and_left_out(keys_file) -> None:
    keys_file.write_text(
        '[keys]\n"app.nothing" = "X"\n"app.search" = "Ctrl+Banana"\n"app.keys" = 3\n'
        '"app.theme" = "Ctrl+Shift+T"\n',
        encoding="utf-8",
    )
    keymap = keys_svc.load()
    assert keymap.of("app.search") == ("Ctrl+K",)
    assert keymap.of("app.keys") == ("?",)
    assert keymap.of("app.theme") == ("Ctrl+Shift+T",)
    assert len(keymap.problems) == 3
    assert any("'app.nothing' is not an action" in p for p in keymap.problems)


def test_a_file_that_is_not_toml_leaves_every_key_its_default_and_is_not_written_over(
    keys_file,
) -> None:
    keys_file.write_text('[keys\n"app.search" = "Ctrl+P"\n', encoding="utf-8")
    keymap = keys_svc.load()
    assert keymap.broken and keymap.of("app.search") == ("Ctrl+K",)
    with pytest.raises(DomainError, match="put it right"):
        keys_svc.save("app.search", ["Ctrl+P"])
    assert keys_file.read_text(encoding="utf-8").startswith("[keys\n")


def test_a_key_chosen_is_kept_with_what_else_the_file_says(keys_file) -> None:
    keys_file.write_text(
        '# mine\n[keys]\n"app.theme" = "Ctrl+Shift+T"  # the theme\n', encoding="utf-8"
    )
    keymap = keys_svc.save("app.search", ["ctrl+p", "Ctrl+P", "F1"])
    assert keymap.of("app.search") == ("Ctrl+P", "F1")
    text = keys_file.read_text(encoding="utf-8")
    assert "# mine" in text and "# the theme" in text
    assert '"app.search" = ["Ctrl+P", "F1"]' in text

    # One key is written as one; none as none; its default again, not at all.
    keys_svc.save("app.search", ["Ctrl+P"])
    assert '"app.search" = "Ctrl+P"' in keys_file.read_text(encoding="utf-8")
    keys_svc.save("app.density", [])
    assert '"app.density" = []' in keys_file.read_text(encoding="utf-8")
    assert keys_svc.save("app.search", ["Ctrl+K"]).of("app.search") == ("Ctrl+K",)
    assert "app.search" not in keys_file.read_text(encoding="utf-8")
    keymap = keys_svc.save("app.density", None)
    assert keymap.chosen == {"app.theme": ("Ctrl+Shift+T",)}


def test_a_new_file_says_how_it_is_written(keys_file) -> None:
    keys_svc.save("app.theme", ["Ctrl+Shift+T"])
    text = keys_file.read_text(encoding="utf-8")
    assert text.startswith("# Personal Calendar's keys")
    assert '[keys]\n"app.theme" = "Ctrl+Shift+T"' in text


def test_every_key_back_to_its_default_keeps_the_files_words(keys_file) -> None:
    keys_file.write_text('# mine\n[keys]\n"app.theme" = "Ctrl+Shift+T"\n', encoding="utf-8")
    keymap = keys_svc.reset_all()
    assert keymap.chosen == {}
    assert "# mine" in keys_file.read_text(encoding="utf-8")


def test_the_file_written_by_hand_is_read_again_as_it_changes(keys_file) -> None:
    keys_file.write_text('[keys]\n"app.theme" = "F5"\n', encoding="utf-8")
    assert keys_svc.load().of("app.theme") == ("F5",)
    keys_file.write_text('[keys]\n"app.theme" = "F6"\n', encoding="utf-8")
    # A later write, as an editor saving it a moment on would make.
    later = time.time() + 2
    os.utime(keys_file, (later, later))
    assert keys_svc.load().of("app.theme") == ("F6",)


def test_two_actions_on_one_key_in_one_scope_clash(keys_file) -> None:
    keys_svc.save("app.theme", ["C"])
    clashes = keys_svc.load().conflicts()
    assert clashes == {"app.theme": ["app.density"], "app.density": ["app.theme"]}
    # Across scopes they don't: a page's own key comes first there.
    keys_svc.save("app.theme", ["X"])
    assert keys_svc.load().conflicts() == {}


def test_keys_are_shown_as_key_caps_and_words() -> None:
    keymap = keys_svc.load()
    assert keymap.text("app.back") == "Alt+←"
    assert keymap.title("Search", "app.search") == "Search (Ctrl+K)"
    assert keymap.aria("app.search") == "Control+K"
    assert keymap.cap("nav.slot3") == "3"
    assert str(keymap.kbd("task.new")) == (
        '<kbd>N</kbd> <span class="or">or</span> <kbd>Shift</kbd> <kbd>N</kbd>'
    )
    assert str(keymap.hint("gantt.earlier", "gantt.later")) == (
        "<kbd>Alt</kbd><kbd>←</kbd><kbd>→</kbd>"
    )
    assert str(keys_svc.fixed_keys("[Ctrl] [Enter] or [Esc]")) == (
        '<kbd>Ctrl</kbd> <kbd>Enter</kbd> <span class="or">or</span> <kbd>Esc</kbd>'
    )
    assert str(keys_svc.with_caps("[- [ ]] task, [Ctrl][Z]")) == (
        "<kbd>- [ ]</kbd> task, <kbd>Ctrl</kbd><kbd>Z</kbd>"
    )


# ---- the routes ----


def test_the_keys_are_read_and_set_over_http(client, keys_file) -> None:
    listing = client.get("/ui/keys").json()
    assert listing["file"] == str(keys_file)
    anywhere = next(s for s in listing["scopes"] if s["id"] == "anywhere")
    search = next(e for e in anywhere["entries"] if e.get("id") == "app.search")
    assert search["keys"] == ["Ctrl+K"] and search["default"] == ["Ctrl+K"]
    assert listing["map"]["app.search"]["keys"] == ["Ctrl+K"]

    put = client.put("/ui/keys/app.search", json={"keys": ["ctrl+p"]})
    assert put.status_code == 200
    assert put.json()["map"]["app.search"]["keys"] == ["Ctrl+P"]
    assert '"app.search" = "Ctrl+P"' in keys_file.read_text(encoding="utf-8")

    bad = client.put("/ui/keys/app.search", json={"keys": ["Ctrl+Banana"]})
    assert bad.status_code == 422 and "not a key" in bad.json()["detail"]
    assert client.put("/ui/keys/app.nothing", json={"keys": ["F1"]}).status_code == 422

    assert client.delete("/ui/keys/app.search").json()["map"]["app.search"]["keys"] == ["Ctrl+K"]
    client.put("/ui/keys/app.theme", json={"keys": []})
    assert client.delete("/ui/keys").json()["changed"] == 0


def test_every_page_carries_the_keys_chosen(client, keys_file) -> None:
    keys_file.write_text(
        '[keys]\n"app.search" = "Ctrl+P"\n"nav.slot1" = "Alt+Q"\n', encoding="utf-8"
    )
    page = client.get("/projects").text
    keymap = page.split('<script type="application/json" id="keymap">')[1].split("</script>")[0]
    assert '"app.search": {"keys": ["Ctrl+P"]' in keymap
    # The rail's button, the first page's badge and the keys dialog say them.
    assert 'title="Search, go or do (Ctrl+P)"' in page
    assert '<kbd class="rail-button__key">Ctrl P</kbd>' in page
    first = page.split('data-slot="1"')[1].split("</a>")[0]
    assert '<span class="nav-key" aria-hidden="true">Q</span>' in first
    dialog = page.split('id="keys-dialog"')[1]
    assert "<dt><kbd>Ctrl</kbd> <kbd>P</kbd></dt><dd>Search tasks" in dialog
    # Not Alt+1 to Alt+9 any more: each page of the sidebar's its own line.
    assert "<dt><kbd>Alt</kbd> <kbd>Q</kbd></dt><dd>The sidebar&#39;s page 1" in dialog


def test_the_pane_keys_are_heard_before_the_pages_own(client, keys_file) -> None:
    page = client.get("/today").text
    keymap = json.loads(
        page.split('<script type="application/json" id="keymap">')[1].split("</script>")[0]
    )
    assert keymap["pane.left"]["keys"] == ["Ctrl+Alt+ArrowLeft"]
    assert keymap["pane.left"]["first"] is True
    assert "first" not in keymap["app.search"]


def test_keyboards_page_lists_every_action_and_what_the_file_has_wrong(client, keys_file) -> None:
    keys_file.write_text('[keys]\n"app.theme" = "C"\n"app.nothing" = "X"\n', encoding="utf-8")
    page = client.get("/keys").text
    assert "<h1>Keyboard</h1>" in page and str(keys_file) in page
    assert "&#39;app.nothing&#39; is not an action" in page
    for action_id in keys_svc.installed_actions():
        assert f'data-action="{action_id}"' in page
    theme = page.split('data-action="app.theme"')[1].split("</li>")[0]
    assert "Compact rows, or roomy again" in theme  # its clash
    assert 'data-reset' in theme
    assert "Every key back to its default" in page
