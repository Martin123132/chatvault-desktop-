from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

try:
    from .chatvault_db import add_tag, connect, get_messages, search_messages
except Exception:  # pragma: no cover
    from chatvault_db import add_tag, connect, get_messages, search_messages


class TagPayload(BaseModel):
    tag: str


def _root_dir() -> Path:
    return Path(__file__).resolve().parent.parent


def _snippet(text: str, max_len: int = 220) -> str:
    s = (text or "").strip()
    if len(s) <= max_len:
        return s
    return s[: max_len - 1] + "…"


def make_app(db_path: str | None = None) -> FastAPI:
    app = FastAPI(title="ChatVault Dashboard")
    con = connect(db_path or os.getenv("CHATVAULT_DB", "chatvault.sqlite3"))

    root = _root_dir()
    templates_dir = root / "templates"
    static_dir = root / "static"

    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        html = (templates_dir / "index.html").read_text(encoding="utf-8")
        return HTMLResponse(html)

    @app.get("/api/search")
    def api_search(q: str, limit: int = 25) -> list[dict[str, Any]]:
        query = (q or "").strip()
        if not query:
            return []
        rows = search_messages(con, query=query, limit=max(1, min(int(limit), 200)))
        out: list[dict[str, Any]] = []
        for message_id, conversation_id, title, role, snippet in rows:
            out.append(
                {
                    "message_id": int(message_id),
                    "conversation_id": int(conversation_id),
                    "conversation_title": title,
                    "role": role,
                    "snippet": snippet,
                }
            )
        return out

    @app.get("/api/conversations/{conversation_id}")
    def api_conversation(conversation_id: int, limit: int = 5000, offset: int = 0) -> dict[str, Any]:
        cur = con.cursor()
        cur.execute("SELECT id, COALESCE(title, ''), COALESCE(provider, 'chatgpt') FROM conversations WHERE id=?", (conversation_id,))
        conv = cur.fetchone()
        if not conv:
            raise HTTPException(status_code=404, detail="conversation not found")

        rows = get_messages(con, conversation_id=conversation_id, limit=max(1, limit), offset=max(0, offset))
        messages = []
        for mid, role, created_at, content, _meta_json in rows:
            messages.append(
                {
                    "id": int(mid),
                    "role": role,
                    "created_at": created_at,
                    "content": content,
                    "preview": _snippet(content),
                }
            )
        return {
            "id": int(conv[0]),
            "title": conv[1],
            "provider": conv[2],
            "messages": messages,
        }

    @app.get("/api/messages/{message_id}/context")
    def api_context(message_id: int, window: int = 6) -> dict[str, Any]:
        cur = con.cursor()
        cur.execute("SELECT conversation_id FROM messages WHERE id=?", (int(message_id),))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="message not found")

        conversation_id = int(row[0])
        cur.execute(
            """
            SELECT id, role, content, created_at
            FROM messages
            WHERE conversation_id=?
            ORDER BY id ASC
            """,
            (conversation_id,),
        )
        rows = cur.fetchall()
        idx = next((i for i, r in enumerate(rows) if int(r[0]) == int(message_id)), None)
        if idx is None:
            raise HTTPException(status_code=404, detail="message not found in conversation")

        start = max(0, idx - max(0, int(window)))
        end = min(len(rows), idx + max(0, int(window)) + 1)
        items = []
        for i in range(start, end):
            mid, role, content, created_at = rows[i]
            items.append(
                {
                    "id": int(mid),
                    "role": role,
                    "created_at": created_at,
                    "content": content,
                    "is_target": int(mid) == int(message_id),
                }
            )
        return {"conversation_id": conversation_id, "message_id": int(message_id), "items": items}

    @app.get("/api/messages/{message_id}/tags")
    def api_list_tags(message_id: int) -> dict[str, Any]:
        cur = con.cursor()
        cur.execute("SELECT tag FROM message_tags WHERE message_id=? ORDER BY tag COLLATE NOCASE", (int(message_id),))
        tags = [r[0] for r in cur.fetchall()]
        return {"message_id": int(message_id), "tags": tags}

    @app.post("/api/messages/{message_id}/tags")
    def api_add_tag(message_id: int, payload: TagPayload) -> dict[str, Any]:
        tag = (payload.tag or "").strip()
        if not tag:
            raise HTTPException(status_code=400, detail="tag is required")

        cur = con.cursor()
        cur.execute("SELECT 1 FROM messages WHERE id=?", (int(message_id),))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="message not found")

        add_tag(con, message_id=message_id, tag=tag)
        cur.execute("SELECT tag FROM message_tags WHERE message_id=? ORDER BY tag COLLATE NOCASE", (int(message_id),))
        tags = [r[0] for r in cur.fetchall()]
        return {"ok": True, "message_id": int(message_id), "tags": tags}

    return app


app = make_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("src.app:app", host="127.0.0.1", port=8000, reload=False)
