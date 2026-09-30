"""Markdown as the app draws it: Claude's answers in the chats, and the
nutrition files' notes. Raw HTML in it is escaped, never passed through."""

from __future__ import annotations

from markdown_it import MarkdownIt
from markdown_it.common.utils import escapeHtml

_markdown = MarkdownIt("commonmark", {"html": False, "linkify": False}).enable("table")


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


_markdown.add_render_rule("link_open", _link_open)
_markdown.add_render_rule("link_close", _link_close)


def render_markdown(text: str) -> str:
    """Markdown as HTML; raw HTML in it is escaped, never passed through."""
    return _markdown.render(text)


def render_inline(text: str) -> str:
    """A line of Markdown (emphasis, code, links) as HTML, without a paragraph."""
    return _markdown.renderInline(text)
