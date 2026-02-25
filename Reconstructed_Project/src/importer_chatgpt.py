import json
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timezone

from chatvault_db import upsert_conversation_from_export, add_message


def _iso_from_ts(ts: Optional[float]) -> Optional[str]:
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    except Exception:
        return None


def _node_to_messages(node: Dict[str, Any]) -> List[Tuple[str, str]]:
    """
    Extract (role, content) from an export node.
    Handles common shapes seen in conversations.json.
    """
    msg = (node or {}).get("message")
    if not msg:
        return []

    author = (msg.get("author") or {}).get("role") or "assistant"
    content_obj = msg.get("content") or {}
    content_obj.get("content_type")

    parts: List[str]
    # fallback: try parts anyway, else stringify lightly
    parts = content_obj.get("parts") or []

    text = "\n".join([p for p in parts if isinstance(p, str)]).strip()
    if not text:
        return []

    return [(author, text)]


def _find_fallback_leaf_node(mapping: Dict[str, Any]) -> Optional[str]:
    """Find a leaf-ish node as a fallback."""
    for nid, node in mapping.items():
        if not (node or {}).get("children") and (node or {}).get("message"):
            return nid
    return None


def _reconstruct_active_path(mapping: Dict[str, Any], current_node_id: Optional[str]) -> List[str]:
    """
    Reconstruct the "active" message path by walking parent links from current_node backwards.
    Returns node_ids from root->...->current.
    """
    if not mapping:
        return []

    if not current_node_id or current_node_id not in mapping:
        current_node_id = _find_fallback_leaf_node(mapping)

    if not current_node_id or current_node_id not in mapping:
        return []

    path_rev = []
    nid = current_node_id
    seen = set()
    while nid and nid in mapping and nid not in seen:
        seen.add(nid)
        path_rev.append(nid)
        nid = (mapping[nid] or {}).get("parent")

    return list(reversed(path_rev))


def _process_conversation(con, conv: Dict[str, Any]) -> Tuple[int, int]:
    """Process a single conversation, return (message_count, 1 if success else 0)."""
    external_id = conv.get("id") or conv.get("conversation_id")
    if not external_id:
        raise ValueError("Conversation has no ID")
    title = conv.get("title") or "Untitled"
    create_ts = conv.get("create_time")
    update_ts = conv.get("update_time")

    conv_id = upsert_conversation_from_export(
        con=con,
        external_id=external_id,
        title=title[:200],
        created_at=_iso_from_ts(create_ts),
        updated_at=_iso_from_ts(update_ts),
    )

    mapping = conv.get("mapping") or {}
    current_node = conv.get("current_node") or conv.get("current_node_id")
    node_path = _reconstruct_active_path(mapping, current_node)

    message_count = 0
    for node_id in node_path:
        node = mapping.get(node_id) or {}
        if not node.get("message"):
            continue

        msg = node.get("message") or {}
        ts = _iso_from_ts(msg.get("create_time"))

        for role, content in _node_to_messages(node):
            add_message(
                con=con,
                conversation_id=conv_id,
                source="chatgpt_export",
                role=role,
                content=content,
                created_at=ts,
                external_node_id=node_id,
                parent_external_node_id=node.get("parent"),
                meta={"export": True},
            )
            message_count += 1
    return message_count, 1


def import_conversations_json(con, conversations_json_path: str) -> Dict[str, int]:
    """
    Imports ALL conversations from conversations.json.
    Returns basic stats.
    """
    with open(conversations_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    conversations = data if isinstance(data, list) else data.get("conversations") or []

    stats = {"conversations": 0, "messages": 0, "skipped": 0}

    for conv in conversations:
        try:
            msg_count, conv_count = _process_conversation(con, conv)
            stats["messages"] += msg_count
            stats["conversations"] += conv_count
        except Exception:
            stats["skipped"] += 1
            continue

    return stats
