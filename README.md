
 
 <img width="1448" height="1086" alt="a447b52a-bd2a-44b1-9631-3459dd4d747c" src="https://github.com/user-attachments/assets/0f963a49-b261-442b-a645-bd6d72cef745" />

 <img width="1672" height="941" alt="43c9922a-00cb-466f-a52f-8a5f9af7c446" src="https://github.com/user-attachments/assets/96644868-cfb1-4b61-a87e-ecf4bab9e5b0" />


⭐ ChatVault
<img width="1448" height="1086" alt="a48e06a9-265a-4a29-8021-10c7d4821a5c" src="https://github.com/user-attachments/assets/dbe5c862-e1ba-402a-b70e-dec0b7bb5b0d" />

Your local, searchable AI conversation archive with multi-model intelligence.

ChatVault stores ChatGPT + Claude conversations locally, lets you search them, tag them, analyse them, and even run offline AI reasoning with local models like Llama 3 via Ollama.

Everything lives in your chatvault.sqlite3.
Nothing is uploaded. Nothing leaves your machine.

⸻
## Quick Start On Windows

For the easiest path:

1. Download the GitHub repo as a ZIP.
2. Extract the ZIP.
3. Open the extracted folder.
4. Double-click `START_HERE_WINDOWS.bat`.

The starter finds Python 3.10+, creates a private `.venv`, installs dependencies, starts ChatVault, and opens the local dashboard in your browser. If Python is not on PATH, set a `CHATVAULT_PYTHON` environment variable to the full `python.exe` path before launching.

## In-App Features

The dashboard includes UI screens for the main ChatVault commands:

- Imports: ChatGPT JSON, ChatGPT HTML, Claude JSON, shared ChatGPT URLs, and local research documents
- Search: keyword search and semantic search
- Conversations: full conversation viewer, message context, and tags
- Ask My Vault: ask questions over your local archive with source citations; optional LLM synthesis can turn the matches into an answer
- Projects: group conversations and notes into focused workspaces, then ask within that project scope
- Setup Doctor: check Python, dependencies, database access, model settings, imports, and extension files
- Import Wizard: guided file, folder, and shared-link importing from one panel
- Chat: start a new AI chat from the browser UI
- Council Mode: ask OpenAI, Anthropic, and Ollama backends and store the synthesis
- Insights: summaries and recommendation reports
- Replay: timeline playback for saved conversations
- Setup and Settings: save API keys, model choices, Ollama settings, first-run setup state, and offline mode without editing code

API keys are saved to the per-user ChatVault `.env` file shown in Settings.

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

- <img width="1448" height="1086" alt="9d376bd5-36b4-42ae-9b17-5e888dda13f6" src="https://github.com/user-attachments/assets/18e0e8c8-64bb-4e93-909d-efaa2e6df800" />


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

Import local research docs (PDF/Markdown/text)

python chatvault.py import-docs --path ~/papers
python chatvault.py import-docs --path ./notes.md --chunk-size 180 --chunk-overlap 30

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
	•	a synthesized final answer
	•	full reasoning trail

python chatvault.py council --question "How do we design a CPU?"

All council messages are saved in a dedicated conversation.

⸻


📚 Research Library Upgrades

You can now ingest local files into the same searchable semantic memory:

	•	PDFs (`.pdf`)
	•	Markdown (`.md`)
	•	Plain text (`.txt`)

Each file is chunked, stored as a local conversation, and can be queried with both keyword and semantic search.

```bash
python chatvault.py import-docs --path ~/research
python chatvault.py search "find papers discussing retrieval augmented generation" --semantic
```

Useful flags:

- `--no-recursive` to only ingest the top folder
- `--chunk-size` / `--chunk-overlap` to tune chunking
- `--no-embeddings` for fast ingestion without semantic vectors

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
	•	Ask My Vault citations
	•	projects and notes
	•	setup diagnostics
	•	guided imports
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
	•	projects, project_conversations, project_notes

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


---

## ChatVault Capture browser extension

ChatVault Capture is a local-only Manifest V3 browser extension in `browser_extension/` that captures visible conversations from `chatgpt.com` and saves them directly into your local ChatVault database through the FastAPI endpoint:

- `POST http://127.0.0.1:8000/api/browser-capture`

### What it supports
- Save full visible thread from popup button.
- Right-click: **Save selected text to ChatVault**.
- Right-click: **Save nearest assistant message**.
- Preserves message role (`user`/`assistant`).
- Includes exported Markdown text in capture metadata.
- Includes metadata: provider, page URL, conversation title, and capture timestamp.
- Success/failure notifications in-browser.

### Install (Chrome/Edge)
1. Start ChatVault web server locally:
   - `uvicorn src.app:app --host 127.0.0.1 --port 8000`
2. Open extension management page:
   - Chrome: `chrome://extensions`
   - Edge: `edge://extensions`
3. Enable **Developer mode**.
4. Click **Load unpacked** and choose `browser_extension/`.
5. Open a ChatGPT conversation page (`https://chatgpt.com/...`).
6. Use the popup **Save Thread** button or context menu actions.

### Security note
This extension is intentionally local-first: it only sends capture payloads to `http://127.0.0.1:8000/api/browser-capture` on your own machine. It does not call OpenAI, Anthropic, or any external capture servers.

<img width="1672" height="941" alt="189c3014-a08f-4511-9ee5-e19933356f7a" src="https://github.com/user-attachments/assets/181caa70-6495-4caa-a090-73f9a7448d73" />


