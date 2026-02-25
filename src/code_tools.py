import base64
import os
import sqlite3
from typing import Any, Dict, Optional, Tuple

from excel_tools import resolve_file_path

DEFAULT_MAX_BYTES = int(os.getenv("CHATVAULT_CODE_MAX_BYTES", "200000"))


def inspect_code(
    con: sqlite3.Connection,
    file_id: str,
    offset: int = 0,
    max_bytes: Optional[int] = None,
    as_base64: bool = False,
    encoding: Optional[str] = None,
) -> Dict[str, Any]:
    path, meta, _ = resolve_file_path(con, file_id)
    size = os.path.getsize(path)

    off = max(0, int(offset))
    cap = max_bytes or DEFAULT_MAX_BYTES
    cap = max(1, cap)

    if off >= size:
        raise ValueError("offset beyond end of file")

    with open(path, "rb") as fh:
        fh.seek(off)
        data = fh.read(cap + 1)

    truncated = len(data) > cap
    if truncated:
        data = data[:cap]

    payload: Dict[str, Any] = {
        "ok": True,
        "file_path": path,
        "size_bytes": size,
        "offset": off,
        "bytes": len(data),
        "truncated": truncated,
        "meta": meta,
    }

    if as_base64:
        payload["data_base64"] = base64.b64encode(data).decode("ascii")
    else:
        enc = encoding or "utf-8"
        payload["text"] = data.decode(enc, errors="replace")
        payload["encoding"] = enc

    return payload
