#!/usr/bin/env python3
"""ChatVault CLI entrypoint."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from dotenv import load_dotenv
from src.chat_api import continue_conversation
from src.chatvault_db import add_message, connect, create_conversation, search_messages
from src.importer_chatgpt_html import import_chat_html


def _cmd_import(args: argparse.Namespace) -> int:
    con = connect(args.db)
    stats = import_chat_html(con, args.chat_html)
    print("Import complete:", stats)
    return 0


def _cmd_search(args: argparse.Namespace) -> int:
    con = connect(args.db)
    rows = search_messages(con, args.query, limit=args.limit)
    if not rows:
        print("No matches found.")
        return 0

    for message_id, conversation_id, title, role, snippet in rows:
        print(f"[{message_id}] conv={conversation_id} role={role} title={title!r}")
        print(f"  {snippet}")
    return 0


def _cmd_ctx(args: argparse.Namespace) -> int:
    con = connect(args.db)
    cur = con.cursor()
    cur.execute("SELECT conversation_id FROM messages WHERE id=?", (int(args.message_id),))
    row = cur.fetchone()
    if not row:
        print(f"Message id {args.message_id} not found.")
        return 1

    conversation_id = int(row[0])
    cur.execute(
        """
        SELECT id, role, content, created_at
        FROM messages
        WHERE conversation_id=?
        ORDER BY id ASC
        """,
        (conversation_id,),
    )
    messages = cur.fetchall()
    idx = next((i for i, r in enumerate(messages) if int(r[0]) == int(args.message_id)), None)
    if idx is None:
        print(f"Message id {args.message_id} not found in conversation {conversation_id}.")
        return 1

    start = max(0, idx - int(args.window))
    end = min(len(messages), idx + int(args.window) + 1)
    print(f"Conversation {conversation_id}, showing messages {start + 1}..{end} of {len(messages)}")
    for i in range(start, end):
        mid, role, content, created_at = messages[i]
        marker = ">>" if int(mid) == int(args.message_id) else "  "
        print(f"{marker} [{mid}] {created_at} {role}: {content}")
    return 0


def _cmd_chat(args: argparse.Namespace) -> int:
    con = connect(args.db)
    conversation_id = create_conversation(con, source="api_chat", title=args.title, external_id=None, created_at=None)
    print(f"Started conversation {conversation_id}. Type /quit to exit.")

    while True:
        try:
            user_text = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye.")
            return 0

        if not user_text:
            continue
        if user_text == "/quit":
            print("Bye.")
            return 0

        add_message(
            con=con,
            conversation_id=conversation_id,
            source="api_chat",
            role="user",
            content=user_text,
        )

        try:
            reply = continue_conversation(con, conversation_id=conversation_id, user_text=user_text)
        except Exception as exc:  # pragma: no cover - CLI guardrail
            print(f"assistant> [error] {exc}")
            continue
        print(f"assistant> {reply}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser("chatvault")
    parser.add_argument("--db", default=os.getenv("CHATVAULT_DB", "chatvault.sqlite3"), help="SQLite database path")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_import = sub.add_parser("import", help="Import ChatGPT chat.html")
    p_import.add_argument("--chat-html", required=True, help="Path to chat.html")
    p_import.set_defaults(func=_cmd_import)

    p_search = sub.add_parser("search", help="Search archived messages")
    p_search.add_argument("query", help="FTS query")
    p_search.add_argument("--limit", type=int, default=20, help="Max hits")
    p_search.set_defaults(func=_cmd_search)

    p_ctx = sub.add_parser("ctx", help="Show surrounding context for a message id")
    p_ctx.add_argument("message_id", type=int)
    p_ctx.add_argument("--window", type=int, default=6, help="Messages before/after")
    p_ctx.set_defaults(func=_cmd_ctx)

    p_chat = sub.add_parser("chat", help="Start live chat session")
    p_chat.add_argument("--title", default="Live chat", help="Conversation title")
    p_chat.set_defaults(func=_cmd_chat)

    return parser


def main() -> int:
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
