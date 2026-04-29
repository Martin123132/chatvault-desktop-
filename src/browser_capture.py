from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

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


def import_browser_capture(con: Any, payload: BrowserCapturePayload) -> dict[str, Any]:
    title = (payload.conversation_title or "Captured Chat").strip() or "Captured Chat"
    source = "browser_capture"
    created = payload.captured_at or _now_iso()
    conv_id = create_conversation(
        con,
        source=source,
        title=title,
        external_id=None,
        created_at=created,
        provider=(payload.provider or "chatgpt").strip().lower() or "chatgpt",
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
                "provider": payload.provider,
                "page_url": payload.page_url,
                "conversation_title": title,
                "captured_at": payload.captured_at,
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

    return {"ok": True, "conversation_id": conv_id, "messages_imported": count}
