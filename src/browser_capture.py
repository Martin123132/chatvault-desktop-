from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from .chatvault_db import add_message, add_tag, attach_conversation_to_project, create_conversation, get_or_create_project


@dataclass
class BrowserCaptureMessage:
    role: str
    content: str
    created_at: str | None = None


@dataclass
class BrowserCapturePayload:
    provider: str
    page_url: str
    conversation_title: str
    captured_at: str
    messages: list[BrowserCaptureMessage]
    external_id: str | None = None
    capture_mode: str = "manual"
    replace_existing: bool = False
    markdown: str | None = None
    project: str | None = None
    tags: list[str] | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_role(role: str) -> str:
    r = (role or "").strip().lower()
    if r in {"assistant", "user", "system", "tool"}:
        return r
    return "assistant"


def _clean_tags(tags: list[str] | None) -> list[str]:
    if not tags:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for t in tags:
        s = (t or "").strip()
        if not s:
            continue
        k = s.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(s)
    return out


def _normalized_page_url(page_url: str) -> str:
    url = (page_url or "").strip()
    if not url:
        return ""
    try:
        parts = urlsplit(url)
    except Exception:
        return url
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/") or "/", "", ""))


def _capture_external_id(provider: str, page_url: str, explicit: str | None = None) -> str:
    if explicit and explicit.strip():
        return explicit.strip()
    normalized_url = _normalized_page_url(page_url)
    return f"browser_capture:{(provider or 'unknown').strip().lower()}:{normalized_url}"


def _upsert_capture_conversation(
    con: Any,
    *,
    source: str,
    provider: str,
    title: str,
    external_id: str,
    created_at: str,
) -> tuple[int, bool]:
    cur = con.cursor()
    cur.execute("SELECT id FROM conversations WHERE external_id=?", (external_id,))
    row = cur.fetchone()
    if row:
        conversation_id = int(row[0])
        cur.execute(
            "UPDATE conversations SET title=?, provider=?, updated_at=? WHERE id=?",
            (title, provider, _now_iso(), conversation_id),
        )
        con.commit()
        return conversation_id, True

    return (
        create_conversation(
            con,
            source=source,
            title=title,
            external_id=external_id,
            created_at=created_at,
            provider=provider,
        ),
        False,
    )


def _clear_conversation_messages(con: Any, conversation_id: int) -> None:
    cur = con.cursor()
    cur.execute("DELETE FROM messages WHERE conversation_id=?", (int(conversation_id),))
    con.commit()


def import_browser_capture(con: Any, payload: BrowserCapturePayload) -> dict[str, Any]:
    title = (payload.conversation_title or "Captured Chat").strip() or "Captured Chat"
    source = "browser_capture"
    created = payload.captured_at or _now_iso()
    provider = (payload.provider or "chatgpt").strip().lower() or "chatgpt"
    replace_existing = bool(payload.replace_existing or payload.capture_mode == "live")
    updated_existing = False
    external_id = None

    if replace_existing:
        external_id = _capture_external_id(provider, payload.page_url, payload.external_id)
        conv_id, updated_existing = _upsert_capture_conversation(
            con,
            source=source,
            provider=provider,
            title=title,
            external_id=external_id,
            created_at=created,
        )
        _clear_conversation_messages(con, conv_id)
    else:
        conv_id = create_conversation(
            con,
            source=source,
            title=title,
            external_id=None,
            created_at=created,
            provider=provider,
        )

    project_name = (payload.project or "").strip()
    if project_name:
        project_id = get_or_create_project(con, project_name)
        attach_conversation_to_project(con, project_id=project_id, conversation_id=conv_id)

    tags = _clean_tags(payload.tags)
    count = 0
    for message in payload.messages:
        content = (message.content or "").strip()
        if not content:
            continue
        meta: dict[str, Any] = {
            "capture": {
                "provider": provider,
                "page_url": payload.page_url,
                "conversation_title": title,
                "captured_at": payload.captured_at,
                "capture_mode": payload.capture_mode,
                "external_id": external_id,
                "markdown": payload.markdown,
            }
        }
        mid = add_message(
            con,
            conversation_id=conv_id,
            source=source,
            role=_normalize_role(message.role),
            content=content,
            created_at=message.created_at or created,
            meta=meta,
            create_embedding=False,
        )
        for tag in tags:
            add_tag(con, message_id=mid, tag=tag)
        count += 1

    return {
        "ok": True,
        "conversation_id": conv_id,
        "messages_imported": count,
        "updated_existing": updated_existing,
        "capture_mode": payload.capture_mode,
    }
