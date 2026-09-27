"""Fetch the drafted inputs' caption face (app.css, "drafted inputs"),
Barlow Condensed 600, into app/static/fonts, subset by Google Fonts to the
Latin glyphs the captions use:

    uv run python scripts/fetch-label-fonts.py

The face is SIL Open Font License.
"""

from __future__ import annotations

import re
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "app" / "static" / "fonts"
# Google serves woff2 to a browser that asks like one.
AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126.0 Safari/537.36"
LATIN = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 .,:;+-/()&'"


def get(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def fetch(family: str, weight: int, text: str, name: str) -> None:
    query = urllib.parse.urlencode({"family": f"{family}:wght@{weight}", "text": text})
    css = get(f"https://fonts.googleapis.com/css2?{query}").decode()
    url = re.search(r"url\((https://[^)]+)\)", css)[1]
    data = get(url)
    (FONTS / name).write_bytes(data)
    print(f"{name}: {len(data)} bytes")


def main() -> None:
    FONTS.mkdir(parents=True, exist_ok=True)
    fetch("Barlow Condensed", 600, LATIN, "barlow-condensed-600.woff2")


if __name__ == "__main__":
    main()
