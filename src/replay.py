# replay.py

import json
import os
from openai import OpenAI
from chatvault_db import connect

def replay_message(db_path: str, message_id: int) -> dict:
    con = connect(db_path)
    cur = con.cursor()

    cur.execute(
        """
        SELECT api_request_json
        FROM messages
        WHERE id=? AND api_request_json IS NOT NULL
        """,
        (message_id,)
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
