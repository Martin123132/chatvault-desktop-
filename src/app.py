from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import sys
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

SRC_DIR = Path(__file__).resolve().parent
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

try:
    from .browser_capture import BrowserCaptureMessage, BrowserCapturePayload, import_browser_capture
    from .chatvault_db import (
        add_message,
        add_tag,
        attach_conversation_to_project,
        connect,
        create_conversation,
        delete_conversation,
        get_archive_stats,
        get_conversation_messages,
        get_messages,
        get_or_create_project,
        list_conversations_in_project,
        list_conversations,
        list_project_notes,
        list_projects,
        list_titles,
        save_project_note,
        search_by_tag,
        search_messages,
        semantic_search_messages,
        set_project_model,
        set_project_system_prompt,
    )
    from .council import run_council
    from .importer_chatgpt import import_conversations_json
    from .importer_chatgpt_html import import_chat_html
    from .importer_chatgpt_shared import ImportSharedChatOptions, import_chatgpt_shared_url
    from .importer_claude import import_claude_export
    from .importer_documents import import_documents
    from .insights import recommend_from_archive, summarize_range
    from .llm_backends import generate_response
    from .paths import get_data_dir, resolve_db_path
except Exception:  # pragma: no cover
    from browser_capture import BrowserCaptureMessage, BrowserCapturePayload, import_browser_capture
    from chatvault_db import (
        add_message,
        add_tag,
        attach_conversation_to_project,
        connect,
        create_conversation,
        delete_conversation,
        get_archive_stats,
        get_conversation_messages,
        get_messages,
        get_or_create_project,
        list_conversations_in_project,
        list_conversations,
        list_project_notes,
        list_projects,
        list_titles,
        save_project_note,
        search_by_tag,
        search_messages,
        semantic_search_messages,
        set_project_model,
        set_project_system_prompt,
    )
    from council import run_council
    from importer_chatgpt import import_conversations_json
    from importer_chatgpt_html import import_chat_html
    from importer_chatgpt_shared import ImportSharedChatOptions, import_chatgpt_shared_url
    from importer_claude import import_claude_export
    from importer_documents import import_documents
    from insights import recommend_from_archive, summarize_range
    from llm_backends import generate_response
    from paths import get_data_dir, resolve_db_path


class TagPayload(BaseModel):
    tag: str


class BrowserCaptureMessagePayload(BaseModel):
    role: str
    content: str
    created_at: str | None = None


class BrowserCaptureRequest(BaseModel):
    provider: str = "chatgpt"
    page_url: str
    conversation_title: str | None = None
    captured_at: str
    messages: list[BrowserCaptureMessagePayload] = Field(default_factory=list)
    markdown: str | None = None
    project: str | None = None
    tags: list[str] = Field(default_factory=list)


class ImportSharedPayload(BaseModel):
    url: str
    title: str | None = None
    save_raw_html: bool = False
    raw_html_dir: str | None = None
    no_embeddings: bool = False
    timeout: float = 20.0
    dry_run: bool = False


class ImportPathPayload(BaseModel):
    path: str
    source: str = "documents"
    recursive: bool = True
    no_embeddings: bool = False
    chunk_size: int = 260
    chunk_overlap: int = 40


class SettingsPayload(BaseModel):
    backend: str | None = None
    offline: bool | None = None
    setup_complete: bool | None = None
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    openai_model: str | None = None
    anthropic_model: str | None = None
    ollama_host: str | None = None
    ollama_model: str | None = None
    embeddings_model: str | None = None
    clear_openai_key: bool = False
    clear_anthropic_key: bool = False


class CouncilPayload(BaseModel):
    question: str


class SummaryPayload(BaseModel):
    range: str = "last_30_days"
    use_llm: bool = False


class RecommendPayload(BaseModel):
    use_llm: bool = False


class AskVaultPayload(BaseModel):
    question: str
    project_id: int | None = None
    semantic: bool = True
    use_llm: bool = False
    limit: int = 8


class ProjectPayload(BaseModel):
    name: str
    system_prompt: str | None = None
    preferred_model: str | None = None


class ProjectConversationPayload(BaseModel):
    conversation_id: int


class ProjectNotePayload(BaseModel):
    title: str
    content: str = ""
    note_id: int | None = None


class ChatCreatePayload(BaseModel):
    title: str = "New chat"


class ChatSendPayload(BaseModel):
    message: str
    backend: str | None = None
    model: str | None = None
    temperature: float = 0.2
    max_tokens: int = 1024


def _root_dir() -> Path:
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        return Path(frozen_root)
    return Path(__file__).resolve().parent.parent


def _snippet(text: str, max_len: int = 220) -> str:
    s = (text or "").strip()
    if len(s) <= max_len:
        return s
    return s[: max_len - 3] + "..."


def _json_meta(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _message_dict(row: Any) -> dict[str, Any]:
    mid, role, created_at, content, meta_json = row
    return {
        "id": int(mid),
        "role": role,
        "created_at": created_at,
        "content": content,
        "preview": _snippet(content),
        "meta": _json_meta(meta_json),
    }


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _mask_secret(value: str | None) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if len(value) <= 8:
        return "saved"
    return f"...{value[-4:]}"


def _env_file_path() -> Path:
    return get_data_dir() / ".env"


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        value = value.strip().strip('"').strip("'")
        values[key.strip()] = value
    return values


def _format_env_value(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    if any(ch.isspace() for ch in value) or "#" in value:
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return value


def _write_env_updates(updates: dict[str, str | None]) -> Path:
    path = _env_file_path()
    existing = _read_env_file(path)
    for key, value in updates.items():
        if value is None:
            existing.pop(key, None)
            os.environ.pop(key, None)
            continue
        existing[key] = value
        os.environ[key] = value

    ordered_keys = [
        "CHATVAULT_SETUP_COMPLETE",
        "CHATVAULT_LLM_BACKEND",
        "CHATVAULT_OFFLINE",
        "OPENAI_API_KEY",
        "OPENAI_MODEL_DEFAULT",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_MODEL_DEFAULT",
        "OLLAMA_HOST",
        "OLLAMA_MODEL",
        "CHATVAULT_EMBEDDINGS_MODEL",
    ]
    lines = [
        "# ChatVault settings saved from the desktop dashboard.",
        "# You can edit these here or use Settings in the app.",
    ]
    for key in ordered_keys:
        if key in existing:
            lines.append(f"{key}={_format_env_value(existing[key])}")
    extras = sorted(k for k in existing if k not in ordered_keys)
    for key in extras:
        lines.append(f"{key}={_format_env_value(existing[key])}")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _settings_snapshot() -> dict[str, Any]:
    return {
        "setup_complete": _bool_env("CHATVAULT_SETUP_COMPLETE", False),
        "backend": os.getenv("CHATVAULT_LLM_BACKEND", "openai"),
        "offline": _bool_env("CHATVAULT_OFFLINE", False),
        "openai_key_saved": bool(os.getenv("OPENAI_API_KEY")),
        "openai_key_hint": _mask_secret(os.getenv("OPENAI_API_KEY")),
        "anthropic_key_saved": bool(os.getenv("ANTHROPIC_API_KEY")),
        "anthropic_key_hint": _mask_secret(os.getenv("ANTHROPIC_API_KEY")),
        "openai_model": os.getenv("OPENAI_MODEL_DEFAULT", "gpt-4o-mini"),
        "anthropic_model": os.getenv("ANTHROPIC_MODEL_DEFAULT", "claude-3-5-sonnet-20241022"),
        "ollama_host": os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434"),
        "ollama_model": os.getenv("OLLAMA_MODEL", "llama3"),
        "embeddings_model": os.getenv("CHATVAULT_EMBEDDINGS_MODEL", "sentence-transformers/all-MiniLM-L6-v2"),
        "env_file": str(_env_file_path()),
    }


def _chat_messages_for_llm(con: Any, conversation_id: int) -> list[dict[str, str]]:
    rows = get_messages(con, conversation_id=conversation_id, limit=200, offset=0)
    out: list[dict[str, str]] = []
    for _mid, role, _created_at, content, _meta_json in rows[-60:]:
        normalized_role = role if role in {"system", "user", "assistant"} else "user"
        out.append({"role": normalized_role, "content": content or ""})
    return out


def _safe_temp_path(root: Path, filename: str | None) -> Path:
    suffix = Path(filename or "").suffix.lower()
    safe_name = f"{uuid4().hex}{suffix or '.upload'}"
    target_dir = root / ".tmp_imports"
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir / safe_name


def _run_import_from_path(
    con: Any,
    source: str,
    path: Path,
    recursive: bool,
    no_embeddings: bool,
    chunk_size: int,
    chunk_overlap: int,
) -> dict[str, Any]:
    source_key = (source or "").strip().lower()
    if source_key in {"chatgpt", "chatgpt_json", "chatgpt-export"}:
        return {"source": "chatgpt", "stats": import_conversations_json(con, str(path))}
    if source_key in {"chatgpt_html", "html"}:
        return {"source": "chatgpt_html", "stats": import_chat_html(con, str(path))}
    if source_key in {"claude", "claude_json"}:
        return {"source": "claude", "stats": import_claude_export(con, str(path))}
    if source_key in {"documents", "docs", "research"}:
        stats = import_documents(
            con,
            str(path),
            recursive=recursive,
            chunk_size_words=max(40, int(chunk_size)),
            chunk_overlap_words=max(0, int(chunk_overlap)),
            embed=not no_embeddings,
        )
        return {"source": "documents", "stats": stats}
    raise HTTPException(status_code=400, detail="Unsupported import source")


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None


def _project_conversation_ids(con: Any, project_id: int | None) -> set[int]:
    if project_id is None:
        return set()
    cur = con.cursor()
    cur.execute("SELECT conversation_id FROM project_conversations WHERE project_id=?", (int(project_id),))
    return {int(row[0]) for row in cur.fetchall()}


def _project_exists(con: Any, project_id: int) -> bool:
    cur = con.cursor()
    cur.execute("SELECT 1 FROM projects WHERE id=?", (int(project_id),))
    return cur.fetchone() is not None


def _conversation_exists(con: Any, conversation_id: int) -> bool:
    cur = con.cursor()
    cur.execute("SELECT 1 FROM conversations WHERE id=?", (int(conversation_id),))
    return cur.fetchone() is not None


def _project_rows(con: Any) -> list[dict[str, Any]]:
    cur = con.cursor()
    rows = []
    for project_id, name in list_projects(con):
        cur.execute("SELECT COUNT(*) FROM project_conversations WHERE project_id=?", (int(project_id),))
        conversation_count = int(cur.fetchone()[0])
        cur.execute("SELECT COUNT(*) FROM project_notes WHERE project_id=?", (int(project_id),))
        note_count = int(cur.fetchone()[0])
        rows.append(
            {
                "id": int(project_id),
                "name": name,
                "conversation_count": conversation_count,
                "note_count": note_count,
            }
        )
    return rows


def _citation_rows(
    con: Any,
    question: str,
    project_id: int | None,
    semantic: bool,
    limit: int,
) -> list[dict[str, Any]]:
    capped = max(1, min(int(limit), 20))
    project_ids = _project_conversation_ids(con, project_id)
    citations: list[dict[str, Any]] = []

    if semantic:
        try:
            rows = semantic_search_messages(con, query=question, limit=max(capped, 20))
            for score, message_id, conversation_id, title, role, snippet in rows:
                if project_id is not None and int(conversation_id) not in project_ids:
                    continue
                citations.append(
                    {
                        "score": round(float(score), 4),
                        "message_id": int(message_id),
                        "conversation_id": int(conversation_id),
                        "conversation_title": title,
                        "role": role,
                        "snippet": snippet,
                        "mode": "semantic",
                    }
                )
                if len(citations) >= capped:
                    break
        except Exception:
            citations = []

    if not citations:
        rows = search_messages(con, query=question, project_id=project_id, limit=capped)
        citations = [
            {
                "message_id": int(message_id),
                "conversation_id": int(conversation_id),
                "conversation_title": title,
                "role": role,
                "snippet": snippet,
                "mode": "keyword",
            }
            for message_id, conversation_id, title, role, snippet in rows
        ]
    return citations


def _extractive_answer(question: str, citations: list[dict[str, Any]]) -> str:
    if not citations:
        return "I could not find anything in your vault for that yet."
    lines = [
        "Here are the strongest matches I found in your vault:",
        "",
    ]
    for i, item in enumerate(citations[:5], start=1):
        title = item.get("conversation_title") or "(untitled)"
        snippet = (item.get("snippet") or "").replace("[", "").replace("]", "")
        lines.append(f"{i}. {title} - {snippet}")
    lines.append("")
    lines.append("Turn on LLM answers if you want ChatVault to synthesize these into a fuller response.")
    return "\n".join(lines)


def _llm_answer(question: str, citations: list[dict[str, Any]]) -> str:
    context_lines = []
    for i, item in enumerate(citations, start=1):
        context_lines.append(
            f"[{i}] Conversation #{item['conversation_id']} / message #{item['message_id']} / "
            f"{item.get('conversation_title') or '(untitled)'} / {item.get('role') or 'message'}:\n"
            f"{item.get('snippet') or ''}"
        )
    messages = [
        {
            "role": "system",
            "content": (
                "You answer questions using the user's local ChatVault archive. "
                "Ground the answer in the supplied snippets, say when evidence is thin, "
                "and cite relevant source numbers like [1] or [2]."
            ),
        },
        {
            "role": "user",
            "content": f"Question: {question}\n\nVault snippets:\n\n" + "\n\n".join(context_lines),
        },
    ]
    return generate_response(messages=messages, temperature=0.2, max_tokens=900)


def make_app(db_path: str | None = None) -> FastAPI:
    app = FastAPI(title="ChatVault Dashboard")
    con = connect(resolve_db_path(db_path))

    root = _root_dir()
    templates_dir = root / "templates"
    static_dir = root / "static"

    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        html = (templates_dir / "index.html").read_text(encoding="utf-8")
        return HTMLResponse(html)

    @app.get("/healthz")
    def healthz() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/api/settings")
    def api_get_settings() -> dict[str, Any]:
        return _settings_snapshot()

    @app.get("/api/setup/status")
    def api_setup_status() -> dict[str, Any]:
        settings = _settings_snapshot()
        stats = get_archive_stats(con)
        has_model_connection = bool(
            settings["openai_key_saved"]
            or settings["anthropic_key_saved"]
            or settings["backend"] == "ollama"
        )
        return {
            "setup_complete": settings["setup_complete"],
            "needs_setup": not settings["setup_complete"],
            "has_model_connection": has_model_connection,
            "has_imported_data": int(stats["total_conversations"]) > 0,
            "settings": settings,
        }

    @app.post("/api/settings")
    def api_save_settings(payload: SettingsPayload) -> dict[str, Any]:
        updates: dict[str, str | None] = {}
        if payload.backend is not None:
            backend = payload.backend.strip().lower()
            if backend not in {"openai", "anthropic", "ollama"}:
                raise HTTPException(status_code=400, detail="Backend must be openai, anthropic, or ollama")
            updates["CHATVAULT_LLM_BACKEND"] = backend
        if payload.offline is not None:
            updates["CHATVAULT_OFFLINE"] = "true" if payload.offline else "false"
        if payload.setup_complete is not None:
            updates["CHATVAULT_SETUP_COMPLETE"] = "true" if payload.setup_complete else "false"
        if payload.clear_openai_key:
            updates["OPENAI_API_KEY"] = None
        elif payload.openai_api_key and payload.openai_api_key.strip():
            updates["OPENAI_API_KEY"] = payload.openai_api_key.strip()
        if payload.clear_anthropic_key:
            updates["ANTHROPIC_API_KEY"] = None
        elif payload.anthropic_api_key and payload.anthropic_api_key.strip():
            updates["ANTHROPIC_API_KEY"] = payload.anthropic_api_key.strip()
        optional_map = {
            "OPENAI_MODEL_DEFAULT": payload.openai_model,
            "ANTHROPIC_MODEL_DEFAULT": payload.anthropic_model,
            "OLLAMA_HOST": payload.ollama_host,
            "OLLAMA_MODEL": payload.ollama_model,
            "CHATVAULT_EMBEDDINGS_MODEL": payload.embeddings_model,
        }
        for key, value in optional_map.items():
            if value is not None and value.strip():
                updates[key] = value.strip()
        path = _write_env_updates(updates)
        return {"ok": True, "env_file": str(path), "settings": _settings_snapshot()}

    @app.get("/api/stats")
    def api_stats() -> dict[str, Any]:
        stats = get_archive_stats(con)
        cur = con.cursor()
        cur.execute("SELECT COUNT(*) FROM message_tags")
        tag_count = int(cur.fetchone()[0])
        cur.execute("SELECT tag, COUNT(*) FROM message_tags GROUP BY tag ORDER BY COUNT(*) DESC, tag LIMIT 12")
        top_tags = [{"tag": row[0], "count": int(row[1])} for row in cur.fetchall()]
        cur.execute("SELECT COUNT(*) FROM conversations WHERE source='document_import'")
        document_count = int(cur.fetchone()[0])
        cur.execute("SELECT COUNT(*) FROM projects")
        project_count = int(cur.fetchone()[0])
        return {
            **stats,
            "tag_count": tag_count,
            "top_tags": top_tags,
            "document_count": document_count,
            "project_count": project_count,
            "settings": _settings_snapshot(),
        }

    @app.get("/api/models")
    def api_models() -> dict[str, list[str]]:
        return {
            "backends": ["openai", "anthropic", "ollama"],
            "openai": ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini", "gpt-4.1"],
            "anthropic": ["claude-3-5-sonnet-20241022", "claude-3-5-haiku-20241022"],
            "ollama": ["llama3", "llama3.1", "mistral", "phi3"],
        }

    @app.get("/api/projects")
    def api_projects() -> list[dict[str, Any]]:
        return _project_rows(con)

    @app.post("/api/projects")
    def api_create_project(payload: ProjectPayload) -> dict[str, Any]:
        name = (payload.name or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="project name is required")
        project_id = get_or_create_project(con, name)
        if payload.system_prompt is not None:
            set_project_system_prompt(con, project_id, payload.system_prompt)
        if payload.preferred_model is not None:
            set_project_model(con, project_id, payload.preferred_model)
        return {"ok": True, "project": next(p for p in _project_rows(con) if p["id"] == project_id)}

    @app.get("/api/projects/{project_id}")
    def api_project_detail(project_id: int) -> dict[str, Any]:
        if not _project_exists(con, project_id):
            raise HTTPException(status_code=404, detail="project not found")
        cur = con.cursor()
        cur.execute(
            "SELECT id, name, COALESCE(system_prompt,''), COALESCE(preferred_model,''), created_at FROM projects WHERE id=?",
            (int(project_id),),
        )
        row = cur.fetchone()
        conversations = [
            {"id": int(cid), "title": title, "updated_at": updated_at}
            for cid, title, updated_at in list_conversations_in_project(con, int(project_id))
        ]
        notes = [
            {"id": int(nid), "title": title, "content": content, "created_at": created_at, "updated_at": updated_at}
            for nid, title, content, created_at, updated_at in list_project_notes(con, int(project_id))
        ]
        return {
            "id": int(row[0]),
            "name": row[1],
            "system_prompt": row[2],
            "preferred_model": row[3],
            "created_at": row[4],
            "conversations": conversations,
            "notes": notes,
        }

    @app.post("/api/projects/{project_id}/conversations")
    def api_project_attach_conversation(project_id: int, payload: ProjectConversationPayload) -> dict[str, Any]:
        if not _project_exists(con, project_id):
            raise HTTPException(status_code=404, detail="project not found")
        if not _conversation_exists(con, payload.conversation_id):
            raise HTTPException(status_code=404, detail="conversation not found")
        attach_conversation_to_project(con, int(project_id), int(payload.conversation_id))
        return {"ok": True, "project": api_project_detail(project_id)}

    @app.post("/api/projects/{project_id}/notes")
    def api_project_save_note(project_id: int, payload: ProjectNotePayload) -> dict[str, Any]:
        if not _project_exists(con, project_id):
            raise HTTPException(status_code=404, detail="project not found")
        try:
            note_id = save_project_note(
                con,
                int(project_id),
                title=payload.title,
                content=payload.content,
                note_id=payload.note_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True, "note_id": int(note_id), "project": api_project_detail(project_id)}

    @app.get("/api/conversations")
    def api_conversation_list(limit: int = 100) -> list[dict[str, Any]]:
        rows = list_conversations(con)[: max(1, min(int(limit), 500))]
        out = []
        for cid, title, created_at, updated_at, provider in rows:
            cur = con.cursor()
            cur.execute("SELECT COUNT(*) FROM messages WHERE conversation_id=?", (int(cid),))
            message_count = int(cur.fetchone()[0])
            out.append(
                {
                    "id": int(cid),
                    "title": title,
                    "created_at": created_at,
                    "updated_at": updated_at,
                    "provider": provider,
                    "message_count": message_count,
                }
            )
        return out

    @app.get("/api/titles")
    def api_titles() -> list[dict[str, Any]]:
        return [{"id": int(cid), "title": title} for cid, title in list_titles(con)]

    @app.get("/api/search")
    def api_search(q: str, limit: int = 25, semantic: bool = False) -> list[dict[str, Any]]:
        query = (q or "").strip()
        if not query:
            return []
        try:
            if semantic:
                rows = semantic_search_messages(con, query=query, limit=max(1, min(int(limit), 100)))
                return [
                    {
                        "score": round(float(score), 4),
                        "message_id": int(message_id),
                        "conversation_id": int(conversation_id),
                        "conversation_title": title,
                        "role": role,
                        "snippet": snippet,
                        "mode": "semantic",
                    }
                    for score, message_id, conversation_id, title, role, snippet in rows
                ]
            rows = search_messages(con, query=query, limit=max(1, min(int(limit), 200)))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return [
            {
                "message_id": int(message_id),
                "conversation_id": int(conversation_id),
                "conversation_title": title,
                "role": role,
                "snippet": snippet,
                "mode": "keyword",
            }
            for message_id, conversation_id, title, role, snippet in rows
        ]

    @app.post("/api/ask")
    def api_ask_vault(payload: AskVaultPayload) -> dict[str, Any]:
        question = (payload.question or "").strip()
        if not question:
            raise HTTPException(status_code=400, detail="question is required")
        if payload.project_id is not None and not _project_exists(con, int(payload.project_id)):
            raise HTTPException(status_code=404, detail="project not found")

        citations = _citation_rows(
            con,
            question=question,
            project_id=payload.project_id,
            semantic=bool(payload.semantic),
            limit=payload.limit,
        )
        if payload.use_llm and citations:
            try:
                answer = _llm_answer(question, citations)
            except Exception as exc:
                answer = _extractive_answer(question, citations)
                return {
                    "ok": True,
                    "answer": answer,
                    "citations": citations,
                    "used_llm": False,
                    "warning": str(exc),
                }
        else:
            answer = _extractive_answer(question, citations)
        return {"ok": True, "answer": answer, "citations": citations, "used_llm": bool(payload.use_llm and citations)}

    @app.get("/api/conversations/{conversation_id}")
    def api_conversation(conversation_id: int, limit: int = 5000, offset: int = 0) -> dict[str, Any]:
        cur = con.cursor()
        cur.execute(
            "SELECT id, COALESCE(title, ''), COALESCE(provider, 'chatgpt'), source, created_at, updated_at FROM conversations WHERE id=?",
            (conversation_id,),
        )
        conv = cur.fetchone()
        if not conv:
            raise HTTPException(status_code=404, detail="conversation not found")

        rows = get_messages(con, conversation_id=conversation_id, limit=max(1, limit), offset=max(0, offset))
        messages = [_message_dict(row) for row in rows]
        return {
            "id": int(conv[0]),
            "title": conv[1],
            "provider": conv[2],
            "source": conv[3],
            "created_at": conv[4],
            "updated_at": conv[5],
            "messages": messages,
        }

    @app.delete("/api/conversations/{conversation_id}")
    def api_delete_conversation(conversation_id: int) -> dict[str, Any]:
        if not _conversation_exists(con, conversation_id):
            raise HTTPException(status_code=404, detail="conversation not found")
        delete_conversation(con, int(conversation_id))
        return {"ok": True, "conversation_id": int(conversation_id)}

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

    @app.post("/api/browser-capture")
    def api_browser_capture(payload: BrowserCaptureRequest) -> dict[str, Any]:
        if not payload.messages:
            raise HTTPException(status_code=400, detail="messages are required")

        parsed = BrowserCapturePayload(
            provider=payload.provider,
            page_url=payload.page_url,
            conversation_title=payload.conversation_title or "Captured Chat",
            captured_at=payload.captured_at,
            messages=[BrowserCaptureMessage(role=m.role, content=m.content, created_at=m.created_at) for m in payload.messages],
            markdown=payload.markdown,
            project=payload.project,
            tags=payload.tags,
        )
        try:
            return import_browser_capture(con, parsed)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/import/shared-chat")
    def api_import_shared_chat(payload: ImportSharedPayload) -> dict[str, Any]:
        options = ImportSharedChatOptions(
            title_override=payload.title,
            save_raw_html=bool(payload.save_raw_html),
            raw_html_dir=payload.raw_html_dir,
            create_embeddings=not payload.no_embeddings,
            request_timeout_s=float(payload.timeout),
            dry_run=bool(payload.dry_run),
        )
        try:
            result = import_chatgpt_shared_url(con, payload.url, options=options)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return result

    @app.post("/api/import/upload")
    async def api_import_upload(
        source: str = Form("chatgpt"),
        recursive: bool = Form(True),
        no_embeddings: bool = Form(False),
        chunk_size: int = Form(260),
        chunk_overlap: int = Form(40),
        file: UploadFile = File(...),
    ) -> dict[str, Any]:
        target = _safe_temp_path(root, file.filename)
        target.write_bytes(await file.read())
        try:
            result = _run_import_from_path(con, source, target, recursive, no_embeddings, chunk_size, chunk_overlap)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True, "filename": file.filename, **result}

    @app.post("/api/import/path")
    def api_import_path(payload: ImportPathPayload) -> dict[str, Any]:
        source_path = Path(payload.path).expanduser()
        if not source_path.exists():
            raise HTTPException(status_code=404, detail="Path does not exist")
        try:
            result = _run_import_from_path(
                con,
                payload.source,
                source_path,
                payload.recursive,
                payload.no_embeddings,
                payload.chunk_size,
                payload.chunk_overlap,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"ok": True, "path": str(source_path), **result}

    @app.post("/api/council")
    def api_council(payload: CouncilPayload) -> dict[str, Any]:
        question = (payload.question or "").strip()
        if not question:
            raise HTTPException(status_code=400, detail="question is required")
        try:
            return run_council(con, question)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/summary")
    def api_summary(payload: SummaryPayload) -> dict[str, Any]:
        try:
            return summarize_range(con, payload.range, use_llm=bool(payload.use_llm))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/recommend")
    def api_recommend(payload: RecommendPayload) -> dict[str, Any]:
        try:
            return recommend_from_archive(con, use_llm=bool(payload.use_llm))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/replay/{conversation_id}")
    def api_replay(conversation_id: int) -> dict[str, Any]:
        rows = get_conversation_messages(con, conversation_id)
        out = []
        previous_dt: datetime | None = None
        for message_id, role, content, created_at in rows:
            current_dt = _parse_iso(created_at)
            delay_s = 0.0
            if previous_dt is not None and current_dt is not None:
                delay_s = max(0.0, min((current_dt - previous_dt).total_seconds(), 30.0))
            if current_dt is not None:
                previous_dt = current_dt
            out.append(
                {
                    "id": int(message_id),
                    "role": role,
                    "content": content,
                    "created_at": created_at,
                    "delay_s": delay_s,
                }
            )
        return {"conversation_id": int(conversation_id), "messages": out}

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

    @app.get("/api/tags/{tag}")
    def api_search_tag(tag: str, limit: int = 50) -> list[dict[str, Any]]:
        rows = search_by_tag(con, tag, limit=max(1, min(int(limit), 200)))
        return [
            {
                "message_id": int(message_id),
                "conversation_id": int(conversation_id),
                "conversation_title": title,
                "role": role,
                "snippet": snippet,
            }
            for message_id, conversation_id, title, role, snippet in rows
        ]

    @app.post("/api/chat")
    def api_chat_create(payload: ChatCreatePayload) -> dict[str, Any]:
        title = (payload.title or "New chat").strip()
        conversation_id = create_conversation(
            con,
            source="api_chat",
            title=title,
            external_id=None,
            created_at=None,
            provider=os.getenv("CHATVAULT_LLM_BACKEND", "openai"),
        )
        return {"ok": True, "conversation_id": conversation_id, "title": title}

    @app.post("/api/chat/{conversation_id}/send")
    def api_chat_send(conversation_id: int, payload: ChatSendPayload) -> dict[str, Any]:
        user_text = (payload.message or "").strip()
        if not user_text:
            raise HTTPException(status_code=400, detail="message is required")

        add_message(con, conversation_id, source="api_chat", role="user", content=user_text)
        try:
            answer = generate_response(
                messages=_chat_messages_for_llm(con, conversation_id),
                backend=payload.backend,
                model=payload.model,
                temperature=float(payload.temperature),
                max_tokens=int(payload.max_tokens),
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        message_id = add_message(
            con,
            conversation_id,
            source="api_chat",
            role="assistant",
            content=answer,
            meta={"backend": payload.backend or os.getenv("CHATVAULT_LLM_BACKEND", "openai"), "model": payload.model},
        )
        return {"ok": True, "message_id": message_id, "reply": answer}

    return app


app = make_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("src.app:app", host="127.0.0.1", port=8000, reload=False)
