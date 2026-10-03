"""Draw the installed app's icons (app/static/icons) from favicon.svg.

The manifest's icons: the favicon itself at 192 and 512 pixels, and a
maskable one for launchers that cut their own shape (the mark smaller, on a
full-bleed tile, inside the 80% safe zone). Run after changing the favicon:

    uv run python scripts/make_icons.py
"""

from __future__ import annotations

import re
from pathlib import Path

from playwright.sync_api import sync_playwright

STATIC = Path(__file__).resolve().parent.parent / "app" / "static"
OUT = STATIC / "icons"


def maskable(favicon: str) -> str:
    """The favicon's mark on a square tile, scaled into the safe zone."""
    tile = re.search(r'<rect width="32" height="32"[^>]*fill="([^"]+)"', favicon).group(1)
    mark = re.sub(r'<rect width="32" height="32"[^>]*/>\s*', "", favicon.split(">", 1)[1])
    mark = mark.rsplit("</svg>", 1)[0]
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
        f'<rect width="32" height="32" fill="{tile}"/>'
        f'<g transform="translate(16 16) scale(0.72) translate(-16 -16)">{mark}</g></svg>'
    )


def main() -> None:
    favicon = (STATIC / "favicon.svg").read_text(encoding="utf-8")
    OUT.mkdir(exist_ok=True)
    shots = [
        ("icon-192.png", favicon, 192),
        ("icon-512.png", favicon, 512),
        ("icon-maskable-512.png", maskable(favicon), 512),
    ]
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        for name, svg, size in shots:
            page.set_viewport_size({"width": size, "height": size})
            page.set_content(
                "<style>html,body{margin:0;background:transparent}"
                f"svg{{display:block;width:{size}px;height:{size}px}}</style>{svg}"
            )
            page.screenshot(path=OUT / name, omit_background=True)
            print(f"wrote {OUT / name}")
        browser.close()


if __name__ == "__main__":
    main()
