import json
import sqlite3
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional, List, Tuple

from semantic_search import DEFAULT_EMBED_MODEL, embed_text, rank_by_similarity, dumps_embedding


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

FTS_TRIGGER_SQL = r"""
CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, content, role, created_at, conv_title)
    VALUES (
        new.id,
        new.content,
        new.role,
        new.created_at,
        COALESCE((SELECT title FROM conversations WHERE id=new.conversation_id), '')
    );
END;

CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
    DELETE FROM messages_fts WHERE rowid = old.id;
END;

CREATE TRIGGER IF NOT EXISTS messages_au AFTER UPDATE ON messages BEGIN
    DELETE FROM messages_fts WHERE rowid = old.id;

    INSERT INTO messages_fts(rowid, content, role, created_at, conv_title)
    VALUES (
        new.id,
        new.content,
        new.role,
        new.created_at,
        COALESCE((SELECT title FROM conversations WHERE id=new.conversation_id), '')
    );
END;
"""

SCHEMA_SQL = r"""
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
        system_prompt TEXT,
        preferred_model TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS project_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS workflows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    cron TEXT,
    enabled INTEGER NOT NULL DEFAULT 1,
    payload_json TEXT,
    last_run TEXT,
    next_run TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,          -- 'chatgpt_export' | 'api_chat'
    external_id TEXT UNIQUE,       -- OpenAI export conversation id (if any)
    provider TEXT NOT NULL DEFAULT 'chatgpt',
    title TEXT,
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS project_conversations (
    project_id INTEGER NOT NULL,
    conversation_id INTEGER NOT NULL,
    PRIMARY KEY (project_id, conversation_id),
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL,
    source TEXT NOT NULL,
    role TEXT NOT NULL,            -- user|assistant|system|tool
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    external_node_id TEXT,         -- node id from mapping (if any)
    parent_external_node_id TEXT,  -- parent node id
    meta_json TEXT,
        api_request_json TEXT,
        api_response_json TEXT,
        request_hash TEXT,
    FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS message_tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER NOT NULL,
    tag TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(message_id, tag),
    FOREIGN KEY(message_id) REFERENCES messages(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS message_embeddings (
    message_id INTEGER PRIMARY KEY,
    embedding_json TEXT NOT NULL,
    model_name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(message_id) REFERENCES messages(id) ON DELETE CASCADE
);

-- fast full-text search (proven)
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts
USING fts5(
    content,
    role,
    created_at,
    conv_title,
    tokenize = 'porter'
);
""" + FTS_TRIGGER_SQL


def connect(db_path: str) -> sqlite3.Connection:
    con = sqlite3.connect(db_path, check_same_thread=False)
    con.executescript(SCHEMA_SQL)
    _ensure_schema_upgrades(con)
    _ensure_triggers(con)
    return con


def _ensure_schema_upgrades(con: sqlite3.Connection) -> None:
    """Adds new columns when upgrading an existing database."""
    cur = con.cursor()
    cur.execute("PRAGMA table_info(messages)")
    existing_cols = {row[1] for row in cur.fetchall()}
    added = False

    if "api_request_json" not in existing_cols:
        cur.execute("ALTER TABLE messages ADD COLUMN api_request_json TEXT")
        added = True
    if "api_response_json" not in existing_cols:
        cur.execute("ALTER TABLE messages ADD COLUMN api_response_json TEXT")
        added = True
    if "request_hash" not in existing_cols:
        cur.execute("ALTER TABLE messages ADD COLUMN request_hash TEXT")
        added = True

    if added:
        con.commit()

    cur.execute("PRAGMA table_info(conversations)")
    conv_cols = {row[1] for row in cur.fetchall()}
    if "provider" not in conv_cols:
        cur.execute("ALTER TABLE conversations ADD COLUMN provider TEXT NOT NULL DEFAULT 'chatgpt'")
        con.commit()


def _ensure_triggers(con: sqlite3.Connection) -> None:
    """Recreate FTS triggers to the latest definitions."""
    cur = con.cursor()
    cur.executescript(
        """
        DROP TRIGGER IF EXISTS messages_ai;
        DROP TRIGGER IF EXISTS messages_ad;
        DROP TRIGGER IF EXISTS messages_au;
        """
        + FTS_TRIGGER_SQL
    )
    con.commit()


def get_or_create_project(con: sqlite3.Connection, name: str) -> int:
    cur = con.cursor()
    cur.execute("SELECT id FROM projects WHERE name=?", (name,))
    row = cur.fetchone()
    if row:
        return int(row[0])

    cur.execute(
        "INSERT INTO projects(name, created_at, system_prompt, preferred_model) VALUES(?,?,?,?)",
        (name, utc_now_iso(), "", "")
    )

    con.commit()
    if cur.lastrowid is None:
        raise RuntimeError("Failed to get last row id for new project.")
    return int(cur.lastrowid)


def list_projects(con: sqlite3.Connection) -> List[Tuple[int, str]]:
    cur = con.cursor()
    cur.execute("SELECT id, name FROM projects ORDER BY name COLLATE NOCASE")
    return cur.fetchall()


def create_conversation(
    con: sqlite3.Connection,
    source: str,
    title: str,
    external_id: Optional[str],
    created_at: Optional[str],
    provider: str = "chatgpt",
) -> int:
    cur = con.cursor()
    cur.execute(
        "INSERT INTO conversations(source, external_id, provider, title, created_at, updated_at) VALUES (?,?,?,?,?,?)",
        (source, external_id, provider, title, created_at or utc_now_iso(), utc_now_iso())
    )
    con.commit()
    if cur.lastrowid is None:
        raise RuntimeError("Failed to get last row id for new conversation.")
    return int(cur.lastrowid)


def upsert_conversation_from_export(
    con: sqlite3.Connection,
    external_id: str,
    title: str,
    created_at: Optional[str],
    updated_at: Optional[str],
    provider: str = "chatgpt",
) -> int:
    cur = con.cursor()
    cur.execute("SELECT id FROM conversations WHERE external_id=?", (external_id,))
    row = cur.fetchone()
    if row:
        conv_id = int(row[0])
        cur.execute(
            "UPDATE conversations SET title=?, provider=?, created_at=COALESCE(created_at, ?), updated_at=? WHERE id=?",
            (title, provider, created_at or utc_now_iso(), updated_at or utc_now_iso(), conv_id)
        )
        con.commit()
        return conv_id

    cur.execute(
        "INSERT INTO conversations(source, external_id, provider, title, created_at, updated_at) VALUES (?,?,?,?,?,?)",
        ("chatgpt_export", external_id, provider, title, created_at or utc_now_iso(), updated_at or utc_now_iso())
    )
    con.commit()
    if cur.lastrowid is None:
        raise RuntimeError("Failed to get last row id for new conversation from export.")
    return int(cur.lastrowid)


def attach_conversation_to_project(con: sqlite3.Connection, project_id: int, conversation_id: int) -> None:
    cur = con.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO project_conversations(project_id, conversation_id) VALUES(?,?)",
        (project_id, conversation_id)
    )
    con.commit()


def list_conversations_in_project(con: sqlite3.Connection, project_id: int) -> List[Tuple[int, str, str]]:
    cur = con.cursor()
    cur.execute(
        """
        SELECT c.id, COALESCE(c.title,''), COALESCE(c.updated_at, c.created_at)
        FROM conversations c
        JOIN project_conversations pc ON pc.conversation_id=c.id
        WHERE pc.project_id=?
        ORDER BY COALESCE(c.updated_at, c.created_at) DESC
        """,
        (project_id,)
    )
    return cur.fetchall()


def list_unassigned_conversations(con: sqlite3.Connection, limit: int = 200) -> List[Tuple[int, str, str]]:
    cur = con.cursor()
    cur.execute(
        """
        SELECT c.id, COALESCE(c.title,''), COALESCE(c.updated_at, c.created_at)
        FROM conversations c
        LEFT JOIN project_conversations pc ON pc.conversation_id=c.id
        WHERE pc.conversation_id IS NULL
        ORDER BY COALESCE(c.updated_at, c.created_at) DESC
        LIMIT ?
        """,
        (limit,)
    )
    return cur.fetchall()


def add_message(
    con: sqlite3.Connection,
    conversation_id: int,
    source: str,
    role: str,
    content: str,
    created_at: Optional[str] = None,
    external_node_id: Optional[str] = None,
    parent_external_node_id: Optional[str] = None,
    meta: Optional[Dict[str, Any]] = None,
    create_embedding: bool = False,
) -> int:
    cur = con.cursor()
    cur.execute(
        """
        INSERT INTO messages(conversation_id, source, role, content, created_at, external_node_id, parent_external_node_id, meta_json)
        VALUES (?,?,?,?,?,?,?,?)
        """,
        (
            conversation_id, source, role, content, created_at or utc_now_iso(),
            external_node_id, parent_external_node_id,
            json.dumps(meta) if meta else None
        )
    )
    cur.execute("UPDATE conversations SET updated_at=? WHERE id=?", (utc_now_iso(), conversation_id))
    con.commit()
    if cur.lastrowid is None:
        raise RuntimeError("Failed to get last row id for new message.")
    message_id = int(cur.lastrowid)
    if create_embedding:
        upsert_message_embedding(con, message_id=message_id, content=content)
    return message_id


def upsert_message_embedding(con: sqlite3.Connection, message_id: int, content: str, model_name: str = DEFAULT_EMBED_MODEL) -> None:
    text = (content or "").strip()
    if not text:
        return
    try:
        vec = embed_text(text, model_name=model_name)
    except Exception:
        return
    cur = con.cursor()
    cur.execute(
        """
        INSERT INTO message_embeddings(message_id, embedding_json, model_name, created_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(message_id) DO UPDATE SET
            embedding_json=excluded.embedding_json,
            model_name=excluded.model_name,
            created_at=excluded.created_at
        """,
        (message_id, dumps_embedding(vec), model_name, utc_now_iso()),
    )
    con.commit()


def add_tag(con: sqlite3.Connection, message_id: int, tag: str) -> None:
    cur = con.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO message_tags(message_id, tag, created_at) VALUES (?, ?, ?)",
        (int(message_id), tag.strip(), utc_now_iso()),
    )
    con.commit()


def search_by_tag(con: sqlite3.Connection, tag: str, limit: int = 50) -> List[Tuple[int, int, str, str, str]]:
    cur = con.cursor()
    cur.execute(
        """
        SELECT m.id, m.conversation_id, COALESCE(c.title,''), m.role, substr(m.content, 1, 200)
        FROM message_tags t
        JOIN messages m ON m.id = t.message_id
        JOIN conversations c ON c.id = m.conversation_id
        WHERE lower(t.tag) = lower(?)
        ORDER BY m.id DESC
        LIMIT ?
        """,
        (tag.strip(), max(1, limit)),
    )
    return cur.fetchall()


def list_titles(con: sqlite3.Connection) -> List[Tuple[int, str]]:
    cur = con.cursor()
    cur.execute("SELECT id, COALESCE(title, '') FROM conversations ORDER BY id ASC")
    return cur.fetchall()


def semantic_search_messages(con: sqlite3.Connection, query: str, limit: int = 10) -> List[Tuple[float, int, int, str, str, str]]:
    qv = embed_text(query)
    cur = con.cursor()
    cur.execute(
        """
        SELECT m.id, m.conversation_id, COALESCE(c.title,''), m.role, substr(m.content,1,200), e.embedding_json
        FROM message_embeddings e
        JOIN messages m ON m.id = e.message_id
        JOIN conversations c ON c.id = m.conversation_id
        """
    )
    rows = cur.fetchall()
    ranked = rank_by_similarity(qv, rows, limit=limit)
    return ranked


def get_archive_stats(con: sqlite3.Connection) -> Dict[str, Any]:
    cur = con.cursor()
    cur.execute("SELECT COUNT(*) FROM messages")
    total_messages = int(cur.fetchone()[0])
    cur.execute("SELECT COUNT(*) FROM conversations")
    total_conversations = int(cur.fetchone()[0])
    cur.execute("SELECT MIN(created_at), MAX(created_at) FROM messages")
    min_date, max_date = cur.fetchone()
    cur.execute(
        """
        SELECT AVG(cnt), MIN(cnt), MAX(cnt)
        FROM (
            SELECT COUNT(*) AS cnt FROM messages GROUP BY conversation_id
        )
        """
    )
    mean_cnt, min_cnt, max_cnt = cur.fetchone()
    return {
        "total_messages": total_messages,
        "total_conversations": total_conversations,
        "date_range": (min_date, max_date),
        "messages_per_conversation": {
            "mean": float(mean_cnt) if mean_cnt is not None else 0.0,
            "min": int(min_cnt) if min_cnt is not None else 0,
            "max": int(max_cnt) if max_cnt is not None else 0,
        },
    }


def get_messages(
    con: sqlite3.Connection,
    conversation_id: int,
    limit: int = 200000,
    offset: int = 0
) -> List[Tuple[int, str, str, str, Optional[str]]]:
    cur = con.cursor()
    cur.execute(
        """
        SELECT id, role, created_at, content, meta_json
        FROM messages
        WHERE conversation_id=?
        ORDER BY id ASC
        LIMIT ? OFFSET ?
        """,
        (conversation_id, limit, offset)
    )
    return cur.fetchall()


def search_messages(
    con: sqlite3.Connection,
    query: str,
    project_id: Optional[int] = None,
    limit: int = 30
) -> List[Tuple[int, int, str, str, str]]:
    """
    Returns: (message_id, conversation_id, conversation_title, role, snippet)
    """
    cur = con.cursor()

    def run_fts(q: str) -> List[Tuple[int, int, str, str, str]]:
        if project_id is None:
            cur.execute(
                """
                SELECT m.id, m.conversation_id, COALESCE(c.title,''), m.role,
                       snippet(messages_fts, 0, '[', ']', '…', 12)
                FROM messages_fts
                JOIN messages m ON m.id = messages_fts.rowid
                JOIN conversations c ON c.id = m.conversation_id
                WHERE messages_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (q, limit)
            )
        else:
            cur.execute(
                """
                SELECT m.id, m.conversation_id, COALESCE(c.title,''), m.role,
                       snippet(messages_fts, 0, '[', ']', '…', 12)
                FROM messages_fts
                JOIN messages m ON m.id = messages_fts.rowid
                JOIN conversations c ON c.id = m.conversation_id
                WHERE m.conversation_id IN (
                    SELECT conversation_id FROM project_conversations WHERE project_id = ?
                )
                AND messages_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (int(project_id), q, limit)
            )
        return cur.fetchall()

    def run_like(tokens: List[str]) -> List[Tuple[int, int, str, str, str]]:
        if not tokens:
            return []
        clauses = " AND ".join(["m.content LIKE ?" for _ in tokens])
        params = [f"%{t}%" for t in tokens]

        if project_id is None:
            cur.execute(
                f"""
                SELECT m.id, m.conversation_id, COALESCE(c.title,''), m.role,
                       substr(m.content, 1, 200) as snippet
                FROM messages m
                JOIN conversations c ON c.id = m.conversation_id
                WHERE {clauses}
                ORDER BY m.id DESC
                LIMIT ?
                """,
                (*params, limit)
            )
        else:
            cur.execute(
                f"""
                SELECT m.id, m.conversation_id, COALESCE(c.title,''), m.role,
                       substr(m.content, 1, 200) as snippet
                FROM messages m
                JOIN conversations c ON c.id = m.conversation_id
                WHERE m.conversation_id IN (
                    SELECT conversation_id FROM project_conversations WHERE project_id = ?
                )
                AND {clauses}
                ORDER BY m.id DESC
                LIMIT ?
                """,
                (int(project_id), *params, limit)
            )
        return cur.fetchall()

    # First try FTS; if it errors or returns nothing, fall back to LIKE with tokenized terms.
    try:
        rows = run_fts(query)
        if rows:
            return rows
    except sqlite3.OperationalError:
        rows = []

    tokens = re.findall(r"[\w]+", query)[:5]
    if not tokens and query.strip():
        tokens = [query.strip()]
    return run_like(tokens)

def get_project_system_prompt(con: sqlite3.Connection, project_id: int) -> str:
    cur = con.cursor()
    cur.execute("SELECT system_prompt FROM projects WHERE id=?", (project_id,))
    row = cur.fetchone()
    return row[0] or "" if row else ""


def set_project_system_prompt(con: sqlite3.Connection, project_id: int, prompt: str) -> None:
    cur = con.cursor()
    cur.execute(
        "UPDATE projects SET system_prompt=? WHERE id=?",
        (prompt, project_id)
    )
    con.commit()

def get_project_model(con: sqlite3.Connection, project_id: int) -> str:
    cur = con.cursor()
    cur.execute("SELECT preferred_model FROM projects WHERE id=?", (project_id,))
    row = cur.fetchone()
    return row[0] or "" if row else ""


def set_project_model(con: sqlite3.Connection, project_id: int, model: str) -> None:
    cur = con.cursor()
    cur.execute(
        "UPDATE projects SET preferred_model=? WHERE id=?",
        (model, project_id)
    )
    con.commit()


def list_project_notes(con: sqlite3.Connection, project_id: int, limit: int = 200) -> List[Tuple[int, str, str, str, str]]:
    cur = con.cursor()
    cur.execute(
        """
        SELECT id, title, content, created_at, updated_at
        FROM project_notes
        WHERE project_id=?
        ORDER BY updated_at DESC
        LIMIT ?
        """,
        (project_id, max(1, limit)),
    )
    return cur.fetchall()


def save_project_note(
    con: sqlite3.Connection,
    project_id: int,
    title: str,
    content: str,
    note_id: Optional[int] = None,
) -> int:
    title = (title or "").strip()
    if not title:
        raise ValueError("title is required")
    content = content or ""

    cur = con.cursor()
    now = utc_now_iso()
    if note_id is None:
        cur.execute(
            """
            INSERT INTO project_notes(project_id, title, content, created_at, updated_at)
            VALUES (?,?,?,?,?)
            """,
            (project_id, title, content, now, now),
        )
        con.commit()
        if cur.lastrowid is None:
            raise RuntimeError("Failed to get last row id for project note")
        return int(cur.lastrowid)

    cur.execute(
        """
        UPDATE project_notes
        SET title=?, content=?, updated_at=?
        WHERE id=? AND project_id=?
        """,
        (title, content, now, note_id, project_id),
    )
    con.commit()
    return int(note_id)


def delete_project_note(con: sqlite3.Connection, project_id: int, note_id: int) -> None:
    cur = con.cursor()
    cur.execute("DELETE FROM project_notes WHERE id=? AND project_id=?", (note_id, project_id))
    con.commit()


def list_workflows(con: sqlite3.Connection, limit: int = 200) -> List[Tuple[int, str, str, str, int, str, str, str, str]]:
    cur = con.cursor()
    cur.execute(
        """
        SELECT id, name, description, cron, enabled, payload_json, last_run, next_run, updated_at
        FROM workflows
        ORDER BY updated_at DESC
        LIMIT ?
        """,
        (max(1, limit),),
    )
    return cur.fetchall()


def create_workflow(
    con: sqlite3.Connection,
    name: str,
    description: str | None,
    cron: str | None,
    enabled: bool,
    payload: dict | None,
) -> int:
    nm = (name or "").strip()
    if not nm:
        raise ValueError("name is required")
    now = utc_now_iso()
    cur = con.cursor()
    cur.execute(
        """
        INSERT INTO workflows(name, description, cron, enabled, payload_json, last_run, next_run, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?, ?, ?)
        """,
        (
            nm,
            (description or "").strip(),
            (cron or "").strip(),
            1 if enabled else 0,
            json.dumps(payload or {}),
            None,
            None,
            now,
            now,
        ),
    )
    con.commit()
    if cur.lastrowid is None:
        raise RuntimeError("Failed to get last row id for workflow")
    return int(cur.lastrowid)


def delete_workflow(con: sqlite3.Connection, workflow_id: int) -> None:
    cur = con.cursor()
    cur.execute("DELETE FROM workflows WHERE id=?", (workflow_id,))
    con.commit()


def get_workflow(con: sqlite3.Connection, workflow_id: int) -> Tuple[int, str, str, str, int, str, str, str, str] | None:
    cur = con.cursor()
    cur.execute(
        """
        SELECT id, name, description, cron, enabled, payload_json, last_run, next_run, updated_at
        FROM workflows
        WHERE id=?
        """,
        (workflow_id,),
    )
    row = cur.fetchone()
    return row


def record_workflow_run(con: sqlite3.Connection, workflow_id: int, next_run: str | None = None) -> None:
    cur = con.cursor()
    now = utc_now_iso()
    cur.execute(
        """
        UPDATE workflows
        SET last_run=?, next_run=?, updated_at=?
        WHERE id=?
        """,
        (now, next_run, now, workflow_id),
    )
    con.commit()


def delete_conversation(con: sqlite3.Connection, conversation_id: int) -> None:
    """Delete a conversation and cascaded messages/project links."""
    cur = con.cursor()
    try:
        cur.execute(
            "DELETE FROM messages_fts WHERE rowid IN (SELECT id FROM messages WHERE conversation_id=?)",
            (conversation_id,)
        )
        cur.execute("DELETE FROM messages WHERE conversation_id=?", (conversation_id,))
        cur.execute("DELETE FROM project_conversations WHERE conversation_id=?", (conversation_id,))
        cur.execute("DELETE FROM conversations WHERE id=?", (conversation_id,))
        con.commit()
    except sqlite3.OperationalError:
        con.rollback()
        raise
