"""Draw the app's icons (app/static/icons) from favicon.svg.

- app.ico: the desktop app's icon (its window, taskbar button, tray, Start
  menu and installer), the favicon drawn at each size Windows asks for, so
  none is a shrunken copy of another.
- icon-192.png: the icon a phone keeps for the app on its home screen.

Run after changing the favicon:

    uv run python scripts/make_icons.py
"""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image
from playwright.sync_api import sync_playwright

STATIC = Path(__file__).resolve().parent.parent / "app" / "static"
OUT = STATIC / "icons"
ICO_SIZES = [16, 20, 24, 32, 40, 48, 64, 96, 128, 256]


def main() -> None:
    favicon = (STATIC / "favicon.svg").read_text(encoding="utf-8")
    OUT.mkdir(exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()

        def draw(size: int) -> Image.Image:
            page.set_viewport_size({"width": size, "height": size})
            page.set_content(
                "<style>html,body{margin:0;background:transparent}"
                f"svg{{display:block;width:{size}px;height:{size}px}}</style>{favicon}"
            )
            return Image.open(io.BytesIO(page.screenshot(omit_background=True))).convert("RGBA")

        draw(192).save(OUT / "icon-192.png")
        print(f"wrote {OUT / 'icon-192.png'}")
        images = [draw(size) for size in ICO_SIZES]
        images[-1].save(
            OUT / "app.ico",
            format="ICO",
            sizes=[(s, s) for s in ICO_SIZES],
            append_images=images[:-1],
        )
        print(f"wrote {OUT / 'app.ico'}")
        browser.close()


if __name__ == "__main__":
    main()
