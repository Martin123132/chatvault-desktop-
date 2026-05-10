from fastapi.testclient import TestClient

from src import arcade
from src.app import make_app
from src.chatvault_db import connect


def test_tictactoe_rules_win():
    state = arcade.initial_game_state("tictactoe")
    for move in ({"cell": 0}, {"cell": 3}, {"cell": 1}, {"cell": 4}, {"cell": 2}):
        state = arcade.apply_game_move("tictactoe", state, move).state
    assert state["status"] == "complete"
    assert state["winner"] == "p1"


def test_connect4_rules_win():
    state = arcade.initial_game_state("connect4")
    for move in ({"column": 0}, {"column": 1}, {"column": 0}, {"column": 1}, {"column": 0}, {"column": 1}, {"column": 0}):
        state = arcade.apply_game_move("connect4", state, move).state
    assert state["status"] == "complete"
    assert state["winner"] == "p1"


def test_checkers_legal_and_invalid_move():
    state = arcade.initial_game_state("checkers")
    legal = arcade.legal_moves_for_state("checkers", state)
    assert {"move": "21-17"} in legal
    next_state = arcade.apply_game_move("checkers", state, {"move": "21-17"}).state
    assert next_state["current_player"] == "p2"
    try:
        arcade.apply_game_move("checkers", state, {"move": "1-5"})
    except arcade.ArcadeError:
        pass
    else:
        raise AssertionError("illegal checkers move should fail")


def test_arcade_api_ai_turn_with_mocked_model(tmp_path, monkeypatch):
    app = make_app(str(tmp_path / "arcade.sqlite3"))
    client = TestClient(app)

    monkeypatch.setattr(
        arcade,
        "generate_response",
        lambda **_: '{"move":{"cell":4},"explanation":"Take the center."}',
    )

    created = client.post(
        "/api/arcade/sessions",
        json={
            "game_id": "tictactoe",
            "mode": "user_vs_ai",
            "p1_type": "user",
            "p1_label": "You",
            "p2_type": "ai",
            "p2_backend": "openai",
            "p2_label": "OpenAI",
        },
    )
    assert created.status_code == 200
    sid = created.json()["id"]
    moved = client.post(f"/api/arcade/sessions/{sid}/move", json={"move": {"cell": 0}})
    assert moved.status_code == 200
    ai = client.post(f"/api/arcade/sessions/{sid}/ai-turn", json={})
    assert ai.status_code == 200
    body = ai.json()
    assert body["state"]["board"][4] == "p2"
    assert body["moves"][-1]["explanation"] == "Take the center."


def test_arcade_ai_retries_invalid_output(tmp_path, monkeypatch):
    app = make_app(str(tmp_path / "arcade.sqlite3"))
    client = TestClient(app)
    responses = iter(["not json", '{"move":{"cell":4},"explanation":"Recovered."}'])

    monkeypatch.setattr(arcade, "generate_response", lambda **_: next(responses))

    created = client.post(
        "/api/arcade/sessions",
        json={
            "game_id": "tictactoe",
            "mode": "user_vs_ai",
            "p1_type": "user",
            "p1_label": "You",
            "p2_type": "ai",
            "p2_backend": "openai",
            "p2_label": "OpenAI",
        },
    )
    sid = created.json()["id"]
    client.post(f"/api/arcade/sessions/{sid}/move", json={"move": {"cell": 0}})
    ai = client.post(f"/api/arcade/sessions/{sid}/ai-turn", json={})

    assert ai.status_code == 200
    body = ai.json()
    assert body["state"]["board"][4] == "p2"
    assert body["moves"][-1]["invalid_attempts"] == 1


def test_arcade_ai_backend_failure_falls_back(tmp_path, monkeypatch):
    app = make_app(str(tmp_path / "arcade.sqlite3"))
    client = TestClient(app)

    def unavailable(**_):
        raise RuntimeError("backend offline")

    monkeypatch.setattr(arcade, "generate_response", unavailable)

    created = client.post(
        "/api/arcade/sessions",
        json={
            "game_id": "tictactoe",
            "mode": "user_vs_ai",
            "p1_type": "user",
            "p1_label": "You",
            "p2_type": "ai",
            "p2_backend": "openai",
            "p2_label": "OpenAI",
        },
    )
    sid = created.json()["id"]
    client.post(f"/api/arcade/sessions/{sid}/move", json={"move": {"cell": 0}})
    ai = client.post(f"/api/arcade/sessions/{sid}/ai-turn", json={})

    assert ai.status_code == 200
    body = ai.json()
    assert body["state"]["board"][1] == "p2"
    assert body["moves"][-1]["invalid_attempts"] == 1
    assert "Fallback used" in body["moves"][-1]["explanation"]


def test_completed_game_saves_searchable_conversation(tmp_path):
    db = tmp_path / "arcade.sqlite3"
    con = connect(str(db))
    session = arcade.create_arcade_session(
        con,
        game_id="tictactoe",
        mode="user_vs_ai",
        p1_type="user",
        p1_backend=None,
        p1_label="You",
        p2_type="user",
        p2_backend=None,
        p2_label="Friend",
    )
    for move in ({"cell": 0}, {"cell": 3}, {"cell": 1}, {"cell": 4}, {"cell": 2}):
        session = arcade.submit_arcade_move(con, session["id"], move)
    assert session["status"] == "complete"
    assert session["conversation_id"]
    cur = con.cursor()
    cur.execute("SELECT COUNT(*) FROM conversations WHERE source='arcade'")
    assert cur.fetchone()[0] == 1
    cur.execute("SELECT COUNT(*) FROM message_tags WHERE tag='arcade'")
    assert cur.fetchone()[0] >= 1
    con.close()
