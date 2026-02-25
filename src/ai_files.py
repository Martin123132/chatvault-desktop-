import base64
import hashlib
import os
import uuid
import sqlite3
from typing import Any, Dict

from chatvault_db import add_message

UPLOAD_ROOT = os.path.abspath(os.getenv("CHATVAULT_UPLOAD_DIR", "uploads"))


def _ensure_upload_dir(conversation_id: int) -> str:
    dest = os.path.join(UPLOAD_ROOT, str(conversation_id))
    os.makedirs(dest, exist_ok=True)
    return dest


def save_ai_file(
    con: sqlite3.Connection,
    conversation_id: int,
    filename: str,
    data_bytes: bytes,
    content_type: str | None = None,
) -> Dict[str, Any]:
    if not filename:
        raise ValueError("filename is required")
    if data_bytes is None:
        raise ValueError("data_bytes is required")

    dest_dir = _ensure_upload_dir(conversation_id)
    suffix = os.path.splitext(filename)[1]
    unique = f"{uuid.uuid4().hex}{suffix}"
    path = os.path.abspath(os.path.join(dest_dir, unique))

    sha = hashlib.sha256(data_bytes).hexdigest()
    with open(path, "wb") as fh:
        fh.write(data_bytes)

    msg_id = add_message(
        con=con,
        conversation_id=conversation_id,
        source="ai_file",
        role="assistant",
        content=(
            f"[AI generated file: {filename} | {len(data_bytes)} bytes | stored at {path} | sha256 {sha}]"
        ),
        meta={
            "filename": filename,
            "bytes": len(data_bytes),
            "content_type": content_type or "application/octet-stream",
            "stored_path": path,
            "sha256": sha,
            "source": "ai_file",
        },
    )

    return {
        "ok": True,
        "message_id": msg_id,
        "stored_path": path,
        "bytes": len(data_bytes),
        "sha256": sha,
    }
