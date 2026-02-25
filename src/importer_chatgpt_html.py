# importer_chatgpt_html.py

from bs4 import BeautifulSoup, Tag
from datetime import datetime, timezone
from typing import List, Dict, Optional
import re

from chatvault_db import create_conversation, add_message


ROLE_PATTERNS = [
    (re.compile(r"^\s*You\s*[:\-]", re.I), "user"),
    (re.compile(r"^\s*User\s*[:\-]", re.I), "user"),
    (re.compile(r"^\s*ChatGPT\s*[:\-]", re.I), "assistant"),
    (re.compile(r"^\s*Assistant\s*[:\-]", re.I), "assistant"),
]


def _detect_role(text: str) -> Optional[str]:
    for rx, role in ROLE_PATTERNS:
        if rx.match(text):
            return role
    return None


def _strip_role_prefix(text: str) -> str:
    return re.sub(r"^\s*(You|User|ChatGPT|Assistant)\s*[:\-]\s*", "", text, flags=re.I)


def _process_heading(el, current_conv: Optional[Dict], conversations: List[Dict]) -> Optional[Dict]:
    """Processes a heading element, potentially starting a new conversation."""
    title = el.get_text(" ", strip=True)
    if not title:
        return current_conv

    if current_conv and current_conv["messages"]:
        conversations.append(current_conv)
    return {"title": title[:200], "messages": []}


def _process_message_element(el, current_conv: Optional[Dict]) -> Optional[Dict]:
    """Processes a message element, adding a message to the current conversation."""
    if not hasattr(el, "name") or el.name not in ("p", "div", "li"):
        return current_conv

    text = el.get_text(" ", strip=True)
    if not text or len(text) < 3:
        return current_conv

    role = _detect_role(text)
    if not role:
        return current_conv

    content = _strip_role_prefix(text).strip()
    if not content:
        return current_conv

    if current_conv is None:
        current_conv = {"title": "Imported chat (HTML)", "messages": []}

    current_conv["messages"].append({"role": role, "content": content})
    return current_conv


def _parse_conversations_from_html(soup: BeautifulSoup) -> List[Dict]:
    body = soup.body or soup
    conversations: List[Dict] = []
    current_conv: Optional[Dict] = None

    for el in body.find_all(True):  # Iterate over Tag objects only
        if isinstance(el, Tag) and el.name in ("h1", "h2", "h3"):
            current_conv = _process_heading(el, current_conv, conversations)
        else:
            current_conv = _process_message_element(el, current_conv)

    if current_conv and current_conv["messages"]:
        conversations.append(current_conv)

    return conversations


def _save_conversations_to_db(con, conversations: List[Dict]) -> dict:
    conv_count = 0
    msg_count = 0

    for conv in conversations:
        conv_id = create_conversation(
            con=con,
            source="chatgpt_html",
            title=conv["title"],
            external_id=None,
            created_at=datetime.now(timezone.utc).isoformat()
        )
        conv_count += 1

        for m in conv["messages"]:
            add_message(
                con=con,
                conversation_id=conv_id,
                source="chatgpt_html",
                role=m["role"],
                content=m["content"]
            )
            msg_count += 1

    return {"conversations": conv_count, "messages": msg_count}


def import_chat_html(con, chat_html_path: str) -> dict:
    """
    Best-effort import of chat.html.
    Returns import statistics.
    """

    with open(chat_html_path, "rb") as f:
        soup = BeautifulSoup(f.read(), "lxml")

    conversations = _parse_conversations_from_html(soup)
    return _save_conversations_to_db(con, conversations)
