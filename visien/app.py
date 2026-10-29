"""Visien desktop shell: a native window (WebView2) around the local engine server.

    python -m visien             native window
    python -m visien --browser   open in the default browser instead
    python -m visien --server    API only (no window)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import socket
import sys
import threading
import time
import traceback
import webbrowser
from pathlib import Path

from . import APP_NAME, __version__
from .config import CONFIG, DATA_DIR, ROOT, ensure_dirs, output_dir

LOG_PATH = DATA_DIR / "visien.log"
MEDIA_FILTER = ("Media files (*.mp4;*.mkv;*.mov;*.avi;*.webm;*.m4v;*.ts;*.mts;*.m2ts;*.wmv;*.png;*.jpg;*.jpeg;"
                "*.webp;*.avif;*.tif;*.tiff;*.bmp;*.heic)", "All files (*.*)")


def _setup_logging() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=LOG_PATH, level=logging.INFO, encoding="utf-8",
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if sys.stdout is None or sys.stderr is None:   # pythonw.exe has no console
        sys.stdout = sys.stderr = open(DATA_DIR / "console.log", "a", encoding="utf-8", buffering=1)


def _free_port(preferred: int) -> int:
    for port in (preferred, *range(preferred + 1, preferred + 20)):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _serve(port: int) -> threading.Thread:
    import uvicorn  # noqa: WPS433

    from .server import app  # noqa: WPS433

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", access_log=False,
                            log_config=None)
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="visien-server", daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)
    return thread


class Bridge:
    """Native helpers exposed to the page as window.pywebview.api.*"""

    def __init__(self) -> None:
        self._window = None

    def _dialog(self, kind, **kwargs):
        import webview  # noqa: WPS433

        if self._window is None:
            return []
        result = self._window.create_file_dialog(kind, **kwargs)
        if not result:
            return []
        return [result] if isinstance(result, str) else list(result)

    def pick_media(self):
        import webview  # noqa: WPS433

        return self._dialog(webview.FileDialog.OPEN, allow_multiple=True, file_types=MEDIA_FILTER,
                            directory=CONFIG.get("last_dir") or "")

    def pick_folder(self, start: str = ""):
        import webview  # noqa: WPS433

        found = self._dialog(webview.FileDialog.FOLDER, directory=start or str(output_dir()))
        return found[0] if found else ""

    def pick_file(self, file_filter: str = "All files (*.*)"):
        import webview  # noqa: WPS433

        filters = (file_filter, "All files (*.*)") if file_filter != "All files (*.*)" else (file_filter,)
        found = self._dialog(webview.FileDialog.OPEN, file_types=filters)
        return found[0] if found else ""

    def pick_preset(self):
        import webview  # noqa: WPS433

        found = self._dialog(webview.FileDialog.OPEN, file_types=("Presets (*.json)", "All files (*.*)"))
        return found[0] if found else ""

    def save_preset(self, name: str = "Visien"):
        import webview  # noqa: WPS433

        safe = "".join(c for c in name if c not in '<>:"/\\|?*').strip() or "Visien"
        found = self._dialog(webview.FileDialog.SAVE, save_filename=f"{safe}.json",
                             file_types=("Presets (*.json)",))
        return found[0] if found else ""

    def native(self):
        return True

    def version(self):
        return __version__


_BOUND: set[int] = set()


def _bind_drop(window) -> None:
    from webview.dom import DOMEventHandler  # noqa: WPS433

    if id(window) in _BOUND:
        return
    _BOUND.add(id(window))

    def on_drop(event):
        files = (event.get("dataTransfer") or {}).get("files") or []
        paths = [f.get("pywebviewFullPath") for f in files if isinstance(f, dict) and f.get("pywebviewFullPath")]
        if paths:
            window.evaluate_js(f"window.visien && window.visien.dropped({json.dumps(paths)})")

    def ignore(_event):
        return None

    window.dom.document.events.dragover += DOMEventHandler(ignore, prevent_default=True)
    window.dom.document.events.drop += DOMEventHandler(on_drop, prevent_default=True)


def _icon() -> str | None:
    icon = ROOT / "ui" / "assets" / "visien.ico"
    return str(icon) if icon.is_file() else None


def _unblock_window_libraries() -> None:
    """Remove Windows' "downloaded from the internet" mark from the window's .NET libraries.

    Files extracted with Explorer from a downloaded zip carry that mark (a Zone.Identifier stream), and .NET then
    refuses to load pythonnet's Python.Runtime.dll and the WebView2 wrappers, so the window cannot open.
    """
    if os.name != "nt":
        return
    import importlib.util  # noqa: WPS433

    for name in ("pythonnet", "clr_loader", "webview"):
        try:
            spec = importlib.util.find_spec(name)
        except (ImportError, ValueError):
            continue
        for base in (spec.submodule_search_locations or []) if spec else []:
            for path in Path(base).rglob("*"):
                if path.suffix.lower() in (".dll", ".exe"):
                    try:
                        os.remove(f"{path}:Zone.Identifier")
                    except OSError:
                        pass


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="visien", description=f"{APP_NAME} {__version__}")
    parser.add_argument("--browser", action="store_true", help="open the interface in the default browser")
    parser.add_argument("--server", action="store_true", help="run the local API only")
    parser.add_argument("--port", type=int, default=int(CONFIG.get("port") or 7870))
    parser.add_argument("--debug", action="store_true", help="enable WebView developer tools")
    args = parser.parse_args(argv)

    _setup_logging()
    ensure_dirs()
    if os.name == "nt":
        try:
            import ctypes  # noqa: WPS433

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Visien.App")
        except Exception:  # noqa: BLE001
            pass
    port = _free_port(args.port)
    thread = _serve(port)
    url = f"http://127.0.0.1:{port}/"
    logging.info("Visien %s on %s", __version__, url)

    if args.server:
        print(f"Visien API on {url}")
        thread.join()
        return
    if args.browser:
        webbrowser.open(url)
        print(f"Visien is running on {url} (close this window to quit)")
        thread.join()
        return
    try:
        _unblock_window_libraries()
        import webview  # noqa: WPS433

        bridge = Bridge()
        window = webview.create_window(APP_NAME, url, js_api=bridge, width=1640, height=980, min_size=(1180, 720),
                                       background_color="#111213", text_select=False, zoomable=False,
                                       maximized=True)
        bridge._window = window  # noqa: SLF001
        window.events.loaded += lambda: _bind_drop(window)
        webview.start(gui="edgechromium" if os.name == "nt" else None, debug=args.debug, private_mode=False,
                      storage_path=str(DATA_DIR / "webview"), icon=_icon())
    except Exception:  # noqa: BLE001 - fall back to the browser rather than not starting
        details = traceback.format_exc()
        logging.error("Native window failed, falling back to the browser:\n%s", details)
        _fallback(url, thread, details)


def _fallback(url: str, thread: threading.Thread, details: str = "") -> None:
    if os.name == "nt":
        if "Python.Runtime" in details or "clr" in details.lower():
            reason = ("Windows blocked some of Visien's files because they came from a downloaded zip.\n\n"
                      "Run install.bat in the Visien folder once, then start Visien again.")
        else:
            reason = ("Microsoft Edge WebView2 Runtime is missing or damaged. Install the x64 Evergreen version from "
                      "https://go.microsoft.com/fwlink/p/?LinkId=2124703 for the app window.")
        try:
            import ctypes  # noqa: WPS433

            ctypes.windll.user32.MessageBoxW(
                None, f"The Visien window could not open. Visien opens in your browser instead.\n\n{reason}\n\n"
                      f"Details: {LOG_PATH}", APP_NAME, 0x40)
        except Exception:  # noqa: BLE001
            pass
    webbrowser.open(url)
    thread.join()


if __name__ == "__main__":
    main()
