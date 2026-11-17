"""The desktop app: a pywebview window showing `web/index.html`, driven by the bridge.

    python -m coppertrail.ui [--data-dir DIR] [--sample] [--dev | --screenshot PNG] [--size WxH]

pywebview uses Edge WebView2 on Windows and GTK on Linux; it is never asked for Qt.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import webbrowser
from collections.abc import Callable
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any, ClassVar

from coppertrail.ui import tokens
from coppertrail.ui.bridge import AHLEDGER_URL, Bridge
from coppertrail.ui.devserver import WEB_DIR, serve
from coppertrail.ui.pull import PullResult, run_pull

Emit = Callable[[str, dict], None]
VIEW_IDS = ("overview", "item", "patterns", "movers")  # web/js/navrail.js VIEWS
FOLDER_CHANGED = "Pull finished, but the data folder changed meanwhile"
PULL_CRASHED = "Pull failed · the data could not be reloaded"


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

    EXPOSED: ClassVar[tuple[str, ...]] = (*Bridge.EXPOSED, "pick_data_folder", "open_credit")

    def __init__(self, data_dir: Path | None = None, *, emit: Emit | None = None, **kw) -> None:
        super().__init__(data_dir, **kw)
        self.window = None  # set by run_window() once the window exists
        self._emit = emit or self._emit_to_window
        self._pull_thread: threading.Thread | None = None

    def _emit_to_window(self, event: str, payload: dict) -> None:
        if self.window is not None:
            name, data = json.dumps(event), json.dumps(payload, ensure_ascii=False)
            self.window.evaluate_js(f"window.ct && ct.emit({name}, {data})")

    def pick_data_folder(self) -> dict:
        import webview

        chosen = self.window.create_file_dialog(webview.FileDialog.FOLDER) if self.window else None
        if not chosen:
            return self.state()
        return self.set_data_dir(str(chosen[0] if isinstance(chosen, list | tuple) else chosen))

    def open_credit(self) -> None:
        webbrowser.open(AHLEDGER_URL)

    def pull_latest(self) -> dict:
        """Runs git in a worker thread and reports with a `pull` event when done."""
        if self._pull_thread is not None and self._pull_thread.is_alive():
            return {"started": False}

        folder = self.data_dir

        def work() -> None:
            # Always emits, so the page never stays at "Pulling…". git runs unlocked; the
            # reload and state() hold the bridge lock, like every JS call.
            try:
                result = run_pull(folder)
                with self.lock:
                    if result.ok and self.data_dir != folder:
                        result = replace(result, ok=False, message=FOLDER_CHANGED)
                    elif result.ok:
                        self._load()
                    payload = {
                        **asdict(result),
                        "failure": self.pull_failure(result),
                        "state": self.state(),
                    }
            except Exception as exc:  # noqa: BLE001
                crashed = PullResult(False, PULL_CRASHED, f"{type(exc).__name__}: {exc}")
                payload = {**asdict(crashed)}
                try:
                    with self.lock:
                        payload["failure"] = self.pull_failure(crashed)
                        payload["state"] = self.state()
                except Exception:  # noqa: BLE001
                    pass
            self._emit("pull", payload)

        self._pull_thread = threading.Thread(target=work, daemon=True)
        self._pull_thread.start()
        return {"started": True}

    def wait_for_pull(self, timeout: float | None = None) -> None:
        if self._pull_thread is not None:
            self._pull_thread.join(timeout)


def js_facade(api: Bridge) -> Any:
    """An object with only the exposed methods, for pywebview's `js_api`.

    pywebview exposes every public attribute of `js_api` (and walks nested objects), so the
    bridge itself would leak its item lists. Calls arrive on pywebview threads; one at a time,
    except the `UNLOCKED` view methods, which copy their inputs under the lock themselves.
    """
    lock = api.lock  # shared with the pull worker
    unlocked = set(getattr(type(api), "UNLOCKED", ()))

    def wrap(name: str):
        method = getattr(api, name)

        def call(self, *args):
            if name in unlocked:
                return method(*args)
            with lock:
                return method(*args)

        call.__name__ = name
        return call

    cls = type("JsApi", (), {name: wrap(name) for name in type(api).EXPOSED})
    return cls()


def run_window(api: AppApi, page: str, size: tuple[int, int]) -> int:
    import webview

    w, h = size
    api.window = webview.create_window(
        "Coppertrail",
        str(WEB_DIR / page),
        js_api=js_facade(api),
        width=w,
        height=h,
        min_size=(1280, 720),
        background_color=tokens.DARK["bg1"],
    )
    webview.start(gui=gui_backend(), http_server=True, private_mode=True)
    return 0


def run_dev(bridge: Bridge, page: str, port: int) -> int:
    server, url = serve(bridge, port)
    print(f"Coppertrail dev server: {url}{page}  (Ctrl+C to stop)", flush=True)
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
    parser.add_argument("--data-dir", type=Path, help="data folder for this session only")
    parser.add_argument("--sample", action="store_true", help="show the style sample page")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dev", action="store_true", help="serve the page on 127.0.0.1 only")
    mode.add_argument("--screenshot", type=Path, metavar="PNG", help="render to a PNG and exit")
    parser.add_argument("--size", help="window or screenshot size, e.g. 1920x1080")
    parser.add_argument("--port", type=int, default=0, help="dev server port (default: any)")
    parser.add_argument(
        "--view", choices=VIEW_IDS, help="open this view first (overview, item, patterns, movers)"
    )
    args = parser.parse_args(argv)

    page = "sample.html" if args.sample else "index.html"
    if args.view and not args.sample:
        page += f"#{args.view}"
    if args.dev:
        return run_dev(Bridge(args.data_dir), page, args.port)
    if args.screenshot:
        size = parse_size(args.size or "1920x1080")
        return run_screenshot(Bridge(args.data_dir), page, args.screenshot, size)
    window_page = page.split("#")[0]  # a file path: the window always opens on the overview
    return run_window(AppApi(args.data_dir), window_page, parse_size(args.size or "1600x1000"))
