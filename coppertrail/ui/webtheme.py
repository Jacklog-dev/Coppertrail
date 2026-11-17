"""Turn the design tokens (`tokens.py`) into CSS custom properties for the web front end.

`web/css/tokens.css` is generated and committed; a test fails when it is out of date.
Regenerate with `uv run python -m coppertrail.ui.webtheme`.
"""

from __future__ import annotations

from pathlib import Path

from coppertrail.ui import tokens

WEB_DIR = Path(__file__).parent / "web"
TOKENS_CSS = WEB_DIR / "css" / "tokens.css"
FALLBACK = '"Segoe UI Symbol", serif'  # ▲ ▼ are missing from Caudex
MONO_FALLBACK = '"Cascadia Mono", Consolas, monospace'  # the mono font is not bundled


def _kebab(name: str) -> str:
    return name.replace("_", "-")


def _spacing(percent: int) -> str:
    return "0" if percent == 0 else f".{percent:02d}em"


def _colours(palette: dict[str, str]) -> list[str]:
    return [f"  --{k}: {v};" for k, v in palette.items()]


def tokens_css() -> str:
    lines = ["/* Generated from coppertrail/ui/tokens.py, do not edit. */", ":root {"]
    lines += _colours(tokens.DARK)
    for role, (family, weight, px, upper, spacing) in tokens.TYPE.items():
        lines += [
            f'  --type-{role}-family: "{family}", {FALLBACK};',
            f"  --type-{role}-weight: {weight};",
            f"  --type-{role}-size: {px}px;",
            f"  --type-{role}-transform: {'uppercase' if upper else 'none'};",
            f"  --type-{role}-spacing: {_spacing(spacing)};",
        ]
    lines.append(f'  --type-mono-family: "{tokens.FONT_MONO}", {MONO_FALLBACK};')
    lines += [f"  --space-{i}: {v}px;" for i, v in enumerate(tokens.SPACE, start=1)]
    lines += [f"  --radius-{_kebab(k)}: {v}px;" for k, v in tokens.RADIUS.items()]
    lines += [f"  --size-{_kebab(k)}: {v}px;" for k, v in tokens.SIZES.items()]
    lines += [
        f"  --coin-{k.removesuffix('_px')}: {v}px;"
        for k, v in tokens.COIN.items()
        if k.endswith("_px")
    ]
    chart = tokens.CHART
    lines += [
        f"  --chart-line-primary: {chart['line_primary']};",
        f"  --chart-line-secondary: {chart['line_secondary']};",
        f"  --chart-line-tertiary: {chart['line_tertiary']};",
        f"  --chart-area-alpha: {chart['area_alpha']};",
        f"  --chart-band-alpha: {chart['band_alpha']};",
        f"  --chart-bar-gap: {chart['bar_gap']};",
        f"  --chart-axis-font: {chart['axis_font_px']}px;",
        f"  --chart-marker-dot: {chart['marker_dot_px']}px;",
        "}",
        "",
        ':root[data-theme="light"] {',
    ]
    lines += _colours(tokens.LIGHT)
    lines += ["}", ""]
    return "\n".join(lines)


def write_tokens_css(path: Path = TOKENS_CSS) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tokens_css(), encoding="utf-8", newline="\n")
    return path


if __name__ == "__main__":
    print(f"wrote {write_tokens_css()}")
