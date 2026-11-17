"""The window breakpoints (HANDOVER 8b "Resizing") are the same in tokens, CSS and JS."""

import re

from coppertrail.ui.devserver import WEB_DIR
from coppertrail.ui.tokens import BREAKPOINTS

COMPACT = BREAKPOINTS["compact_max"]
WIDE = BREAKPOINTS["ultrawide_min"]


def _queries(text: str) -> set[tuple[str, int]]:
    return {(k, int(v)) for k, v in re.findall(r"\((max|min)-width:\s*(\d+)px\)", text)}


def test_css_media_queries_use_the_token_widths():
    for name in ("frame.css", "filterbar.css", "layout.css"):
        found = _queries((WEB_DIR / "css" / name).read_text(encoding="utf-8"))
        assert found, name
        assert found <= {("max", COMPACT), ("min", WIDE)}, (name, found)


def test_layout_js_uses_the_token_widths():
    text = (WEB_DIR / "js" / "layout.js").read_text(encoding="utf-8")
    assert f"COMPACT_MAX = {COMPACT};" in text
    assert f"ULTRAWIDE_MIN = {WIDE};" in text


def test_pages_load_the_new_styles():
    index = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    for css in ("states.css", "layout.css"):
        assert f'href="css/{css}"' in index
