"""Desktop launcher for ChatVault.

Starts the bundled FastAPI dashboard and opens it in the default browser.
This file is intended to be packaged as a windowed executable on Windows.
"""

from __future__ import annotations

import ctypes
import json
import os
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
import webbrowser

import uvicorn
from dotenv import load_dotenv

from src.paths import get_data_dir, resolve_db_path


HOST = "127.0.0.1"
PREFERRED_PORT = 8000
_STARTUP_LOG = None


def _pick_free_port(host: str = HOST, preferred_port: int = PREFERRED_PORT) -> tuple[int, bool]:
    if preferred_port > 0:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.bind((host, preferred_port))
                return preferred_port, True
        except OSError:
            pass

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1]), False


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
        _safe_print(message)


def _prepare_runtime_logging(data_dir) -> None:
    """Give windowed packaged builds a real stream for hidden startup errors."""
    global _STARTUP_LOG
    if sys.stdout is not None and sys.stderr is not None:
        return
    try:
        log_path = data_dir / "chatvault-startup.log"
        _STARTUP_LOG = open(log_path, "a", encoding="utf-8", buffering=1)
        if sys.stdout is None:
            sys.stdout = _STARTUP_LOG
        if sys.stderr is None:
            sys.stderr = _STARTUP_LOG
        _safe_print()
        _safe_print(f"ChatVault startup log: {log_path}")
    except Exception:
        pass


def _safe_print(message: str = "") -> None:
    stream = getattr(sys, "stdout", None)
    if stream is None:
        return
    try:
        print(message, flush=True)
    except Exception:
        pass


def _copy_to_clipboard(text: str) -> bool:
    if os.name != "nt":
        return False
    try:
        subprocess.run("clip.exe", input=text, text=True, check=True)
        return True
    except Exception:
        return False


def _env_truthy(name: str) -> bool:
    return (os.getenv(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def _run_server(server: uvicorn.Server) -> None:
    try:
        server.run()
    except Exception:
        try:
            traceback.print_exc()
        finally:
            raise


def main() -> int:
    load_dotenv()
    data_dir = get_data_dir()
    _prepare_runtime_logging(data_dir)
    user_env = data_dir / ".env"
    if user_env.exists():
        load_dotenv(user_env, override=True)

    from src.app import make_app

    port, used_preferred_port = _pick_free_port(HOST)
    url = f"http://{HOST}:{port}"
    capture_endpoint = f"{url}/api/browser-capture"
    _safe_print()
    _safe_print("ChatVault local dashboard")
    _safe_print(f"Dashboard URL: {url}")
    _safe_print(f"Browser capture endpoint: {capture_endpoint}")
    if not used_preferred_port:
        copied = _copy_to_clipboard(url)
        _safe_print(f"Port {PREFERRED_PORT} is already busy, so ChatVault is using {port}.")
        if copied:
            _safe_print("The fallback dashboard URL was copied to your clipboard.")
        _safe_print("If the browser extension cannot connect, paste the browser capture endpoint above into its popup.")
    _safe_print()

    app = make_app(resolve_db_path())
    config = uvicorn.Config(
        app=app,
        host=HOST,
        port=port,
        log_level="warning",
        log_config=None,
        access_log=False,
        loop="asyncio",
        http="h11",
        lifespan="off",
    )
    server = uvicorn.Server(config=config)

    thread = threading.Thread(target=_run_server, args=(server,), daemon=False)
    thread.start()

    if _wait_for_healthz(HOST, port):
        _safe_print(f"ChatVault is ready: {url}")
        if _env_truthy("CHATVAULT_NO_BROWSER"):
            _safe_print("Browser auto-open skipped because CHATVAULT_NO_BROWSER is set.")
        else:
            opened = webbrowser.open(url)
            if not opened:
                _safe_print(f"If your browser did not open, paste this into it: {url}")
    else:
        _show_startup_error(
            "ChatVault could not start its local web server.\n\n"
            f"Tried: {url}\n\n"
            "Close any old ChatVault windows and try again. If this keeps happening, run Setup Doctor after the app opens or restart Windows."
        )
        server.should_exit = True

    thread.join()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
