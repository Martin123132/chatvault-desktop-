from __future__ import annotations

import json
import os
import time
from datetime import datetime

from openai import OpenAI

from chatvault_db import connect, get_conversation_messages


def replay_message(db_path: str, message_id: int) -> dict:
    con = connect(db_path)
    cur = con.cursor()

    cur.execute(
        """
        SELECT api_request_json
        FROM messages
        WHERE id=? AND api_request_json IS NOT NULL
        """,
        (message_id,),
    )
    row = cur.fetchone()
    if not row:
        raise RuntimeError("Message is not replayable")

    request_payload = json.loads(row[0])

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set")

    client = OpenAI(api_key=api_key)
    resp = client.chat.completions.create(**request_payload)
    return resp.model_dump()


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None


def replay_conversation(con, conversation_id: int, speed: float = 1.0, max_sleep_s: float = 2.0) -> int:
    rows = get_conversation_messages(con, conversation_id)
    if not rows:
        return 0

    speed = max(0.01, float(speed))
    last_dt = None
    for message_id, role, content, created_at in rows:
        current_dt = _parse_iso(created_at)
        if last_dt is not None and current_dt is not None:
            delta = (current_dt - last_dt).total_seconds()
            if delta > 0:
                time.sleep(min(delta / speed, max_sleep_s))
        last_dt = current_dt if current_dt else last_dt
        print(f"[{message_id}] {created_at} {role}: {content}")
    return len(rows)
