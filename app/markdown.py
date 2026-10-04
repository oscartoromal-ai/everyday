"""Markdown as the app draws it: Claude's answers in the chats, the
nutrition files' notes, and a task's description in its row. Raw HTML in it
is escaped, never passed through."""

from __future__ import annotations

import re

from markdown_it import MarkdownIt
from markdown_it.common.utils import escapeHtml

_markdown = MarkdownIt("commonmark", {"html": False, "linkify": False}).enable("table")
# A task's description reads as its editor shows it (markdown-editor.js,
# GitHub's flavour): ~~struck~~ words, and bare https:// and www. addresses
# as links.
_notes = MarkdownIt("commonmark", {"html": False, "linkify": True}).enable(
    ["linkify", "strikethrough"]
)
_notes.linkify.set({"fuzzy_link": False, "fuzzy_email": False})


def _link_open(self, tokens, idx, options, env):  # noqa: ANN001, ANN202, ARG001
    # A link to one of the folder's own files (../meals/x.md) leads nowhere
    # in the app, so its words stay as words; a web link opens beside it.
    href = tokens[idx].attrGet("href") or ""
    if not href.startswith(("https://", "http://")):
        tokens[idx].meta["dropped"] = True
        return ""
    return f'<a href="{escapeHtml(href)}" target="_blank" rel="noopener noreferrer">'


def _link_close(self, tokens, idx, options, env):  # noqa: ANN001, ANN202, ARG001
    # The matching open is the nearest unclosed one before it.
    depth = 0
    for token in reversed(tokens[:idx]):
        if token.type == "link_close":
            depth += 1
        elif token.type == "link_open":
            if depth == 0:
                return "" if token.meta.get("dropped") else "</a>"
            depth -= 1
    return "</a>"


for _md in (_markdown, _notes):
    _md.add_render_rule("link_open", _link_open)
    _md.add_render_rule("link_close", _link_close)


def render_markdown(text: str) -> str:
    """Markdown as HTML; raw HTML in it is escaped, never passed through."""
    return _markdown.render(text)


def render_inline(text: str) -> str:
    """A line of Markdown (emphasis, code, links) as HTML, without a paragraph."""
    return _markdown.renderInline(text)


_HEADING = re.compile(r"^(#{1,6})[ \t]+(.*?)(?:[ \t]+#+)?[ \t]*$")
_QUOTE = re.compile(r"^>[ \t]?")
_RULE = re.compile(r"^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$")


def render_note(text: str) -> str:
    """A line of a task's description, or a sub-task's words, as its row
    shows them: as the editor does (markdown-editor.js) with the caret
    elsewhere, its inline Markdown, and a heading's, quote's or rule's line
    drawn as one, its marks hidden."""
    if _RULE.match(text):
        return '<span class="md-hr"></span>'
    heading = _HEADING.match(text)
    if heading:
        level = len(heading[1])
        return f'<strong class="md-h md-h{level}">{_notes.renderInline(heading[2])}</strong>'
    quote = _QUOTE.match(text)
    if quote:
        return f'<span class="md-quote">{_notes.renderInline(text[quote.end() :])}</span>'
    return _notes.renderInline(text)
