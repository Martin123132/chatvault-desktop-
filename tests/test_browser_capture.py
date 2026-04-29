from fastapi.testclient import TestClient

from src.app import make_app
from src.chatvault_db import connect


def test_browser_capture_ingests_messages(tmp_path):
    db = tmp_path / 'test.sqlite3'
    app = make_app(str(db))
    client = TestClient(app)

    payload = {
        'provider': 'chatgpt',
        'page_url': 'https://chatgpt.com/c/abc',
        'conversation_title': 'My test chat',
        'captured_at': '2026-04-29T00:00:00Z',
        'messages': [
            {'role': 'user', 'content': 'hello'},
            {'role': 'assistant', 'content': 'hi there'}
        ],
        'project': 'Capture Project',
        'tags': ['capture', 'chatgpt']
    }
    r = client.post('/api/browser-capture', json=payload)
    assert r.status_code == 200
    body = r.json()
    assert body['ok'] is True
    assert body['messages_imported'] == 2

    con = connect(str(db))
    cur = con.cursor()
    cur.execute('SELECT COUNT(*) FROM messages')
    assert cur.fetchone()[0] == 2
    cur.execute('SELECT COUNT(*) FROM message_tags')
    assert cur.fetchone()[0] == 4


def test_browser_capture_requires_messages(tmp_path):
    app = make_app(str(tmp_path / 'test.sqlite3'))
    client = TestClient(app)
    r = client.post('/api/browser-capture', json={
        'provider': 'chatgpt',
        'page_url': 'https://chatgpt.com',
        'conversation_title': 'x',
        'captured_at': '2026-04-29T00:00:00Z',
        'messages': []
    })
    assert r.status_code == 400
