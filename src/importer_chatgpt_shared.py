from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

try:
    from .chatvault_db import add_message, create_conversation
except Exception:  # pragma: no cover
    from chatvault_db import add_message, create_conversation


SHARE_HOSTS = {"chatgpt.com", "chat.openai.com"}
SHARE_PATH_RE = re.compile(r"^/share/[a-zA-Z0-9\-]+/?$")
PARSER_VERSION = "chatgpt_shared_v1"


@dataclass
class ImportSharedChatOptions:
    title_override: str | None = None
    save_raw_html: bool = False
    raw_html_dir: str | None = None
    create_embeddings: bool = True
    request_timeout_s: float = 20.0
    dry_run: bool = False


def is_chatgpt_share_url(url: str) -> bool:
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in {"http", "https"}:
        return False
    if (parsed.netloc or "").lower() not in SHARE_HOSTS:
        return False
    return bool(SHARE_PATH_RE.match(parsed.path or ""))


def _fetch_html(url: str, timeout_s: float) -> str:
    response = requests.get(
        url,
        timeout=timeout_s,
        headers={
            "User-Agent": "ChatVault/1.0 (+https://example.invalid/chatvault)",
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    response.raise_for_status()
    return response.text


def _normalize_role(author: Any) -> str | None:
    value = str(author or "").strip().lower()
    if value in {"user", "human"}:
        return "user"
    if value in {"assistant", "chatgpt"}:
        return "assistant"
    return None


def _extract_text_parts(parts: list[Any]) -> str:
    chunks: list[str] = []
    for part in parts or []:
        if isinstance(part, str):
            if part.strip():
                chunks.append(part.strip())
            continue
        if not isinstance(part, dict):
            continue
        ptype = str(part.get("type") or "").lower()
        text = part.get("text")
        if ptype == "code" and text:
            chunks.append(f"```\n{text.strip()}\n```")
        elif isinstance(text, str) and text.strip():
            chunks.append(text.strip())
    return "\n\n".join(chunks).strip()


def _extract_from_next_data(html: str) -> dict[str, Any] | None:
    soup = BeautifulSoup(html, "lxml")
    script = soup.find("script", id="__NEXT_DATA__")
    if not script or not script.string:
        return None

    payload = json.loads(script.string)
    page_props = payload.get("props", {}).get("pageProps", {})
    server_data = page_props.get("serverResponse") or page_props.get("data") or {}

    title = page_props.get("title") or server_data.get("title") or "Imported shared chat"
    messages: list[dict[str, str]] = []

    mapping = server_data.get("mapping") or {}
    if isinstance(mapping, dict):
        for node in mapping.values():
            msg = (node or {}).get("message") or {}
            role = _normalize_role((msg.get("author") or {}).get("role"))
            if not role:
                continue
            parts = (msg.get("content") or {}).get("parts") or []
            content = _extract_text_parts(parts)
            if content:
                messages.append({"role": role, "content": content})

    if not messages:
        return None

    return {
        "title": str(title).strip() or "Imported shared chat",
        "messages": messages,
    }


def _extract_from_dom(html: str) -> dict[str, Any] | None:
    soup = BeautifulSoup(html, "lxml")
    title = (soup.title.get_text(strip=True) if soup.title else "Imported shared chat") or "Imported shared chat"

    messages: list[dict[str, str]] = []
    candidates = soup.select("main article") or soup.select("article")
    for article in candidates:
        role: str | None = None
        role_text = article.get("data-message-author-role") or ""
        role = _normalize_role(role_text)
        if role is None:
            label = article.find(attrs={"data-testid": re.compile("author", re.I)})
            if label:
                role = _normalize_role(label.get_text(" ", strip=True))
        if role is None:
            continue

        for pre in article.find_all("pre"):
            pre_text = pre.get_text("\n", strip=True)
            pre.insert_before(f"\n```\n{pre_text}\n```\n")

        content = article.get_text("\n", strip=True).strip()
        if content:
            messages.append({"role": role, "content": content})

    if not messages:
        return None

    return {"title": title, "messages": messages}


def parse_shared_chat_html(html: str) -> dict[str, Any]:
    parsed = _extract_from_next_data(html) or _extract_from_dom(html)
    if not parsed or len(parsed.get("messages") or []) < 2:
        raise ValueError("Could not extract conversation messages from shared chat HTML")
    return parsed


def _save_raw_html(html: str, source_url: str, raw_html_dir: str | None = None) -> str:
    root = Path(raw_html_dir or ".")
    root.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", source_url).strip("_")[:70] or "shared_chat"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = root / f"{slug}_{stamp}.html"
    path.write_text(html, encoding="utf-8")
    return str(path)


def _find_existing_conversation_id(con: sqlite3.Connection, source_url: str) -> int | None:
    cur = con.cursor()
    cur.execute("SELECT id FROM conversations WHERE external_id=?", (source_url,))
    row = cur.fetchone()
    return int(row[0]) if row else None


def import_chatgpt_shared_url(
    con: sqlite3.Connection,
    url: str,
    options: ImportSharedChatOptions | None = None,
) -> dict[str, Any]:
    opts = options or ImportSharedChatOptions()
    source_url = (url or "").strip()
    if not is_chatgpt_share_url(source_url):
        raise ValueError("URL must be a ChatGPT shared chat link (https://chatgpt.com/share/...)")

    existing_id = _find_existing_conversation_id(con, source_url)
    if existing_id is not None:
        return {
            "ok": True,
            "conversation_id": existing_id,
            "messages": 0,
            "duplicate": True,
            "provider": "chatgpt_shared",
            "source_url": source_url,
        }

    html = _fetch_html(source_url, timeout_s=opts.request_timeout_s)
    parsed = parse_shared_chat_html(html)

    snapshot_path = None
    if opts.save_raw_html:
        snapshot_path = _save_raw_html(html, source_url, opts.raw_html_dir)

    title = (opts.title_override or parsed.get("title") or "Imported shared chat").strip()
    if opts.dry_run:
        return {
            "ok": True,
            "conversation_id": None,
            "title": title,
            "messages": len(parsed.get("messages") or []),
            "duplicate": False,
            "provider": "chatgpt_shared",
            "source_url": source_url,
            "raw_html_path": snapshot_path,
            "dry_run": True,
        }

    conversation_id = create_conversation(
        con=con,
        source="chatgpt_shared",
        title=title[:200],
        external_id=source_url,
        created_at=datetime.now(timezone.utc).isoformat(),
        provider="chatgpt_shared",
    )

    imported = 0
    for sequence, message in enumerate(parsed.get("messages") or [], start=1):
        role = _normalize_role(message.get("role"))
        content = str(message.get("content") or "").strip()
        if not role or not content:
            continue
        add_message(
            con=con,
            conversation_id=conversation_id,
            source="chatgpt_shared",
            role=role,
            content=content,
            meta={
                "source_url": source_url,
                "parser_version": PARSER_VERSION,
                "sequence": sequence,
                "imported_at": datetime.now(timezone.utc).isoformat(),
            },
            create_embedding=opts.create_embeddings,
        )
        imported += 1

    return {
        "ok": True,
        "conversation_id": conversation_id,
        "title": title,
        "messages": imported,
        "duplicate": False,
        "provider": "chatgpt_shared",
        "source_url": source_url,
        "raw_html_path": snapshot_path,
    }
