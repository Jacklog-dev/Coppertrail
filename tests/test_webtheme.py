from coppertrail.ui import tokens
from coppertrail.ui.webtheme import TOKENS_CSS, tokens_css


def test_committed_tokens_css_is_current():
    assert TOKENS_CSS.read_text(encoding="utf-8") == tokens_css(), (
        "run: uv run python -m coppertrail.ui.webtheme"
    )


def test_every_colour_is_a_variable():
    css = tokens_css()
    for key, value in tokens.DARK.items():
        assert f"--{key}: {value};" in css


def test_type_and_sizes():
    css = tokens_css()
    assert '--type-h1-family: "Almendra", "Segoe UI Symbol", serif;' in css
    assert "--type-h1-transform: uppercase;" in css
    assert "--type-h1-spacing: .06em;" in css
    assert "--type-body-transform: none;" in css and "--type-body-spacing: 0;" in css
    assert "--type-body-size: 14px;" in css and "--type-body-weight: 400;" in css
    assert "--size-nav-w: 200px;" in css and "--size-control-h: 32px;" in css
    assert "--space-1: 4px;" in css and "--space-5: 24px;" in css
    assert "--radius-card: 4px;" in css and "--coin-mark: 7px;" in css
    assert "--chart-line-primary: 2.25;" in css and "--chart-axis-font: 12px;" in css


def test_light_block():
    css = tokens_css()
    light = css[css.index(':root[data-theme="light"]') :]
    assert f"--bg1: {tokens.LIGHT['bg1']};" in light
