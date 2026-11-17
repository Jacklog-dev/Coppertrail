"""Start the GUI. Being rebuilt on pywebview, see docs/superpowers/plans."""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    print(
        "GUI is being rebuilt (pywebview), see docs/superpowers/plans/2026-11-17-webview-gui.md",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
