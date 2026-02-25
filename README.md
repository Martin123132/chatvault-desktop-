⭐ ChatVault

Your local, searchable AI conversation archive + live chat assistant.

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Core commands

```bash
python chatvault.py --help
python chatvault.py import --chat-html path/to/chat.html
python chatvault.py import-claude --export path/to/claude_export.json
python chatvault.py search "transformer AND memory"
python chatvault.py search "how do I optimize this" --semantic --limit 5
python chatvault.py ctx 42 --window 6
python chatvault.py stats
python chatvault.py titles
python chatvault.py tag 42 --tag research
python chatvault.py search-tags research
```

## ChatGPT HTML import

```bash
python chatvault.py import --chat-html exports/chat.html
```

Notes:
- Conversation titles are generated automatically from the first user message.
- Message embeddings are generated during import for semantic search.

## Claude import

Use a Claude export JSON file and import with:

```bash
python chatvault.py import-claude --export exports/claude.json
```

Imported conversations use the same schema and store `provider='claude'` in the conversation metadata column.

## Stats

```bash
python chatvault.py stats
```

Example output:

```text
total messages: 240
total conversations: 16
date range: 2024-01-09T12:03:11+00:00 -> 2025-02-15T17:49:22+00:00
messages/conversation mean=15.00 min=2 max=48
```

## Tagging

Add tags to messages and query by tag:

```bash
python chatvault.py tag 101 --tag bug
python chatvault.py search-tags bug
```

## Titles

List all conversation IDs and titles:

```bash
python chatvault.py titles
```

## Semantic search

Semantic mode uses `sentence-transformers` embeddings saved in SQLite.

```bash
python chatvault.py search "which conversation discussed sqlite fts ranking" --semantic --limit 5
```

## Database

By default data is stored in `chatvault.sqlite3`.

Schema includes:
- `conversations` (with `provider` + `title`)
- `messages`
- `message_tags`
- `message_embeddings`
- `messages_fts`
