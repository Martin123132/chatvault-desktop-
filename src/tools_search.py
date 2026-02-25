"""Project/local+web search helpers.

These utilities are intentionally dependency-light so the reconstructed
project remains usable even in constrained environments.
"""

from __future__ import annotations

import re
from typing import Any

import requests
from bs4 import BeautifulSoup

from chatvault_db import search_messages


USER_AGENT = "Mozilla/5.0 (compatible; ChatVaultReconstructed/1.0)"


def search_project_memory(con, query: str, project_id: int | None = None, limit: int = 12) -> list[dict[str, Any]]:
    """Search messages already stored in SQLite via FTS/LIKE fallback."""
    q = (query or "").strip()
    if not q:
        return []
    rows = search_messages(con=con, query=q, project_id=project_id, limit=max(1, int(limit or 12)))
    out = []
    for r in rows:
        # search_messages returns: (message_id, conversation_id, conversation_title, role, snippet)
        out.append({
            "message_id": int(r[0]),
            "conversation_id": int(r[1]),
            "conversation_title": r[2],
            "role": r[3],
            "snippet": r[4],
        })
    return out


def _clean_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text("\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def fetch_url(url: str, max_bytes: int | None = None) -> dict[str, Any]:
    """Fetch URL and return sanitized text and metadata."""
    u = (url or "").strip()
    if not (u.startswith("http://") or u.startswith("https://")):
        return {"ok": False, "error": "url must start with http:// or https://", "url": u}

    byte_limit = max(1024, int(max_bytes or 300_000))
    try:
        resp = requests.get(
            u,
            timeout=20,
            headers={"User-Agent": USER_AGENT},
            allow_redirects=True,
        )
        resp.raise_for_status()
    except Exception as exc:  # pragma: no cover
        return {"ok": False, "error": str(exc), "url": u}

    body = resp.content[:byte_limit]
    try:
        html = body.decode(resp.encoding or "utf-8", errors="replace")
    except Exception:
        html = body.decode("utf-8", errors="replace")

    text = _clean_text(html)
    return {
        "ok": True,
        "url": resp.url,
        "status": resp.status_code,
        "content_type": resp.headers.get("content-type", ""),
        "title": (BeautifulSoup(html, "lxml").title.string.strip() if BeautifulSoup(html, "lxml").title and BeautifulSoup(html, "lxml").title.string else ""),
        "text": text,
        "text_preview": text[:1000],
        "truncated_to_bytes": byte_limit,
    }


def web_search(query: str, max_results: int = 5) -> list[dict[str, Any]]:
    """Use DuckDuckGo HTML endpoint (no API key required)."""
    q = (query or "").strip()
    if not q:
        return []

    size = min(max(1, int(max_results or 5)), 10)
    try:
        resp = requests.get(
            "https://duckduckgo.com/html/",
            params={"q": q},
            timeout=20,
            headers={"User-Agent": USER_AGENT},
        )
        resp.raise_for_status()
    except Exception as exc:  # pragma: no cover
        return [{"error": str(exc), "query": q}]

    soup = BeautifulSoup(resp.text, "lxml")
    results: list[dict[str, Any]] = []
    for item in soup.select("div.result"):
        a = item.select_one("a.result__a")
        if not a:
            continue
        snippet = item.select_one("a.result__snippet") or item.select_one("div.result__snippet")
        results.append(
            {
                "title": a.get_text(" ", strip=True),
                "url": a.get("href", ""),
                "snippet": snippet.get_text(" ", strip=True) if snippet else "",
            }
        )
        if len(results) >= size:
            break

    if not results:
        # fallback: any links
        for a in soup.select("a[href]"):
            href = a.get("href", "")
            text = a.get_text(" ", strip=True)
            if href.startswith("http") and text:
                results.append({"title": text, "url": href, "snippet": ""})
            if len(results) >= size:
                break

    return results
