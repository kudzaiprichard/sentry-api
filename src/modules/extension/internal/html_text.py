"""HTML → plain text for /emails/analyze body projection.

STANDARD §12 says: ``body`` ← ``body.text`` if non-empty, else strip HTML
from ``body.html``. Keep this dependency-free — parsing via stdlib avoids
pulling BeautifulSoup just to strip tags for the detector's input.
"""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser


_WS_RE = re.compile(r"[ \t]+")
_BLOCK_RE = re.compile(r"\n{3,}")


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0

    _BLOCK_TAGS = {
        "p", "br", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
    }
    _SKIP_TAGS = {"script", "style", "head", "noscript"}

    def handle_starttag(self, tag: str, attrs) -> None:  # type: ignore[override]
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
        elif tag in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:  # type: ignore[override]
        if tag in self._SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        elif tag in self._BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:  # type: ignore[override]
        if self._skip_depth == 0:
            self._parts.append(data)

    def result(self) -> str:
        return "".join(self._parts)


def strip_html(raw: str) -> str:
    if not raw:
        return ""
    parser = _TextExtractor()
    try:
        parser.feed(raw)
        parser.close()
    except Exception:  # noqa: BLE001
        # Malformed HTML — fall back to a crude tag strip + entity decode.
        return html.unescape(re.sub(r"<[^>]+>", " ", raw)).strip()

    text = parser.result()
    text = _WS_RE.sub(" ", text)
    text = _BLOCK_RE.sub("\n\n", text)
    return text.strip()
