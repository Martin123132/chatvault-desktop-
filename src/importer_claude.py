from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from chatvault_db import add_message, create_conversation


def _iso_from_any(ts: Any) -> Optional[str]:
    if ts is None:
        return None
    if isinstance(ts, (int, float)):
        try:
            if ts > 10_000_000_000:
                ts = ts / 1000.0
            return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        except Exception:
            return None
    if isinstance(ts, str):
        return ts
    return None


def _iter_conversations(data: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                yield item
        return
    if isinstance(data, dict):
        if isinstance(data.get("conversations"), list):
            for item in data["conversations"]:
                if isinstance(item, dict):
                    yield item
            return
        yield data


def _extract_messages(conv: Dict[str, Any]) -> List[Tuple[str, str, Optional[str]]]:
    message_nodes = conv.get("messages") or conv.get("chat_messages") or conv.get("items") or []
    out: List[Tuple[str, str, Optional[str]]] = []
    for node in message_nodes:
        if not isinstance(node, dict):
            continue
        role = (node.get("role") or node.get("sender") or "assistant").lower()
        content = node.get("content")
        if isinstance(content, list):
            text_parts = [part for part in content if isinstance(part, str)]
            content = "\n".join(text_parts)
        if isinstance(content, dict):
            content = content.get("text") or content.get("content") or ""
        if not isinstance(content, str):
            content = str(content or "")
        content = content.strip()
        if not content:
            continue
        created_at = _iso_from_any(node.get("created_at") or node.get("createdAt") or node.get("timestamp"))
        out.append((role, content, created_at))
    return out


def _derive_title(messages: List[Tuple[str, str, Optional[str]]], fallback: str) -> str:
    for role, content, _ in messages:
        if role == "user":
            words = content.split()
            snippet = " ".join(words[:10])
            return (snippet + "…")[:200] if len(words) > 10 else snippet[:200]
    return (fallback or "Claude import")[:200]


def import_claude_export(con, export_path: str) -> Dict[str, int]:
    with open(export_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    stats = {"conversations": 0, "messages": 0, "skipped": 0}

    for conv in _iter_conversations(data):
        try:
            messages = _extract_messages(conv)
            if not messages:
                stats["skipped"] += 1
                continue
            conv_id = create_conversation(
                con=con,
                source="claude_export",
                title=_derive_title(messages, conv.get("title") or "Claude import"),
                external_id=str(conv.get("id") or conv.get("uuid") or "") or None,
                created_at=_iso_from_any(conv.get("created_at") or conv.get("createdAt")),
                provider="claude",
            )
            stats["conversations"] += 1
            for role, content, created_at in messages:
                add_message(
                    con=con,
                    conversation_id=conv_id,
                    source="claude_export",
                    role=role,
                    content=content,
                    created_at=created_at,
                    meta={"provider": "claude"},
                    create_embedding=True,
                )
                stats["messages"] += 1
        except Exception:
            stats["skipped"] += 1
    return stats
