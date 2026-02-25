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
from src.chatvault_db import (
    add_message,
    add_tag,
    connect,
    create_conversation,
    list_titles,
    search_by_tag,
    search_messages,
    semantic_search_messages,
)
from src.council import run_council
from src.importer_chatgpt_html import import_chat_html
from src.importer_claude import import_claude_export
from src.insights import recommend_from_archive, summarize_range
from src.replay import replay_conversation
from src.stats import collect_stats


def _cmd_import(args: argparse.Namespace) -> int:
    con = connect(args.db)
    stats = import_chat_html(con, args.chat_html)
    print("Import complete:", stats)
    return 0


def _cmd_import_claude(args: argparse.Namespace) -> int:
    con = connect(args.db)
    stats = import_claude_export(con, args.export)
    print("Claude import complete:", stats)
    return 0


def _cmd_search(args: argparse.Namespace) -> int:
    con = connect(args.db)
    if args.semantic:
        try:
            rows = semantic_search_messages(con, args.query, limit=args.limit)
        except Exception as exc:
            print(f"Semantic search unavailable: {exc}")
            return 1
        if not rows:
            print("No semantic matches found.")
            return 0
        for score, message_id, conversation_id, title, role, snippet in rows:
            print(f"[{message_id}] sim={score:.4f} conv={conversation_id} role={role} title={title!r}")
            print(f"  {snippet}")
        return 0

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
    conversation_id = create_conversation(
        con,
        source="api_chat",
        title=args.title,
        external_id=None,
        created_at=None,
        provider="chatgpt",
    )
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
            create_embedding=True,
        )

        try:
            from src.chat_api import continue_conversation

            reply = continue_conversation(con, conversation_id=conversation_id, user_text=user_text)
        except Exception as exc:  # pragma: no cover - CLI guardrail
            print(f"assistant> [error] {exc}")
            continue
        print(f"assistant> {reply}")


def _cmd_stats(args: argparse.Namespace) -> int:
    con = connect(args.db)
    stats = collect_stats(con)
    print(f"total messages: {stats['total_messages']}")
    print(f"total conversations: {stats['total_conversations']}")
    print(f"date range: {stats['date_range'][0]} -> {stats['date_range'][1]}")
    mpc = stats["messages_per_conversation"]
    print(f"messages/conversation mean={mpc['mean']:.2f} min={mpc['min']} max={mpc['max']}")
    return 0


def _cmd_tag(args: argparse.Namespace) -> int:
    con = connect(args.db)
    add_tag(con, args.message_id, args.tag)
    print(f"Tagged message {args.message_id} with '{args.tag}'.")
    return 0


def _cmd_search_tags(args: argparse.Namespace) -> int:
    con = connect(args.db)
    rows = search_by_tag(con, args.tag, limit=args.limit)
    if not rows:
        print("No tagged messages found.")
        return 0
    for message_id, conversation_id, title, role, snippet in rows:
        print(f"[{message_id}] conv={conversation_id} role={role} title={title!r}")
        print(f"  {snippet}")
    return 0


def _cmd_titles(args: argparse.Namespace) -> int:
    con = connect(args.db)
    rows = list_titles(con)
    if not rows:
        print("No conversations found.")
        return 0
    for conversation_id, title in rows:
        print(f"{conversation_id}\t{title}")
    return 0


def _cmd_replay(args: argparse.Namespace) -> int:
    con = connect(args.db)
    count = replay_conversation(con, args.conversation_id, speed=args.speed)
    if count == 0:
        print(f"Conversation {args.conversation_id} has no messages.")
        return 1
    return 0


def _cmd_council(args: argparse.Namespace) -> int:
    con = connect(args.db)
    result = run_council(con, args.question)
    print(f"Council conversation id: {result['conversation_id']}")
    for name in ("openai", "claude", "ollama"):
        print(f"\n[{name}]\n{result.get(name, '')}\n")
    print("[synthesis]")
    print(result.get("synthesis", ""))
    return 0


def _cmd_summarize(args: argparse.Namespace) -> int:
    con = connect(args.db)
    report = summarize_range(con, args.range, use_llm=not args.no_llm)
    print(f"range: {report['range'][0]} -> {report['range'][1]}")
    print(f"messages: {report['message_count']}")
    print("\nhigh-level summary:")
    print(report["summary"])
    print("\ncommon themes:")
    for theme, count in report["common_themes"]:
        print(f"- {theme}: {count}")
    print("\nrecurring tasks:")
    for item in report["recurring_tasks"]:
        print(f"- {item}")
    print("\naction items:")
    for item in report["action_items"]:
        print(f"- {item}")
    return 0


def _cmd_recommend(args: argparse.Namespace) -> int:
    con = connect(args.db)
    rec = recommend_from_archive(con, use_llm=not args.no_llm)
    print("unfinished threads:")
    for row in rec["unfinished_threads"]:
        print(f"- conv {row['conversation_id']} ({row['title']}): {row['last_message']}")
    print("\nideas mentioned multiple times:")
    for row in rec["ideas_mentioned_multiple_times"]:
        print(f"- {row['idea']} ({row['count']})")
    print("\naction items or plans:")
    for row in rec["action_items_or_plans"]:
        print(f"- conv {row['conversation_id']} [{row['role']}] {row['text']}")
    print("\nrelated conversations:")
    for row in rec["related_conversations"]:
        print(f"- {row['conversation_a']} <-> {row['conversation_b']} via {', '.join(row['shared'])}")
    if rec.get("llm_recommendation"):
        print("\nllm recommendation:")
        print(rec["llm_recommendation"])
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser("chatvault")
    parser.add_argument("--db", default=os.getenv("CHATVAULT_DB", "chatvault.sqlite3"), help="SQLite database path")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_import = sub.add_parser("import", help="Import ChatGPT chat.html")
    p_import.add_argument("--chat-html", required=True, help="Path to chat.html")
    p_import.set_defaults(func=_cmd_import)

    p_import_claude = sub.add_parser("import-claude", help="Import Claude export JSON")
    p_import_claude.add_argument("--export", required=True, help="Path to Claude export JSON")
    p_import_claude.set_defaults(func=_cmd_import_claude)

    p_search = sub.add_parser("search", help="Search archived messages")
    p_search.add_argument("query", help="FTS query")
    p_search.add_argument("--limit", type=int, default=20, help="Max hits")
    p_search.add_argument("--semantic", action="store_true", help="Use semantic (embedding) search")
    p_search.set_defaults(func=_cmd_search)

    p_ctx = sub.add_parser("ctx", help="Show surrounding context for a message id")
    p_ctx.add_argument("message_id", type=int)
    p_ctx.add_argument("--window", type=int, default=6, help="Messages before/after")
    p_ctx.set_defaults(func=_cmd_ctx)

    p_chat = sub.add_parser("chat", help="Start live chat session")
    p_chat.add_argument("--title", default="Live chat", help="Conversation title")
    p_chat.set_defaults(func=_cmd_chat)

    p_stats = sub.add_parser("stats", help="Show archive statistics")
    p_stats.set_defaults(func=_cmd_stats)

    p_tag = sub.add_parser("tag", help="Tag a message")
    p_tag.add_argument("message_id", type=int)
    p_tag.add_argument("--tag", required=True, help="Tag name")
    p_tag.set_defaults(func=_cmd_tag)

    p_search_tags = sub.add_parser("search-tags", help="Find messages by tag")
    p_search_tags.add_argument("tag", help="Tag to search")
    p_search_tags.add_argument("--limit", type=int, default=20, help="Max hits")
    p_search_tags.set_defaults(func=_cmd_search_tags)

    p_titles = sub.add_parser("titles", help="List conversation titles")
    p_titles.set_defaults(func=_cmd_titles)

    p_replay = sub.add_parser("replay", help="Replay a conversation in timestamp order")
    p_replay.add_argument("conversation_id", type=int)
    p_replay.add_argument("--speed", type=float, default=1.0, help="Playback speed factor (higher=faster)")
    p_replay.set_defaults(func=_cmd_replay)

    p_council = sub.add_parser("council", help="Ask multiple model backends and synthesize answer")
    p_council.add_argument("--question", required=True, help="Question to ask all backends")
    p_council.set_defaults(func=_cmd_council)

    p_summarize = sub.add_parser("summarize", help="Summarize messages in a time range")
    p_summarize.add_argument("--range", default="last_30_days", choices=["last_7_days", "last_30_days", "last_90_days"], help="Time range")
    p_summarize.add_argument("--no-llm", action="store_true", help="Disable LLM enrichment")
    p_summarize.set_defaults(func=_cmd_summarize)

    p_recommend = sub.add_parser("recommend", help="Recommend follow-ups and related threads")
    p_recommend.add_argument("--no-llm", action="store_true", help="Disable LLM enrichment")
    p_recommend.set_defaults(func=_cmd_recommend)

    return parser


def main() -> int:
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
