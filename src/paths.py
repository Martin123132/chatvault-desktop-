from __future__ import annotations

import os
from pathlib import Path


APP_NAME = "ChatVault"
DB_FILENAME = "chatvault.sqlite3"


def _windows_localappdata() -> Path:
    localappdata = os.getenv("LOCALAPPDATA")
    if localappdata:
        return Path(localappdata)
    return Path.home() / "AppData" / "Local"


def get_data_dir() -> Path:
    """Return per-user application data directory and ensure it exists."""
    if os.name == "nt":
        base = _windows_localappdata()
        data_dir = base / APP_NAME
    else:
        data_dir = Path.home() / ".local" / "share" / APP_NAME.lower()
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def get_default_db_path() -> str:
    return str(get_data_dir() / DB_FILENAME)


def resolve_db_path(explicit_path: str | None = None) -> str:
    if explicit_path:
        return explicit_path
    env_db = os.getenv("CHATVAULT_DB")
    if env_db:
        return env_db
    return get_default_db_path()
