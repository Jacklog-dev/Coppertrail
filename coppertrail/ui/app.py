"""The desktop app: a pywebview window showing `web/index.html`, driven by the bridge.

    python -m coppertrail.ui [--db FILE] [--dev | --screenshot PNG] [--size WxH] [--no-sync]

pywebview uses Edge WebView2 on Windows and GTK on Linux; it is never asked for Qt. On start
the app syncs our database from the Pi in the background.
"""

from __future__ import annotations

import argparse
import sys
import time
import webbrowser
from pathlib import Path
from typing import Any, ClassVar

from coppertrail.ui import tokens
from coppertrail.ui.bridge import Bridge
from coppertrail.ui.devserver import WEB_DIR, serve
from coppertrail.ui.format import CREDIT_URL


def gui_backend(platform: str = sys.platform) -> str | None:
    """The pywebview backend: never "qt"."""
    if platform == "win32":
        return "edgechromium"
    if platform.startswith("linux"):
        return "gtk"
    return None  # macOS: cocoa, pywebview's only choice there


def parse_size(text: str) -> tuple[int, int]:
    w, h = text.lower().split("x")
    return int(w), int(h)


class AppApi(Bridge):
    """The bridge plus what only the native window can do."""

    EXPOSED: ClassVar[tuple[str, ...]] = (*Bridge.EXPOSED, "open_credit")

    def open_credit(self) -> None:
        webbrowser.open(CREDIT_URL)


def js_facade(api: Bridge) -> Any:
    """An object with only the exposed methods, for pywebview's `js_api`.

    pywebview exposes every public attribute of `js_api` (and walks nested objects), so the
    bridge itself is never handed over.
    """

    def wrap(name: str):
        method = getattr(api, name)

        def call(self, *args):
            return method(*args)

        call.__name__ = name
        return call

    cls = type("JsApi", (), {name: wrap(name) for name in type(api).EXPOSED})
    return cls()


def run_window(api: AppApi, size: tuple[int, int]) -> int:
    import webview

    w, h = size
    webview.create_window(
        "Coppertrail",
        str(WEB_DIR / "index.html"),
        js_api=js_facade(api),
        width=w,
        height=h,
        min_size=(1024, 640),
        background_color=tokens.DARK["bg1"],
    )
    webview.start(gui=gui_backend(), http_server=True, private_mode=True)
    return 0


def run_dev(bridge: Bridge, port: int) -> int:
    server, url = serve(bridge, port)
    print(f"Coppertrail dev server: {url}index.html  (Ctrl+C to stop)", flush=True)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
    return 0


def run_screenshot(bridge: Bridge, page: str, out: Path, size: tuple[int, int]) -> int:
    from coppertrail.ui.screenshot import take

    server, url = serve(bridge)
    try:
        return take(url + page, out, size)
    finally:
        server.shutdown()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m coppertrail.ui", description="Coppertrail desktop GUI."
    )
    parser.add_argument("--db", type=Path, help="our database file (default: config folder)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dev", action="store_true", help="serve the page on 127.0.0.1 only")
    mode.add_argument("--screenshot", type=Path, metavar="PNG", help="render to a PNG and exit")
    parser.add_argument("--size", help="window or screenshot size, e.g. 1920x1080")
    parser.add_argument("--port", type=int, default=0, help="dev server port (default: any)")
    parser.add_argument("--item", type=int, help="with --screenshot: open this item's detail")
    parser.add_argument("--no-sync", action="store_true", help="do not sync from the Pi at start")
    args = parser.parse_args(argv)

    if args.screenshot:
        page = "index.html" + (f"#item/{args.item}" if args.item else "")
        size = parse_size(args.size or "1600x1000")
        return run_screenshot(Bridge(args.db), page, args.screenshot, size)
    api = AppApi(args.db)
    if not args.no_sync:
        api.sync_now()
    if args.dev:
        return run_dev(api, args.port)
    return run_window(api, parse_size(args.size or "1600x1000"))
