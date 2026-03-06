
⭐ ChatVault

Your local, searchable AI conversation archive with multi-model intelligence.

ChatVault stores ChatGPT + Claude conversations locally, lets you search them, tag them, analyse them, and even run offline AI reasoning with local models like Llama 3 via Ollama.

Everything lives in your chatvault.sqlite3.
Nothing is uploaded. Nothing leaves your machine.

⸻

🚀 Installation

python -m venv .venv
source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt

Create your environment file:

cp .env.example .env

Then edit .env and set:

OPENAI_API_KEY=your_key_here     # optional if running offline

Optional fields in .env:
	•	ANTHROPIC_API_KEY – for Claude
	•	CHATVAULT_LLM_BACKEND=openai|anthropic|ollama
	•	CHATVAULT_OFFLINE=true|false
	•	OLLAMA_HOST, OLLAMA_MODEL
	•	CHATVAULT_EMBEDDINGS_MODEL (local sentence-transformers)


🖥️ Windows Desktop App (Installer)

ChatVault can be shipped as a non-technical Windows desktop app using:
- **PyInstaller** (bundled Python runtime, EXE builds)
- **Inno Setup** (one-click installer, Start Menu + Desktop shortcuts)

### What users get
- One-click `ChatVaultSetup.exe` installer
- Start Menu shortcut (`ChatVault`)
- Optional Desktop shortcut (`ChatVault`)
- App launches without terminal usage
- CLI still included (`chatvault-cli.exe`) for advanced users

### Build the Windows installer
On a Windows machine with Python 3.10+ and Inno Setup 6 installed:

```powershell
# from repo root
./scripts/build_windows.ps1
```

Artifacts:
- `dist/ChatVault.exe` (desktop launcher, no console)
- `dist/chatvault-cli.exe` (CLI, console)
- `dist/installer/ChatVaultSetup.exe` (installer)

If you only want EXEs (no installer):

```powershell
./scripts/build_windows.ps1 -SkipInstaller
```

### Data location
By default ChatVault now stores SQLite data in a per-user app data folder:
- Windows: `%LOCALAPPDATA%\ChatVault\chatvault.sqlite3`
- Linux/macOS: `~/.local/share/chatvault/chatvault.sqlite3`

You can still override with `--db` or `CHATVAULT_DB`.


⸻

📦 Core Commands

python chatvault.py --help

Import ChatGPT

python chatvault.py import --chat-html exports/chat.html

Import Claude

python chatvault.py import-claude --export exports/claude.json

Keyword search (FTS)

python chatvault.py search "transformer AND memory"

Semantic search (local embeddings)

python chatvault.py search "how do I optimize this" --semantic --limit 5

View a message with context

python chatvault.py ctx 42 --window 6

Stats overview

python chatvault.py stats

Titles list

python chatvault.py titles

Tag messages

python chatvault.py tag 101 --tag research
python chatvault.py search-tags research

Replay timelines

python chatvault.py replay 12 --speed 1.5


⸻

🤖 AI-Powered Tools

Summarise (LLM or offline heuristics)

python chatvault.py summarize --range last_30_days
python chatvault.py summarize --range last_30_days --no-llm

Recommend (unfinished ideas, repeated themes)

python chatvault.py recommend
python chatvault.py recommend --no-llm

Council Mode (multi-model debate)

Ask the same question to multiple backends (OpenAI, Anthropic, Ollama) and store:
	•	each model’s answer
	•	a synthesised final answer
	•	full reasoning trail

python chatvault.py council --question "How do we design a CPU?"

All council messages are saved in a dedicated conversation.

⸻

🔍 Semantic Search (Offline-Ready)

ChatVault uses sentence-transformers locally.
	•	First run may download the model once
	•	After that, it works fully offline
	•	Embeddings are stored in SQLite for fast recall

python chatvault.py search "sqlite fts ranking" --semantic


⸻

🔒 100% Offline Mode

To use ChatVault with local-only models (no OpenAI / no Anthropic):

CHATVAULT_LLM_BACKEND=ollama
CHATVAULT_OFFLINE=true
OLLAMA_MODEL=llama3

Then run:

ollama pull llama3
ollama serve

Now commands like:

python chatvault.py chat
python chatvault.py council
python chatvault.py summarize
python chatvault.py recommend

all run offline, using local Llama 3.

⸻

🌐 Web Dashboard (Optional)

ChatVault includes a small FastAPI dashboard for:
	•	search
	•	results
	•	conversation viewer
	•	context viewer
	•	tagging

Launch it:

uvicorn src.app:app --host 127.0.0.1 --port 8000

Open:

http://127.0.0.1:8000


⸻

🗄 Database Layout

Stored locally:

chatvault.sqlite3

Tables:
	•	conversations (title, provider, metadata)
	•	messages
	•	messages_fts (keyword search)
	•	message_tags
	•	message_embeddings

You own this file completely.

⸻

🙌 Contributing

PRs, ideas, and feature requests are welcome — especially:
	•	new importers
	•	extra reasoning tools
	•	more offline model support
	•	improved dashboard

⸻

📝 License

MIT License.
See the included file for full text.

⸻

