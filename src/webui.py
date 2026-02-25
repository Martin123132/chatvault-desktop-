from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from ai_files import save_ai_file
from chat_api import _available_models, continue_conversation, council_conversation
from chatvault_db import (
    add_message,
    attach_conversation_to_project,
    connect,
    create_conversation,
    delete_conversation,
    get_messages,
    get_or_create_project,
    get_project_model,
    get_project_system_prompt,
    list_conversations_in_project,
    list_projects,
    list_unassigned_conversations,
    search_messages,
    set_project_model,
    set_project_system_prompt,
)
from file_mod_tools import inspect_zip_file, resolve_file_path
from importer_chatgpt import import_conversations_json
from importer_chatgpt_html import import_chat_html
from replay import replay_message


def _root_dir() -> Path:
    return Path(__file__).resolve().parent.parent


def _json_meta(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


def _normalize_message_row(row) -> dict[str, Any]:
    return {
        "id": int(row[0]),
        "role": row[1],
        "created_at": row[2],
        "content": row[3],
        "meta": _json_meta(row[4]),
    }


def make_app(db_path: str) -> FastAPI:
    app = FastAPI(title="ChatVault Reconstructed")
    con = connect(db_path)

    root = _root_dir()
    static_dir = root / "static"
    templates_dir = root / "templates"

    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        html = (templates_dir / "index.html").read_text(encoding="utf-8")
        return HTMLResponse(html)

    @app.get("/api/projects")
    def api_projects():
        rows = list_projects(con)
        return [{"id": int(pid), "name": name} for pid, name in rows]

    @app.post("/api/projects")
    async def api_create_project(payload: dict[str, Any]):
        name = (payload.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="name is required")
        pid = get_or_create_project(con, name)
        return {"ok": True, "id": pid, "name": name}

    @app.get("/api/projects/{project_id}/conversations")
    def api_project_conversations(project_id: int):
        rows = list_conversations_in_project(con, project_id)
        return [{"id": int(cid), "title": title, "updated_at": updated} for cid, title, updated in rows]

    @app.get("/api/conversations/unassigned")
    def api_unassigned(limit: int = 200):
        rows = list_unassigned_conversations(con, limit=limit)
        return [{"id": int(cid), "title": title, "updated_at": updated} for cid, title, updated in rows]

    @app.post("/api/projects/{project_id}/attach")
    async def api_attach(project_id: int, payload: dict[str, Any]):
        cid = int(payload.get("conversation_id"))
        attach_conversation_to_project(con, project_id, cid)
        return {"ok": True}

    @app.post("/api/projects/{project_id}/conversations/new")
    async def api_new_conversation(project_id: int, payload: dict[str, Any]):
        title = (payload.get("title") or "New chat").strip()
        cid = create_conversation(con, source="api_chat", title=title, external_id=None, created_at=None)
        attach_conversation_to_project(con, project_id, cid)
        return {"ok": True, "conversation_id": cid, "title": title}

    @app.get("/api/conversations/{conversation_id}/messages")
    def api_messages(conversation_id: int, limit: int = 500, offset: int = 0, tail: int = 0):
        rows = get_messages(con, conversation_id, limit=max(1, limit), offset=max(0, offset))
        items = [_normalize_message_row(r) for r in rows]
        if tail and items:
            items = items[-tail:]
        return items

    @app.post("/api/conversations/{conversation_id}/reply")
    async def api_reply(conversation_id: int, payload: dict[str, Any]):
        user_text = (payload.get("message") or payload.get("user_text") or "").strip()
        project_id = payload.get("project_id")
        if not user_text:
            raise HTTPException(status_code=400, detail="message is required")

        add_message(con, conversation_id, source="api_chat", role="user", content=user_text)
        reply = continue_conversation(
            con=con,
            conversation_id=conversation_id,
            user_text=user_text,
            project_id=int(project_id) if project_id is not None else None,
        )
        return {"ok": True, "reply": reply}

    @app.post("/api/conversations/{conversation_id}/council_reply")
    async def api_council_reply(conversation_id: int, payload: dict[str, Any]):
        user_text = (payload.get("message") or payload.get("user_text") or "").strip()
        project_id = payload.get("project_id")
        if not user_text:
            raise HTTPException(status_code=400, detail="message is required")

        add_message(con, conversation_id, source="api_chat", role="user", content=user_text)
        result = council_conversation(
            con=con,
            conversation_id=conversation_id,
            user_text=user_text,
            project_id=int(project_id) if project_id is not None else None,
        )
        return result

    @app.get("/api/search")
    def api_search(q: str, project_id: int | None = None, limit: int = 50):
        rows = search_messages(con, query=q, project_id=project_id, limit=limit)
        return [
            {
                "message_id": int(r[0]),
                "conversation_id": int(r[1]),
                "conversation_title": r[2],
                "role": r[3],
                "snippet": r[4],
            }
            for r in rows
        ]

    @app.get("/api/projects/{project_id}/system_prompt")
    def api_get_prompt(project_id: int):
        return {"project_id": project_id, "system_prompt": get_project_system_prompt(con, project_id)}

    @app.put("/api/projects/{project_id}/system_prompt")
    async def api_set_prompt(project_id: int, payload: dict[str, Any]):
        set_project_system_prompt(con, project_id, payload.get("system_prompt") or "")
        return {"ok": True}

    @app.get("/api/models")
    def api_models():
        return {"models": _available_models()}

    @app.get("/api/projects/{project_id}/model")
    def api_get_model(project_id: int):
        return {"project_id": project_id, "model": get_project_model(con, project_id)}

    @app.put("/api/projects/{project_id}/model")
    async def api_set_model(project_id: int, payload: dict[str, Any]):
        set_project_model(con, project_id, payload.get("model") or "")
        return {"ok": True}

    @app.delete("/api/conversations/{conversation_id}")
    def api_delete_conversation(conversation_id: int):
        delete_conversation(con, conversation_id)
        return {"ok": True}

    @app.post("/api/messages/{message_id}/replay")
    def api_replay(message_id: int):
        return replay_message(db_path, message_id)

    @app.post("/api/import")
    async def api_import(file: UploadFile = File(...), project: str = Form("Unsorted")):
        pid = get_or_create_project(con, project)
        suffix = Path(file.filename or "").suffix.lower()

        temp_dir = root / ".tmp_imports"
        temp_dir.mkdir(parents=True, exist_ok=True)
        target = temp_dir / (file.filename or "upload.bin")
        target.write_bytes(await file.read())

        if suffix == ".json":
            stats = import_conversations_json(con, str(target))
            source = "chatgpt_export"
        elif suffix in {".html", ".htm"}:
            stats = import_chat_html(con, str(target))
            source = "chatgpt_html"
        else:
            raise HTTPException(status_code=400, detail="Upload a .json or .html export")

        cur = con.cursor()
        cur.execute("SELECT id FROM conversations WHERE source=?", (source,))
        for (cid,) in cur.fetchall():
            attach_conversation_to_project(con, pid, int(cid))
        return {"ok": True, "stats": stats, "project_id": pid}

    @app.get("/api/imports")
    def api_imports(limit: int = 200):
        cur = con.cursor()
        cur.execute(
            """
            SELECT id, source, COALESCE(title,''), created_at, updated_at
            FROM conversations
            WHERE source IN ('chatgpt_export','chatgpt_html')
            ORDER BY COALESCE(updated_at, created_at) DESC
            LIMIT ?
            """,
            (max(1, limit),),
        )
        rows = cur.fetchall()
        return [
            {
                "id": int(r[0]),
                "source": r[1],
                "title": r[2],
                "created_at": r[3],
                "updated_at": r[4],
            }
            for r in rows
        ]

    @app.post("/api/conversations/{conversation_id}/import_file")
    async def api_import_file(conversation_id: int, file: UploadFile = File(...), content_type: str | None = Form(None)):
        payload = await file.read()
        result = save_ai_file(
            con=con,
            conversation_id=conversation_id,
            filename=file.filename or "uploaded.bin",
            data_bytes=payload,
            content_type=content_type or file.content_type,
        )
        return result

    @app.post("/api/conversations/{conversation_id}/analyze_image")
    async def api_analyze_image(conversation_id: int, file: UploadFile = File(...)):
        # Minimal placeholder to keep UI functional; full multimodal chain wasn't recoverable.
        _ = conversation_id
        _ = await file.read()
        return JSONResponse({"ok": False, "error": "Image analysis module was not recoverable from archive."}, status_code=501)

    @app.get("/api/files/generated")
    def api_generated_files(limit: int = 200):
        cur = con.cursor()
        cur.execute(
            """
            SELECT id, conversation_id, created_at, meta_json
            FROM messages
            WHERE source='ai_file'
            ORDER BY id DESC
            LIMIT ?
            """,
            (max(1, limit),),
        )
        rows = cur.fetchall()
        out = []
        for mid, cid, created_at, meta_raw in rows:
            meta = _json_meta(meta_raw)
            out.append(
                {
                    "message_id": int(mid),
                    "conversation_id": int(cid),
                    "created_at": created_at,
                    "filename": meta.get("filename"),
                    "stored_path": meta.get("stored_path"),
                    "bytes": meta.get("bytes"),
                    "content_type": meta.get("content_type"),
                }
            )
        return out

    @app.get("/api/files/{message_id}/download")
    def api_download(message_id: int, filename: str | None = None):
        _ = filename
        path, _meta, _conv = resolve_file_path(con, str(message_id))
        return FileResponse(path)

    @app.get("/api/files/{message_id}/zip_entries")
    def api_zip_entries(message_id: int):
        return inspect_zip_file(con=con, file_id=str(message_id), max_entries=500)

    @app.get("/api/files/{message_id}/zip_entry")
    def api_zip_entry(message_id: int, inner_path: str, max_bytes: int = 200_000):
        import zipfile

        path, _meta, _conv = resolve_file_path(con, str(message_id))
        if not zipfile.is_zipfile(path):
            raise HTTPException(status_code=400, detail="not a zip file")

        with zipfile.ZipFile(path, "r") as zf:
            try:
                raw = zf.read(inner_path)
            except KeyError:
                raise HTTPException(status_code=404, detail="entry not found")
        clipped = raw[: max(1, max_bytes)]
        try:
            text = clipped.decode("utf-8", errors="replace")
        except Exception:
            text = ""
        return {
            "ok": True,
            "inner_path": inner_path,
            "bytes": len(raw),
            "preview_bytes": len(clipped),
            "text_preview": text,
            "base64": "" if text else __import__("base64").b64encode(clipped).decode("ascii"),
            "truncated": len(raw) > len(clipped),
        }

    return app
