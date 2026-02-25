# ChatVault (Local searchable conversation archive)

## What you need
- Python 3.10+
- An OpenAI API key (for the live chat mode)
- Your ChatGPT export ZIP if you want to import old chats

## Install
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt

Copy .env.example to .env and set OPENAI_API_KEY.

## Import your existing ChatGPT history
1) In ChatGPT: Settings -> Data Controls -> Export Data
2) Download the ZIP from your email
3) Extract it, locate 'chat.html'

Then:
python chatvault.py import --chat-html "path/to/chat.html"

## Search (fast keyword search)
python chatvault.py search 'deterministic AND (cpu OR processor)'
python chatvault.py search '"mass gap"'

## View context around a hit
python chatvault.py ctx 12345 --window 6

## Chat via API and store everything
python chatvault.py chat --title "CPU design session"
Inside the chat:
- /search <fts query>
- /ctx <message_id>
- /quit
