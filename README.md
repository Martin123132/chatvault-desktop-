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
python chatvault.py replay 3 --speed 1.5
python chatvault.py council --question "How do we design a CPU?"
python chatvault.py summarize --range last_30_days
python chatvault.py recommend
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


## LLM backend switch

Set backend through environment variables:

```bash
CHATVAULT_LLM_BACKEND=openai   # or anthropic / ollama
```

Commands that use LLMs (`chat`, `council`, `summarize`, `recommend`) route through a shared backend adapter.

## Stats

```bash
python chatvault.py stats
```

Shows total messages, total conversations, date range, and messages/conversation mean/min/max.

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

## Replay

Replay a conversation in timeline order with delays based on original message timestamp gaps:

```bash
python chatvault.py replay 12 --speed 1.5
```

Higher `--speed` means faster playback.

## Council mode

Council mode asks the same question to multiple backends, stores all responses, then synthesizes a final answer using OpenAI:
- OpenAI (`OPENAI_API_KEY`)
- Claude (`ANTHROPIC_API_KEY`)
- local Ollama (`http://localhost:11434`)

```bash
python chatvault.py council --question "How do we design a CPU?"
```

All intermediate responses and the synthesis are saved to SQLite in a dedicated `council` conversation.

## Summarize

Generate rolling summaries over message ranges:

```bash
python chatvault.py summarize --range last_30_days
```

Output includes:
- high-level summary
- common themes
- recurring tasks
- action items

Use `--no-llm` for heuristic-only mode.

## Recommend

Scan the full archive and suggest:
- unfinished threads
- ideas mentioned multiple times
- action items/plans
- related conversations

```bash
python chatvault.py recommend
```

Use `--no-llm` for heuristic-only recommendations.

## Semantic search

Semantic mode uses `sentence-transformers` embeddings locally and saves vectors in SQLite.
The first run may download the model once; after that it works offline.

```bash
python chatvault.py search "which conversation discussed sqlite fts ranking" --semantic --limit 5
```


## Offline mode

To run LLM features fully offline, use local Ollama and enable offline mode:

```bash
CHATVAULT_LLM_BACKEND=ollama
CHATVAULT_OFFLINE=true
ollama pull llama3
ollama serve
```

With this setup, `chat`, `council`, `summarize`, and `recommend` can run without remote LLM API calls.

## Database

By default data is stored in `chatvault.sqlite3`.

Schema includes:
- `conversations` (with `provider` + `title`)
- `messages`
- `message_tags`
- `message_embeddings`
- `messages_fts`
