# ⭐ ChatVault

Your local, searchable AI conversation archive + live chat assistant.

ChatVault lets you:

- Import your ChatGPT and Claude histories
- Store them in a local SQLite database
- Search with both keyword (FTS) and semantic search
- View context around any message
- Tag important messages
- See stats and titles for conversations
- Replay timelines, summarise periods, and get recommendations
- Run “council” multi-model debates and store the results
- Browse everything via a minimal web dashboard

All data lives **locally** in your own `chatvault.sqlite3` file.

---

## 🚀 Install

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt

Create your environment file:

cp .env.example .env

Then edit .env and set at least:

OPENAI_API_KEY=your_openai_key_here

Optional keys (if you use them) can also go in .env, for example:
	•	ANTHROPIC_API_KEY – for Claude
	•	OLLAMA_HOST – if you use Ollama locally

⸻

📦 Core CLI commands

From the repo root (with the venv active):

python chatvault.py --help

Typical usage:

# Import ChatGPT HTML export
python chatvault.py import --chat-html exports/chat.html

# Import Claude JSON export
python chatvault.py import-claude --export exports/claude.json

# Keyword search (SQLite FTS)
python chatvault.py search "transformer AND memory"

# Semantic search (embeddings)
python chatvault.py search "how do I optimize this" --semantic --limit 5

# View a message with context
python chatvault.py ctx 42 --window 6

# Live chat session (logs everything to the DB)
python chatvault.py chat --title "CPU design session"

By default, data is stored in chatvault.sqlite3.
You can override it with --db path/to/other.sqlite3 on any command if you like.

⸻

📥 ChatGPT HTML import

Export from ChatGPT via:

Settings → Data Controls → Export Data

You’ll get a ZIP in your email. Extract it and find chat.html, then run:

python chatvault.py import --chat-html exports/chat.html

Notes:
	•	Conversation titles are generated automatically from the first user message.
	•	Message embeddings are generated during import for semantic search (if the embedding backend is available).

⸻

🤖 Claude import

Use a Claude export JSON file and import with:

python chatvault.py import-claude --export exports/claude.json

Imported conversations reuse the same schema and store provider = 'claude' in the conversations table.

⸻

📊 Stats

Basic archive stats:

python chatvault.py stats

Example output:

total messages: 240
total conversations: 16
date range: 2024-01-09T12:03:11+00:00 -> 2025-02-15T17:49:22+00:00
messages/conversation mean=15.00 min=2 max=48


⸻

🏷 Tagging

Tag important messages and search by tag:

python chatvault.py tag 101 --tag bug
python chatvault.py tag 101 --tag research

python chatvault.py search-tags bug

Tags are stored in a message_tags table linked to message IDs.

⸻

🧾 Titles

List all conversation IDs and titles:

python chatvault.py titles

Titles are auto-generated on import (from the first user message), but you can use this to quickly scan what’s in the archive.

⸻

🔍 Semantic search

Semantic search uses embeddings stored in SQLite:

python chatvault.py search "which conversation discussed sqlite fts ranking" --semantic --limit 5

If the sentence-transformers model or embedding backend isn’t available, ChatVault will fall back gracefully and print a clear warning.

⸻

🎞 Replay

Replay a conversation as a timeline:

python chatvault.py replay 1 --speed 1.5

Messages are printed in chronological order with delays based on timestamp gaps, scaled by --speed (higher speed = faster replay).

⸻

🧠 Summarise

Generate a high-level summary over a time range:

# Last 30 days, with LLM enrichment
python chatvault.py summarize --range last_30_days

# Run without calling any LLMs (heuristic only)
python chatvault.py summarize --range last_30_days --no-llm

The summariser can include:
	•	overall summary
	•	themes
	•	recurring tasks
	•	action items

⸻

📌 Recommend

Get suggestions on what to revisit:

# Use LLM to enrich suggestions
python chatvault.py recommend

# Heuristic only, no LLM calls
python chatvault.py recommend --no-llm

Recommendations may include:
	•	unfinished threads
	•	repeated ideas
	•	action items or plans
	•	related conversations worth revisiting

⸻

🏛 Council mode

Run a multi-model “council” on a question and store all responses plus a synthesis:

python chatvault.py council --question "How do we design a CPU?"

The council workflow:
	•	Sends the same question to multiple backends (e.g. OpenAI, Claude, possibly local models)
	•	Stores each model’s answer as messages in the database
	•	Uses OpenAI to synthesise a final unified answer
	•	Saves the whole exchange as a dedicated council conversation

This turns ChatVault into a local log of multi-agent debates.

⸻

🗂 Database layout

By default, data is stored in:

chatvault.sqlite3

Core tables include:
	•	conversations (with provider, title, etc.)
	•	messages
	•	messages_fts (full-text index)
	•	message_tags
	•	message_embeddings

You own this file; it never leaves your machine.

⸻

🌐 Web dashboard (optional)

ChatVault also ships with a small FastAPI dashboard in src/app.py with:
	•	search bar
	•	results list
	•	conversation viewer
	•	context viewer
	•	tag panel

To run it (example):

# Inside your virtual environment
uvicorn src.app:app --host 127.0.0.1 --port 8000

Then open:

http://127.0.0.1:8000

in your browser.

⸻

🙌 Contributing

Ideas, issues, and pull requests are welcome.

You can:
	•	file bugs
	•	suggest new import formats
	•	improve the web UI
	•	extend council/semantic workflows

⸻

📝 License

ChatVault is released under the MIT License.
See the MIT License file for full details.

---

