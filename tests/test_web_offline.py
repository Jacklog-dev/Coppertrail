"""The web front end loads nothing from the internet and takes its look from tokens.css only."""

import re

from coppertrail.ui.devserver import WEB_DIR

REMOTE = re.compile(
    r"""(src|href)\s*=\s*["']https?://"""
    r"""|url\(\s*["']?https?://"""
    r"""|@import\s+(url\()?["']?https?://"""
    r"""|(from|import)\s*\(?\s*["']https?://"""
    r"""|fetch\(\s*["'`]https?://""",
    re.I,
)
OWN_SOURCES = [
    f
    for f in WEB_DIR.rglob("*")
    if f.suffix in {".html", ".css", ".js"} and "vendor" not in f.relative_to(WEB_DIR).parts
]


def test_there_are_sources():
    assert {"index.html", "base.css", "app.css", "api.js", "main.js", "chart.js"} <= {
        f.name for f in OWN_SOURCES
    }


def test_web_loads_nothing_remote():
    for f in OWN_SOURCES:
        assert not REMOTE.search(f.read_text(encoding="utf-8")), f


def test_no_hard_coded_colours_or_fonts_outside_tokens():
    for f in OWN_SOURCES:
        if f.name == "tokens.css" or f.suffix == ".html":
            continue
        text = f.read_text(encoding="utf-8")
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b", text), f
        if f.name != "base.css":  # @font-face lives there
            assert "Almendra" not in text and "Caudex" not in text, f


def test_pages_have_csp():
    for page in WEB_DIR.glob("*.html"):
        assert 'http-equiv="Content-Security-Policy"' in page.read_text(encoding="utf-8"), page


def test_pages_allow_render_host_images_only():
    # Item icons load by URL from Blizzard's render host (coppertrail/ui/icons.py); nothing else.
    import re as _re

    from coppertrail.ui.icons import ICON_HOST

    for page in WEB_DIR.glob("*.html"):
        csp = _re.search(r'Content-Security-Policy" content="([^"]+)"', page.read_text("utf-8"))
        rules = dict(r.strip().split(" ", 1) for r in csp.group(1).split(";"))
        assert rules["img-src"] == f"'self' data: {ICON_HOST}", page
        assert "http" not in rules["default-src"], page
        assert all("http" not in v for k, v in rules.items() if k != "img-src"), page
