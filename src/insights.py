from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Tuple

from chatvault_db import get_all_messages, get_messages_in_range, list_conversations
from llm_backends import generate_response
from openai import OpenAI
import os

from chatvault_db import get_all_messages, get_messages_in_range, list_conversations


_ACTION_RE = re.compile(r"\b(todo|fix|ship|implement|follow up|next step|action item|plan)\b", re.I)
_QUESTION_RE = re.compile(r"\?\s*$")


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def resolve_range(range_name: str) -> Tuple[str, str]:
    now = datetime.now(timezone.utc)
    key = (range_name or "last_30_days").strip().lower()
    if key == "last_7_days":
        start = now - timedelta(days=7)
    elif key == "last_90_days":
        start = now - timedelta(days=90)
    else:
        start = now - timedelta(days=30)
    return _iso(start), _iso(now)


def _top_themes(texts: List[str], n: int = 8) -> List[Tuple[str, int]]:
    words = []
    for t in texts:
        words.extend(re.findall(r"[a-zA-Z][a-zA-Z0-9_\-]{3,}", t.lower()))
    stop = {"that", "this", "with", "from", "have", "there", "about", "would", "should", "could", "what", "when", "where", "which", "into"}
    counts = Counter(w for w in words if w not in stop)
    return counts.most_common(n)


def summarize_range(con, range_name: str, use_llm: bool = True) -> Dict[str, object]:
    start_iso, end_iso = resolve_range(range_name)
    rows = get_messages_in_range(con, start_iso, end_iso)
    texts = [r[3] for r in rows if r[3]]
    action_items = [t for t in texts if _ACTION_RE.search(t)]
    themes = _top_themes(texts)
    recurring_tasks = [t for t in texts if any(k in t.lower() for k in ["todo", "next", "plan", "follow up"])]

    summary = (
        f"Analyzed {len(rows)} messages across {len(set(r[1] for r in rows))} conversations "
        f"from {start_iso} to {end_iso}."
    )

    if use_llm and texts:
        prompt = (
            "Summarize the following messages into: high-level summary, common themes, recurring tasks, and action items.\n\n"
            + "\n".join(texts[:200])
        )
        try:
            llm_summary = generate_response(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=1000,
            )
            if llm_summary:
                summary = llm_summary
        except Exception as exc:
            raise RuntimeError(f"LLM summarization unavailable: {exc}") from exc
    if use_llm and os.getenv("OPENAI_API_KEY") and texts:
        try:
            client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
            prompt = (
                "Summarize the following messages into: high-level summary, common themes, recurring tasks, and action items.\n\n"
                + "\n".join(texts[:200])
            )
            resp = client.chat.completions.create(
                model=os.getenv("OPENAI_MODEL_DEFAULT", "gpt-4o-mini"),
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
            )
            llm_summary = (resp.choices[0].message.content or "").strip()
            if llm_summary:
                summary = llm_summary
        except Exception:
            pass

    return {
        "range": (start_iso, end_iso),
        "message_count": len(rows),
        "summary": summary,
        "common_themes": themes,
        "recurring_tasks": recurring_tasks[:20],
        "action_items": action_items[:20],
    }


def recommend_from_archive(con, use_llm: bool = True) -> Dict[str, object]:
    messages = get_all_messages(con)
    conversations = list_conversations(con)

    by_conv = defaultdict(list)
    for mid, cid, role, content, created_at in messages:
        by_conv[cid].append((mid, role, content, created_at))

    unfinished = []
    for cid, title, created_at, updated_at, provider in conversations:
        conv_msgs = by_conv.get(cid, [])
        if not conv_msgs:
            continue
        last = conv_msgs[-1]
        if last[1] == "user" or _QUESTION_RE.search(last[2] or ""):
            unfinished.append({"conversation_id": cid, "title": title, "last_message": (last[2] or "")[:180]})

    phrase_counts = Counter()
    for _, _, _, content, _ in messages:
        for phrase in re.findall(r"\b[a-zA-Z][a-zA-Z0-9\- ]{8,40}\b", (content or "").lower()):
            phrase_counts[phrase.strip()] += 1
    repeated_ideas = [{"idea": p, "count": c} for p, c in phrase_counts.items() if c >= 3][:20]

    action_candidates = []
    for _, cid, role, content, _ in messages:
        if _ACTION_RE.search(content or ""):
            action_candidates.append({"conversation_id": cid, "role": role, "text": (content or "")[:200]})

    related = []
    for cid, items in by_conv.items():
        text = " ".join((m[2] or "") for m in items)
        kws = set(w for w, _ in _top_themes([text], n=5))
        if kws:
            related.append((cid, kws))
    related_pairs = []
    for i in range(len(related)):
        for j in range(i + 1, len(related)):
            overlap = related[i][1].intersection(related[j][1])
            if len(overlap) >= 2:
                related_pairs.append({"conversation_a": related[i][0], "conversation_b": related[j][0], "shared": sorted(overlap)})

    llm_note = ""
    if use_llm:
        prompt = (
            "Given these recommendation candidates, provide concise prioritized recommendations.\n"
            f"unfinished={unfinished[:10]}\nideas={repeated_ideas[:10]}\nactions={action_candidates[:10]}\nrelated={related_pairs[:10]}"
        )
        try:
            llm_note = generate_response(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=900,
            )
        except Exception as exc:
            raise RuntimeError(f"LLM recommendation unavailable: {exc}") from exc
    if use_llm and os.getenv("OPENAI_API_KEY"):
        try:
            client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
            prompt = (
                "Given these recommendation candidates, provide concise prioritized recommendations.\n"
                f"unfinished={unfinished[:10]}\nideas={repeated_ideas[:10]}\nactions={action_candidates[:10]}\nrelated={related_pairs[:10]}"
            )
            resp = client.chat.completions.create(
                model=os.getenv("OPENAI_MODEL_DEFAULT", "gpt-4o-mini"),
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
            )
            llm_note = (resp.choices[0].message.content or "").strip()
        except Exception:
            llm_note = ""

    return {
        "unfinished_threads": unfinished[:20],
        "ideas_mentioned_multiple_times": repeated_ideas,
        "action_items_or_plans": action_candidates[:30],
        "related_conversations": related_pairs[:20],
        "llm_recommendation": llm_note,
    }
