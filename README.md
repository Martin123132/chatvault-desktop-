⭐ ChatVault

Your local, searchable AI conversation archive + live chat assistant

ChatVault is a small, private tool that lets you:
	•	Import your entire ChatGPT history
	•	Store it in a local SQLite database
	•	Search it instantly with powerful full-text queries (SQLite FTS5)
	•	View context around old messages
	•	Chat via the OpenAI API while everything is automatically logged
	•	Keep all your conversations local, private, and fully searchable

No cloud syncing. CLI-first. Just a fast personal knowledge vault you control.

⸻

🧰 Requirements
	•	Python 3.10+
	•	OpenAI API key (only required for live chat mode)
	•	(Optional) Your ChatGPT export ZIP if you want to import older conversations

⸻

🚀 Installation

Create a virtual environment:

python -m venv .venv

Activate it:

Windows

.venv\Scripts\activate

macOS/Linux

source .venv/bin/activate

Install dependencies:

pip install -r requirements.txt


⸻

🔧 Environment Variables

Create your .env:

cp .env.example .env

Then open .env and set:

OPENAI_API_KEY=your_key_here

Optional settings are included in .env.example.

⸻

📥 Importing your ChatGPT data
	1.	In ChatGPT: Settings → Data Controls → Export Data
	2.	OpenAI emails you a ZIP
	3.	Extract it and locate chat.html

Then import it into ChatVault:

python chatvault.py import --chat-html "path/to/chat.html"

Messages, timestamps, and metadata will be indexed locally.

⸻

🔎 Searching your archive

Full-text search using SQLite FTS5:

python chatvault.py search 'deterministic AND (cpu OR processor)'

Exact phrase search:

python chatvault.py search '"mass gap"'


⸻

🧱 Viewing message context

Each message has an ID.
To view it with surrounding messages:

python chatvault.py ctx 12345 --window 6

This shows message 12345 with 6 messages before and after.

⸻

💬 Live Chat Mode

Start a conversation, with all messages automatically stored:

python chatvault.py chat --title "CPU design session"

Inside the chat:
	•	/search <fts query> — search your archive
	•	/ctx <message_id> — view context
	•	/quit — exit

Everything is saved locally as you go.

⸻

📁 Database

ChatVault stores all data in:

chatvault.sqlite3

This database lives only on your machine and never leaves it.

⸻

🎯 Why ChatVault Exists

ChatGPT gives you thousands of conversations…
but no real way to search or organise them.

ChatVault gives you:
	•	Instant local search
	•	A permanent archive
	•	Tools to analyse your past discussions
	•	A unified interface for both old and new chats
	•	Full control and full privacy

It’s your personal memory vault for AI conversations.

⸻

🙌 Contributing

Pull requests, ideas, and feature suggestions are welcome.
Feel free to open an issue or reach out if you’d like to help shape where this goes.

⸻

📝 License

This project is released under the MIT License.
See the MIT License file for details.

