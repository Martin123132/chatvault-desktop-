# ⭐ **ChatVault**

### *Your local, searchable AI conversation archive + live chat assistant*

ChatVault is a small, private tool that lets you:

* Import your entire ChatGPT history
* Store it in a local SQLite database
* Search it instantly with powerful full-text queries
* View context around old messages
* Chat via the OpenAI API while everything is automatically logged
* Keep all your conversations **local, private, and fully searchable**

No cloud syncing. No web UI. Just a fast local knowledge vault you control.

---

## 🧰 **Requirements**

* **Python 3.10+**
* **OpenAI API key** (only needed for the live chat mode)
* *(Optional)* Your ChatGPT export ZIP if you want to import older conversations

---

## 🚀 **Installation**

```bash
python -m venv .venv
```

### Activate the virtual environment

**Windows:**

```bash
.venv\Scripts\activate
```

**macOS/Linux:**

```bash
source .venv/bin/activate
```

### Install dependencies

```bash
pip install -r requirements.txt
```

### Environment variables

Copy the example file:

```bash
cp .env.example .env
```

Then open `.env` and set:

```
OPENAI_API_KEY=your_key_here
```

---

## 📥 **Importing your ChatGPT data**

1. In ChatGPT:
   **Settings → Data Controls → Export Data**
2. The ZIP will be emailed to you.
3. Extract it and locate the file:
   **chat.html**

Then run:

```bash
python chatvault.py import --chat-html "path/to/chat.html"
```

ChatVault will parse messages, timestamps, and metadata, then store everything locally.

---

## 🔎 **Searching your archive**

ChatVault uses fast full-text search (SQLite FTS5).

Examples:

```bash
python chatvault.py search 'deterministic AND (cpu OR processor)'
```

Exact phrase search:

```bash
python chatvault.py search '"mass gap"'
```

---

## 🧱 **Viewing message context**

Every message has an internal ID. To view it with nearby messages:

```bash
python chatvault.py ctx 12345 --window 6
```

This shows the message and 6 messages before + after it.

---

## 💬 **Live Chat Mode (API)**

Start a conversation and have ChatVault archive every exchange automatically:

```bash
python chatvault.py chat --title "CPU design session"
```

Inside the chat, you can use:

* `/search <fts query>` — search stored messages
* `/ctx <message_id>` — show context
* `/quit` — exit the chat

All live messages are saved to the database as you go.

---

## 📁 **Database**

ChatVault stores everything locally in:

```
chatvault.sqlite3
```

You own it — it never leaves your computer.

---

## 🎯 **Why ChatVault Exists**

ChatGPT gives you thousands of conversations… but no good way to search them.

ChatVault fixes that by giving you:

* Instant local search
* A permanent archive
* Tools to analyze your past discussions
* A combined interface for new + old conversations
* Full control of your data

It’s your personal memory bank for AI chats.

---
---

## 🙌 **Contributing**

Pull requests, ideas, and feature suggestions are always welcome.
Feel free to open an issue or reach out if you’d like to help shape where this goes.

---
