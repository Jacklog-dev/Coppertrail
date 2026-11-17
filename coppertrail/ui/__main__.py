"""Start the GUI: `python -m coppertrail.ui [--data-dir DIR] [--screenshot PNG]`."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from coppertrail.query.settings import load_settings
from coppertrail.ui import theme
from coppertrail.ui.window import MainWindow


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m coppertrail.ui", description=__doc__)
    parser.add_argument("--data-dir", type=Path, help="data folder for this session only")
    parser.add_argument("--screenshot", type=Path, help="render the window to a PNG and exit")
    parser.add_argument("--size", default="1920x1080", help="window size for --screenshot")
    args = parser.parse_args(argv)

    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("Coppertrail")
    theme.apply_theme(app)
    win = MainWindow(load_settings(), data_dir=args.data_dir)
    if args.screenshot:
        w, h = (int(v) for v in args.size.lower().split("x"))
        win.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        win.resize(w, h)
        win.show()
        app.processEvents()
        win.grab().save(str(args.screenshot))
        print(f"wrote {args.screenshot}")
        return 0
    win.resize(1600, 1000)
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
