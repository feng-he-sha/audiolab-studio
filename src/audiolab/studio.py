"""Desktop shell: FastAPI + pywebview (WebView2), with browser fallback."""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import threading
import time
import webbrowser
from pathlib import Path
from typing import Any

import requests

from audiolab import config


def find_free_port(preferred: int = 7861) -> int:
    for port in range(preferred, preferred + 30):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class NativeApi:
    """JS bridge exposed as ``window.pywebview.api``."""

    def pick_files(self) -> list[str]:
        import webview

        result = webview.windows[0].create_file_dialog(
            webview.OPEN_DIALOG,
            allow_multiple=True,
            file_types=(
                "媒体文件 (*.mp3;*.wav;*.flac;*.m4a;*.aac;*.ogg;*.opus;*.mp4;*.mov;*.mkv;*.webm)",
                "所有文件 (*.*)",
            ),
        )
        return list(result or [])

    def pick_folder(self) -> list[str]:
        import webview

        result = webview.windows[0].create_file_dialog(webview.FOLDER_DIALOG)
        return list(result or []) if isinstance(result, (list, tuple)) else ([result] if result else [])

    def open_path(self, path: str) -> bool:
        try:
            os.startfile(path)  # type: ignore[attr-defined]
            return True
        except Exception:
            return False

    def reveal_path(self, path: str) -> bool:
        try:
            subprocess.Popen(["explorer", "/select,", str(Path(path))])
            return True
        except Exception:
            return False

    def get_version(self) -> str:
        from audiolab import __version__

        return __version__


def _wait_health(url: str, timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            response = requests.get(f"{url}/api/health", timeout=1.0)
            if response.status_code == 200:
                return True
        except Exception:
            time.sleep(0.2)
    return False


def _run_server(app: Any, host: str, port: int, ready: threading.Event) -> None:
    import uvicorn

    config.ensure_dirs()
    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="info", access_log=False))
    server.install_signal_handlers = lambda: None  # type: ignore[method-assign]
    _run_server.server = server  # type: ignore[attr-defined]
    ready.set()
    server.run()


def main(port: int = 7861, host: str = "127.0.0.1", no_window: bool = False) -> int:
    from audiolab.server.app import app

    config.ensure_dirs()
    port = find_free_port(port)
    url = f"http://{host}:{port}"
    ready = threading.Event()
    thread = threading.Thread(target=_run_server, args=(app, host, port, ready), daemon=True)
    thread.start()
    ready.wait(5)
    if not _wait_health(url, timeout=45):
        print("后端启动超时，请查看日志。")
        return 1
    print(f"AudioLab Studio: {url}")

    if no_window:
        try:
            while thread.is_alive():
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
        server = getattr(_run_server, "server", None)
        if server:
            server.should_exit = True
        thread.join(timeout=5)
        return 0

    try:
        import webview

        window = webview.create_window(
            "AudioLab Studio · 音频人声工作台",
            url,
            width=1480,
            height=920,
            min_size=(1100, 700),
            js_api=NativeApi(),
        )
        webview.start(debug=False)
        server = getattr(_run_server, "server", None)
        if server:
            server.should_exit = True
        thread.join(timeout=5)
        return 0
    except Exception as exc:
        print(f"无法创建桌面窗口（{exc}），改用浏览器打开。")
        webbrowser.open(url)
        try:
            while thread.is_alive():
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
        return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=7861)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--no-window", action="store_true")
    args = parser.parse_args()
    raise SystemExit(main(args.port, args.host, args.no_window))
