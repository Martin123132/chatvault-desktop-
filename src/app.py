import os
import argparse
from dotenv import load_dotenv
from importer_chatgpt_html import import_chat_html

from chatvault_db import connect, get_or_create_project, attach_conversation_to_project
from importer_chatgpt import import_conversations_json
from webui import make_app


def main():
    load_dotenv()
    db_path = os.getenv("CHATVAULT_DB", "chatvault.sqlite3")

    parser = argparse.ArgumentParser("chatvault2")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_import = sub.add_parser("import", help="Import ChatGPT conversations.json")
    p_import.add_argument("--conversations-json", required=True)
    p_import.add_argument("--project", default="Unsorted", help="Project to attach ALL imported chats to (default Unsorted)")
    p_import_html = sub.add_parser("import-html", help="Import ChatGPT chat.html (fallback)")
    p_import_html.add_argument("--chat-html", required=True)
    p_import_html.add_argument("--project", default="Unsorted")

    p_run = sub.add_parser("run", help="Run the local web UI")
    p_run.add_argument("--host", default="127.0.0.1")
    p_run.add_argument("--port", type=int, default=8000)
    
    args = parser.parse_args()
    con = connect(db_path)

    if args.cmd == "import":
        stats = import_conversations_json(con, args.conversations_json)
        # attach all imported chats into a chosen project as a holding pen (manual sorting later)
        pid = get_or_create_project(con, args.project)
        # attach by external_id match: easiest is attach everything currently unassigned
        cur = con.cursor()
        cur.execute("""
            SELECT id FROM conversations
            WHERE source='chatgpt_export'
        """)
        for (cid,) in cur.fetchall():
            attach_conversation_to_project(con, pid, int(cid))

        print("Import complete:", stats)
        print(f"All imported chats attached to project '{args.project}' (you can move them later).")
        return
    
    if args.cmd == "import-html":
        stats = import_chat_html(con, args.chat_html)
        pid = get_or_create_project(con, args.project)

        # Attach all HTML-imported conversations to chosen project
        cur = con.cursor()
        cur.execute("""
            SELECT id FROM conversations
            WHERE source='chatgpt_html'
        """)
        for (cid,) in cur.fetchall():
            attach_conversation_to_project(con, pid, int(cid))

        print("HTML import complete:", stats)
        print(f"Attached to project '{args.project}'.")
        return


    if args.cmd == "run":
        app = make_app(db_path)
        import uvicorn
        uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
