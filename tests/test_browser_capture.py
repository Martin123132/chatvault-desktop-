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


def test_live_browser_capture_updates_existing_thread(tmp_path):
    db = tmp_path / 'test.sqlite3'
    app = make_app(str(db))
    client = TestClient(app)
    base_payload = {
        'provider': 'claude',
        'page_url': 'https://claude.ai/chat/abc',
        'conversation_title': 'Live Claude chat',
        'captured_at': '2026-04-29T00:00:00Z',
        'external_id': 'browser_capture:claude:https://claude.ai/chat/abc',
        'capture_mode': 'live',
        'replace_existing': True,
        'messages': [
            {'role': 'user', 'content': 'first question'},
            {'role': 'assistant', 'content': 'first answer'},
        ],
    }
    first = client.post('/api/browser-capture', json=base_payload)
    assert first.status_code == 200
    first_body = first.json()
    assert first_body['updated_existing'] is False

    second_payload = dict(base_payload)
    second_payload['messages'] = [
        {'role': 'user', 'content': 'updated question'},
        {'role': 'assistant', 'content': 'updated answer'},
        {'role': 'user', 'content': 'follow up'},
    ]
    second = client.post('/api/browser-capture', json=second_payload)
    assert second.status_code == 200
    second_body = second.json()
    assert second_body['conversation_id'] == first_body['conversation_id']
    assert second_body['messages_imported'] == 3
    assert second_body['updated_existing'] is True

    con = connect(str(db))
    cur = con.cursor()
    cur.execute('SELECT COUNT(*) FROM conversations')
    assert cur.fetchone()[0] == 1
    cur.execute('SELECT COUNT(*), group_concat(content, "|") FROM messages')
    count, contents = cur.fetchone()
    assert count == 3
    assert 'first question' not in contents
    assert 'updated question' in contents
