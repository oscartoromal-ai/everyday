"""The Markdown engine (app/static/markdown-live.js) in a real browser, on a
bare page of its own (tests/fixtures/markdown_live.html) served from the
live app, since no page of the app's uses it yet: Markdown drawn as it reads
while it is written, its syntax showing where the caret is, the text always
the Markdown as written. The `live` and `page` fixtures are conftest.py's."""

import json
from pathlib import Path

import pytest

pytest.importorskip("playwright.sync_api")

HARNESS = Path(__file__).parent / "fixtures" / "markdown_live.html"


def open_engine(page, live: str, text: str) -> None:
    """The harness, on the app's own origin, holding `text`."""
    html = (
        HARNESS.read_text(encoding="utf-8")
        .replace("{{BASE}}", live)
        .replace("{{SAMPLE}}", json.dumps(text).replace("</", "<\\/"))
    )
    page.route(
        f"{live}/__markdown", lambda route: route.fulfill(body=html, content_type="text/html")
    )
    page.goto(f"{live}/__markdown")
    page.wait_for_function("window.harness")


def shown(page) -> str:
    """The editor's words as drawn."""
    return page.inner_text(".cm-content")


def text(page) -> str:
    """The Markdown as written."""
    return page.evaluate("harness.text()")


def caret_at(page, words: str) -> None:
    """The caret in the editor, just before `words`."""
    page.evaluate(
        """w => {
          const v = harness.view;
          v.focus();
          v.dispatch({ selection: { anchor: v.state.doc.toString().indexOf(w) } });
        }""",
        words,
    )


def test_syntax_hides_away_from_the_caret_and_shows_at_it(page, live) -> None:
    doc = "# Plan\n\nRun **the server** with `uv` and *care*.\n\n> Said once."
    open_engine(page, live, doc)

    drawn = shown(page)
    assert "Plan" in drawn and "#" not in drawn
    assert "Run the server with uv and care." in drawn
    assert "Said once." in drawn and ">" not in drawn
    assert page.locator(".cm-line.cm-md-h1").count() == 1
    assert page.locator(".cm-md-code").inner_text() == "uv"

    # The caret in the bold shows its marks, and only its.
    caret_at(page, "server")
    drawn = shown(page)
    assert "**the server**" in drawn
    assert "`uv`" not in drawn and "*care*" not in drawn and "# Plan" not in drawn

    # On the heading's line, its marks show.
    caret_at(page, "Plan")
    assert "# Plan" in shown(page)

    # Out of focus, everything is drawn rendered; the text never changed.
    page.evaluate("harness.view.contentDOM.blur()")
    assert "**" not in shown(page)
    assert text(page) == doc


def test_a_task_box_ticks_its_markdown(page, live) -> None:
    open_engine(page, live, "- [ ] Write the engine\n- [x] Research it")
    boxes = page.locator(".cm-md-box")
    assert boxes.count() == 2
    assert boxes.nth(0).get_attribute("aria-checked") == "false"
    assert page.locator(".cm-md-done").inner_text() == "Research it"

    boxes.nth(0).click()
    assert text(page) == "- [x] Write the engine\n- [x] Research it"
    page.locator(".cm-md-box").nth(1).click()
    assert text(page) == "- [x] Write the engine\n- [ ] Research it"
    # Undo takes a tick back, as any edit.
    caret_at(page, "Write")
    page.keyboard.press("Control+z")
    assert text(page) == "- [x] Write the engine\n- [x] Research it"


def test_a_rendered_link_opens_and_a_revealed_one_is_written(page, live) -> None:
    doc = (
        "See [the docs](https://docs.astral.sh/uv/) or https://example.com.\n\n"
        "Words [in brackets] are no link."
    )
    open_engine(page, live, doc)
    assert "the docs" in shown(page) and "](" not in shown(page)
    assert "[in brackets]" in shown(page)
    assert page.locator(".cm-md-link").count() == 2

    page.locator(".cm-md-link", has_text="the docs").click()
    assert page.evaluate("harness.opened") == ["https://docs.astral.sh/uv/"]
    page.locator(".cm-md-link", has_text="example.com").click()
    assert page.evaluate("harness.opened")[-1] == "https://example.com"

    # With the caret in it, a link is its Markdown: a click writes in it,
    # Ctrl+click still opens it.
    caret_at(page, "the docs")
    assert "[the docs](https://docs.astral.sh/uv/)" in shown(page)
    page.locator(".cm-md-link", has_text="the docs").click()
    assert len(page.evaluate("harness.opened")) == 2
    page.locator(".cm-md-link", has_text="the docs").click(modifiers=["Control"])
    assert len(page.evaluate("harness.opened")) == 3


def test_a_table_is_drawn_and_opens_as_its_markdown_on_a_click(page, live) -> None:
    doc = (
        "Before\n\n| Command | Speed |\n|:--|--:|\n| `uv sync` | **1.2s** |\n| pytest | |\n\nAfter"
    )
    open_engine(page, live, doc)

    table = page.locator("table.cm-md-table")
    assert table.locator("th").all_inner_texts() == ["Command", "Speed"]
    assert table.locator("tbody tr").count() == 2
    assert table.locator("td code").inner_text() == "uv sync"
    assert table.locator("td strong").inner_text() == "1.2s"
    assert table.locator("th").nth(1).evaluate("e => e.style.textAlign") == "right"
    assert table.locator("td").nth(3).inner_text() == ""

    table.locator("td", has_text="1.2s").click()
    assert page.locator("table.cm-md-table").count() == 0
    assert "| `uv sync` | **1.2s** |" in shown(page)
    assert page.locator(".cm-md-table-src .cm-md-mark", has_text="**").count() == 2
    caret = page.evaluate("harness.view.state.selection.main.head")
    assert text(page)[:caret].endswith("**1.2s**")


def test_the_writing_keys(page, live) -> None:
    open_engine(page, live, "- first")
    caret_at(page, "first")
    page.keyboard.press("End")
    page.keyboard.press("Enter")
    page.keyboard.type("second")
    assert text(page) == "- first\n- second"

    # Ctrl+L gives the item a box, then ticks it.
    page.keyboard.press("Control+l")
    assert text(page) == "- first\n- [ ] second"
    page.keyboard.press("Control+l")
    assert text(page) == "- first\n- [x] second"

    page.keyboard.press("Control+Shift+ArrowLeft")
    page.keyboard.press("Control+b")
    assert text(page) == "- first\n- [x] **second**"
    page.keyboard.press("Control+b")
    page.keyboard.press("Control+Shift+x")
    assert text(page) == "- first\n- [x] ~~second~~"
    page.keyboard.press("Control+Shift+x")
    page.keyboard.press("Control+`")
    assert text(page) == "- first\n- [x] `second`"

    # Enter goes on with a numbered list and a quote too.
    open_engine(page, live, "1. one\n\n> said")
    caret_at(page, "one")
    page.keyboard.press("End")
    page.keyboard.press("Enter")
    page.keyboard.type("two")
    caret_at(page, "said")
    page.keyboard.press("End")
    page.keyboard.press("Enter")
    page.keyboard.type("again")
    assert text(page) == "1. one\n2. two\n\n> said\n> again"


def test_modes_source_reading_and_back(page, live) -> None:
    doc = "## Head\n\n**bold** and [a link](https://example.com)"
    open_engine(page, live, doc)

    page.click("[data-mode=source]")
    page.evaluate("harness.view.contentDOM.blur()")
    assert "## Head" in shown(page) and "**bold**" in shown(page)
    assert "[a link](https://example.com)" in shown(page)

    page.click("[data-mode=reading]")
    assert "##" not in shown(page) and "**" not in shown(page)
    assert page.get_attribute(".cm-content", "contenteditable") == "false"
    page.locator(".cm-md-link").click()
    assert page.evaluate("harness.opened") == ["https://example.com"]

    # Ctrl+E goes back to the mode it was written in, and into reading again.
    page.keyboard.press("Control+e")
    assert page.evaluate("MarkdownLive.modeOf(harness.view)") == "source"
    page.keyboard.press("Control+e")
    assert page.evaluate("MarkdownLive.modeOf(harness.view)") == "reading"
    assert text(page) == doc


def test_code_is_highlighted_in_its_language_and_its_fences_hide(page, live) -> None:
    doc = "Text\n\n```python\ndef hello():\n    return 42\n```\n\nMore"
    open_engine(page, live, doc)
    assert "```" not in shown(page)
    assert page.locator(".cm-md-code-lang").inner_text() == "python"
    assert page.locator(".cm-md-tok-keyword", has_text="def").count() == 1
    assert page.locator(".cm-line.cm-md-codeblock").count() == 4

    caret_at(page, "return")
    assert "```python" in shown(page)


LANGUAGES = {
    "python": "# note\nx = 1",
    "js": "// note\nconst x = 1;",
    "ts": "// note\nlet x: number = 1;",
    "json": '{"x": 1}',
    "html": "<!-- note --><b>x</b>",
    "css": "/* note */ a { color: red; }",
    "sh": "# note\nls -la",
    "ps1": "# note\nGet-ChildItem",
    "yaml": "# note\nx: 1",
    "toml": "# note\nx = 1",
    "sql": "-- note\nSELECT 1;",
    "diff": "+ added\n- removed",
}


def test_every_language_highlights(page, live) -> None:
    doc = "\n\n".join(f"```{name}\n{code}\n```" for name, code in LANGUAGES.items())
    # Tall enough that every block is on screen, so drawn.
    page.set_viewport_size({"width": 1200, "height": 4000})
    open_engine(page, live, doc)
    page.wait_for_function(
        f"document.querySelectorAll('.cm-md-code-lang').length === {len(LANGUAGES)}"
    )
    labels = page.locator(".cm-md-code-lang").all_inner_texts()
    assert labels == list(LANGUAGES)
    # Each block's tokens are its language's (any page error fails the test).
    assert page.locator(".cm-md-tok-comment").count() >= 10
    assert page.locator(".cm-md-tok-inserted").count() == 1


def test_nothing_written_runs_as_markup(page, live) -> None:
    doc = (
        '<img src=x onerror="window.ran=1"> [bad](javascript:window.ran=2)\n\n'
        '| a |\n|---|\n| <img src=y onerror="window.ran=3"> |\n\n'
        "![pic](javascript:alert(1))"
    )
    open_engine(page, live, doc)
    page.wait_for_timeout(200)
    assert page.evaluate("window.ran") is None
    # (CodeMirror's own cursor buffers are images too.)
    assert page.locator(".cm-content img:not(.cm-widgetBuffer)").count() == 0
    # Only a web address is a link.
    assert page.locator(".cm-md-link").count() == 0
