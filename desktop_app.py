"""Desktop launcher for ChatVault.

Starts the bundled FastAPI dashboard and opens it in the default browser.
This file is intended to be packaged as a windowed executable on Windows.
"""

from __future__ import annotations

import ctypes
import json
import socket
import threading
import time
import urllib.request
import webbrowser

import uvicorn
from dotenv import load_dotenv

from src.paths import get_data_dir, resolve_db_path


HOST = "127.0.0.1"


def _pick_free_port(host: str = HOST, preferred_port: int = 8000) -> int:
    if preferred_port > 0:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.bind((host, preferred_port))
                return preferred_port
        except OSError:
            pass

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def _wait_for_healthz(host: str, port: int, timeout_s: float = 45.0) -> bool:
    url = f"http://{host}:{port}/healthz"
    started = time.time()
    while (time.time() - started) < timeout_s:
        try:
            with urllib.request.urlopen(url, timeout=1.0) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
                if payload.get("ok") is True:
                    return True
        except Exception:
            time.sleep(0.15)
    return False


def _show_startup_error(message: str) -> None:
    try:
        ctypes.windll.user32.MessageBoxW(0, message, "ChatVault Startup Error", 0x10)
    except Exception:
        print(message)


def main() -> int:
    load_dotenv()
    data_dir = get_data_dir()
    user_env = data_dir / ".env"
    if user_env.exists():
        load_dotenv(user_env, override=True)

    from src.app import make_app

    port = _pick_free_port(HOST)
    url = f"http://{HOST}:{port}"
    print(f"ChatVault is starting at {url}", flush=True)

    app = make_app(resolve_db_path())
    config = uvicorn.Config(app=app, host=HOST, port=port, log_level="warning")
    server = uvicorn.Server(config=config)

    thread = threading.Thread(target=server.run, daemon=False)
    thread.start()

    if _wait_for_healthz(HOST, port):
        print(f"ChatVault is ready: {url}", flush=True)
        opened = webbrowser.open(url)
        if not opened:
            print(f"If your browser did not open, paste this into it: {url}", flush=True)
    else:
        _show_startup_error(f"ChatVault could not start its local web server.\n\nTried: {url}")
        server.should_exit = True

    thread.join()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
