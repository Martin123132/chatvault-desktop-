from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

try:
    from .chatvault_db import add_message, add_tag, create_conversation, search_messages
    from .llm_backends import generate_response
except Exception:  # pragma: no cover
    from chatvault_db import add_message, add_tag, create_conversation, search_messages
    from llm_backends import generate_response


GAME_LABELS = {
    "tictactoe": "Tic-tac-toe",
    "connect4": "Connect 4",
    "checkers": "Checkers",
}
GAME_IDS = set(GAME_LABELS)
MODES = {"user_vs_ai", "ai_vs_ai", "replay"}
BACKENDS = {"openai", "anthropic", "ollama"}


class ArcadeError(ValueError):
    pass


@dataclass
class MoveResult:
    state: dict[str, Any]
    move: dict[str, Any]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except Exception:
        return fallback


def _dumps(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def _validate_game(game_id: str) -> str:
    game = (game_id or "").strip().lower()
    if game not in GAME_IDS:
        raise ArcadeError("Unknown arcade game.")
    return game


def _validate_mode(mode: str) -> str:
    value = (mode or "user_vs_ai").strip().lower()
    if value not in MODES:
        raise ArcadeError("Unknown arcade mode.")
    return value


def _opponent(player: str) -> str:
    return "p2" if player == "p1" else "p1"


def initial_game_state(game_id: str) -> dict[str, Any]:
    game = _validate_game(game_id)
    if game == "tictactoe":
        return {
            "game_id": game,
            "board": [""] * 9,
            "current_player": "p1",
            "status": "active",
            "winner": None,
            "turn_index": 0,
        }
    if game == "connect4":
        return {
            "game_id": game,
            "board": [[""] * 7 for _ in range(6)],
            "current_player": "p1",
            "status": "active",
            "winner": None,
            "turn_index": 0,
        }

    board = _new_checkers_board()
    return _checkers_state(board, turn_index=0)


def legal_moves_for_state(game_id: str, state: dict[str, Any]) -> list[dict[str, Any]]:
    game = _validate_game(game_id)
    if (state or {}).get("status") != "active":
        return []
    if game == "tictactoe":
        return [{"cell": i} for i, value in enumerate(state.get("board") or []) if value == ""]
    if game == "connect4":
        board = state.get("board") or []
        if len(board) != 6:
            return []
        return [{"column": col} for col in range(7) if board[0][col] == ""]

    board = _checkers_board_from_state(state)
    return [{"move": str(move)} for move in board.legal_moves]


def apply_game_move(game_id: str, state: dict[str, Any], move: dict[str, Any]) -> MoveResult:
    game = _validate_game(game_id)
    if (state or {}).get("status") != "active":
        raise ArcadeError("This game is already complete.")
    if game == "tictactoe":
        return _apply_tictactoe(state, move)
    if game == "connect4":
        return _apply_connect4(state, move)
    return _apply_checkers(state, move)


def _apply_tictactoe(state: dict[str, Any], move: dict[str, Any]) -> MoveResult:
    board = list(state.get("board") or [""] * 9)
    try:
        cell = int(move.get("cell"))
    except Exception as exc:
        raise ArcadeError("Tic-tac-toe moves require a cell number.") from exc
    if cell < 0 or cell >= 9:
        raise ArcadeError("Tic-tac-toe cell must be between 0 and 8.")
    if board[cell] != "":
        raise ArcadeError("That square is already occupied.")

    player = state.get("current_player") or "p1"
    board[cell] = player
    winner = _ttt_winner(board)
    status = "complete" if winner or all(board) else "active"
    next_player = player if status == "complete" else _opponent(player)
    new_state = {
        **state,
        "board": board,
        "current_player": next_player,
        "status": status,
        "winner": winner or ("draw" if status == "complete" else None),
        "turn_index": int(state.get("turn_index") or 0) + 1,
    }
    return MoveResult(new_state, {"cell": cell})


def _ttt_winner(board: list[str]) -> str | None:
    lines = (
        (0, 1, 2),
        (3, 4, 5),
        (6, 7, 8),
        (0, 3, 6),
        (1, 4, 7),
        (2, 5, 8),
        (0, 4, 8),
        (2, 4, 6),
    )
    for a, b, c in lines:
        if board[a] and board[a] == board[b] == board[c]:
            return board[a]
    return None


def _apply_connect4(state: dict[str, Any], move: dict[str, Any]) -> MoveResult:
    board = [list(row) for row in (state.get("board") or [])]
    if len(board) != 6 or any(len(row) != 7 for row in board):
        raise ArcadeError("Connect 4 board is malformed.")
    try:
        column = int(move.get("column"))
    except Exception as exc:
        raise ArcadeError("Connect 4 moves require a column number.") from exc
    if column < 0 or column >= 7:
        raise ArcadeError("Connect 4 column must be between 0 and 6.")
    if board[0][column] != "":
        raise ArcadeError("That column is full.")

    player = state.get("current_player") or "p1"
    row_played = None
    for row in range(5, -1, -1):
        if board[row][column] == "":
            board[row][column] = player
            row_played = row
            break
    if row_played is None:
        raise ArcadeError("That column is full.")

    winner = _connect4_winner(board, row_played, column, player)
    status = "complete" if winner or all(board[0]) else "active"
    next_player = player if status == "complete" else _opponent(player)
    new_state = {
        **state,
        "board": board,
        "current_player": next_player,
        "status": status,
        "winner": winner or ("draw" if status == "complete" else None),
        "turn_index": int(state.get("turn_index") or 0) + 1,
    }
    return MoveResult(new_state, {"column": column})


def _connect4_winner(board: list[list[str]], row: int, col: int, player: str) -> str | None:
    directions = ((1, 0), (0, 1), (1, 1), (1, -1))
    for dr, dc in directions:
        count = 1
        for sign in (1, -1):
            rr = row + dr * sign
            cc = col + dc * sign
            while 0 <= rr < 6 and 0 <= cc < 7 and board[rr][cc] == player:
                count += 1
                rr += dr * sign
                cc += dc * sign
        if count >= 4:
            return player
    return None


def _new_checkers_board() -> Any:
    import draughts

    return draughts.AmericanBoard()


def _checkers_board_from_state(state: dict[str, Any]) -> Any:
    import draughts

    fen = (state or {}).get("fen")
    if not fen:
        return draughts.AmericanBoard()
    return draughts.AmericanBoard.from_fen(fen)


def _checkers_player_from_turn(turn: Any) -> str:
    return "p1" if str(turn).endswith("WHITE") else "p2"


def _checkers_state(board: Any, turn_index: int) -> dict[str, Any]:
    winner = None
    status = "active"
    if bool(getattr(board, "is_draw", False)):
        winner = "draw"
        status = "complete"
    elif bool(getattr(board, "game_over", False)) or not list(board.legal_moves):
        winner = _opponent(_checkers_player_from_turn(board.turn))
        status = "complete"
    return {
        "game_id": "checkers",
        "fen": board.fen,
        "board": [int(v) for v in board.position.tolist()],
        "current_player": _checkers_player_from_turn(board.turn),
        "status": status,
        "winner": winner,
        "turn_index": int(turn_index),
    }


def _apply_checkers(state: dict[str, Any], move: dict[str, Any]) -> MoveResult:
    board = _checkers_board_from_state(state)
    requested = str(move.get("move") or "").strip()
    legal = {str(candidate): candidate for candidate in board.legal_moves}
    if requested not in legal:
        raise ArcadeError("Illegal checkers move.")
    board.push(legal[requested])
    new_state = _checkers_state(board, turn_index=int(state.get("turn_index") or 0) + 1)
    return MoveResult(new_state, {"move": requested})


def create_arcade_session(
    con: Any,
    *,
    game_id: str,
    mode: str,
    p1_type: str,
    p1_backend: str | None,
    p1_label: str | None,
    p2_type: str,
    p2_backend: str | None,
    p2_label: str | None,
    project_id: int | None = None,
    memory_boost: bool = False,
) -> dict[str, Any]:
    game = _validate_game(game_id)
    session_mode = _validate_mode(mode)
    state = initial_game_state(game)
    now = _now_iso()
    title = f"{GAME_LABELS[game]}: {(p1_label or 'Player 1').strip()} vs {(p2_label or 'Player 2').strip()}"
    cur = con.cursor()
    cur.execute(
        """
        INSERT INTO arcade_sessions(
            game_id, mode, title, p1_type, p1_backend, p1_label,
            p2_type, p2_backend, p2_label, project_id, memory_boost,
            state_json, status, winner, invalid_attempts, started_at, updated_at
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            game,
            session_mode,
            title,
            p1_type,
            p1_backend,
            p1_label or "Player 1",
            p2_type,
            p2_backend,
            p2_label or "Player 2",
            project_id,
            1 if memory_boost else 0,
            _dumps(state),
            "active",
            None,
            0,
            now,
            now,
        ),
    )
    con.commit()
    return get_arcade_session(con, int(cur.lastrowid))


def get_arcade_session(con: Any, session_id: int) -> dict[str, Any]:
    cur = con.cursor()
    cur.execute(
        """
        SELECT id, game_id, mode, title, p1_type, p1_backend, p1_label,
               p2_type, p2_backend, p2_label, project_id, memory_boost,
               state_json, status, winner, invalid_attempts, conversation_id,
               started_at, updated_at, completed_at
        FROM arcade_sessions
        WHERE id=?
        """,
        (int(session_id),),
    )
    row = cur.fetchone()
    if not row:
        raise ArcadeError("Arcade session not found.")
    session = _session_from_row(row)
    session["moves"] = list_arcade_moves(con, int(session_id))
    session["legal_moves"] = legal_moves_for_state(session["game_id"], session["state"])
    return session


def _session_from_row(row: Any) -> dict[str, Any]:
    state = _loads(row[12], {})
    return {
        "id": int(row[0]),
        "game_id": row[1],
        "game_label": GAME_LABELS.get(row[1], row[1]),
        "mode": row[2],
        "title": row[3],
        "players": {
            "p1": {"type": row[4], "backend": row[5], "label": row[6]},
            "p2": {"type": row[7], "backend": row[8], "label": row[9]},
        },
        "project_id": row[10],
        "memory_boost": bool(row[11]),
        "state": state,
        "status": row[13],
        "winner": row[14],
        "invalid_attempts": int(row[15] or 0),
        "conversation_id": row[16],
        "started_at": row[17],
        "updated_at": row[18],
        "completed_at": row[19],
    }


def list_arcade_moves(con: Any, session_id: int) -> list[dict[str, Any]]:
    cur = con.cursor()
    cur.execute(
        """
        SELECT id, move_number, player, actor_type, backend, move_json,
               board_before_json, board_after_json, legal_moves_json,
               explanation, invalid_attempts, elapsed_ms, created_at
        FROM arcade_moves
        WHERE session_id=?
        ORDER BY move_number ASC
        """,
        (int(session_id),),
    )
    moves = []
    for row in cur.fetchall():
        moves.append(
            {
                "id": int(row[0]),
                "move_number": int(row[1]),
                "player": row[2],
                "actor_type": row[3],
                "backend": row[4],
                "move": _loads(row[5], {}),
                "board_before": _loads(row[6], {}),
                "board_after": _loads(row[7], {}),
                "legal_moves": _loads(row[8], []),
                "explanation": row[9] or "",
                "invalid_attempts": int(row[10] or 0),
                "elapsed_ms": int(row[11] or 0),
                "created_at": row[12],
            }
        )
    return moves


def list_arcade_sessions(con: Any, limit: int = 20) -> list[dict[str, Any]]:
    cur = con.cursor()
    cur.execute(
        """
        SELECT id, game_id, mode, title, p1_type, p1_backend, p1_label,
               p2_type, p2_backend, p2_label, project_id, memory_boost,
               state_json, status, winner, invalid_attempts, conversation_id,
               started_at, updated_at, completed_at
        FROM arcade_sessions
        ORDER BY updated_at DESC
        LIMIT ?
        """,
        (max(1, int(limit or 20)),),
    )
    return [_session_from_row(row) for row in cur.fetchall()]


def arcade_scoreboard(con: Any) -> dict[str, Any]:
    cur = con.cursor()
    cur.execute(
        """
        SELECT game_id, status, COALESCE(winner, ''), p1_backend, p2_backend, COUNT(*)
        FROM arcade_sessions
        GROUP BY game_id, status, COALESCE(winner, ''), p1_backend, p2_backend
        ORDER BY game_id
        """
    )
    rows = cur.fetchall()
    cur.execute(
        """
        SELECT id, game_id, title, status, COALESCE(winner,''), updated_at
        FROM arcade_sessions
        ORDER BY updated_at DESC
        LIMIT 8
        """
    )
    recent = [
        {
            "id": int(r[0]),
            "game_id": r[1],
            "title": r[2],
            "status": r[3],
            "winner": r[4],
            "updated_at": r[5],
        }
        for r in cur.fetchall()
    ]
    return {
        "rows": [
            {
                "game_id": r[0],
                "status": r[1],
                "winner": r[2],
                "p1_backend": r[3],
                "p2_backend": r[4],
                "count": int(r[5]),
            }
            for r in rows
        ],
        "recent": recent,
    }


def submit_arcade_move(
    con: Any,
    session_id: int,
    move: dict[str, Any],
    *,
    actor_type: str = "user",
    backend: str | None = None,
    explanation: str = "",
    invalid_attempts: int = 0,
    elapsed_ms: int = 0,
) -> dict[str, Any]:
    session = get_arcade_session(con, session_id)
    if session["status"] != "active":
        return session

    state_before = session["state"]
    player = state_before.get("current_player") or "p1"
    legal = legal_moves_for_state(session["game_id"], state_before)
    result = apply_game_move(session["game_id"], state_before, move)
    move_number = len(session["moves"]) + 1
    now = _now_iso()
    status = result.state.get("status") or "active"
    winner = result.state.get("winner")
    completed_at = now if status == "complete" else None
    cur = con.cursor()
    cur.execute(
        """
        INSERT INTO arcade_moves(
            session_id, move_number, player, actor_type, backend, move_json,
            board_before_json, board_after_json, legal_moves_json, explanation,
            invalid_attempts, elapsed_ms, created_at
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            int(session_id),
            move_number,
            player,
            actor_type,
            backend,
            _dumps(result.move),
            _dumps(state_before),
            _dumps(result.state),
            _dumps(legal),
            explanation,
            int(invalid_attempts or 0),
            int(elapsed_ms or 0),
            now,
        ),
    )
    cur.execute(
        """
        UPDATE arcade_sessions
        SET state_json=?, status=?, winner=?, invalid_attempts=invalid_attempts+?,
            updated_at=?, completed_at=COALESCE(completed_at, ?)
        WHERE id=?
        """,
        (
            _dumps(result.state),
            status,
            winner,
            int(invalid_attempts or 0),
            now,
            completed_at,
            int(session_id),
        ),
    )
    con.commit()
    updated = get_arcade_session(con, session_id)
    if updated["status"] == "complete" and not updated.get("conversation_id"):
        _save_completed_game(con, updated)
        updated = get_arcade_session(con, session_id)
    return updated


def play_arcade_ai_turn(con: Any, session_id: int, backend_override: str | None = None) -> dict[str, Any]:
    session = get_arcade_session(con, session_id)
    if session["status"] != "active":
        return session

    player_key = session["state"].get("current_player") or "p1"
    player = session["players"][player_key]
    if player["type"] != "ai":
        raise ArcadeError("It is not an AI player's turn.")
    backend = (backend_override or player.get("backend") or "").strip().lower()
    if backend not in BACKENDS:
        raise ArcadeError("AI player needs a backend: openai, anthropic, or ollama.")

    legal = legal_moves_for_state(session["game_id"], session["state"])
    if not legal:
        return session

    started = time.perf_counter()
    invalid_attempts = 0
    explanation = ""
    chosen: dict[str, Any] | None = None
    system_prompt, messages = _ai_messages(con, session, legal, player_key)
    for attempt in range(2):
        try:
            raw = generate_response(
                messages=messages,
                system_prompt=system_prompt,
                backend=backend,
                temperature=0.15,
                max_tokens=260,
            )
        except Exception as exc:
            invalid_attempts += 1
            explanation = f"{backend} unavailable or invalid response: {exc}"
            break
        try:
            parsed = _extract_ai_move(raw)
            apply_game_move(session["game_id"], session["state"], parsed.get("move") or {})
            chosen = parsed.get("move") or {}
            explanation = str(parsed.get("explanation") or raw).strip()[:1200]
            break
        except Exception as exc:
            invalid_attempts += 1
            explanation = f"{backend} returned an invalid move: {exc}"
            if attempt == 0:
                messages.append({"role": "assistant", "content": raw})
                messages.append(
                    {
                        "role": "user",
                        "content": f"That move was invalid: {exc}. Return one legal JSON move from this list only: {json.dumps(legal)}",
                    }
                )

    if chosen is None:
        chosen = legal[0]
        explanation = (explanation + " " if explanation else "") + "Fallback used the first legal move."

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return submit_arcade_move(
        con,
        session_id,
        chosen,
        actor_type="ai",
        backend=backend,
        explanation=explanation,
        invalid_attempts=invalid_attempts,
        elapsed_ms=elapsed_ms,
    )


def _extract_ai_move(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).strip()
        text = re.sub(r"```$", "", text).strip()
    try:
        data = json.loads(text)
    except Exception:
        match = re.search(r"\{.*\}", text, flags=re.S)
        if not match:
            raise ArcadeError("AI response did not include JSON.")
        data = json.loads(match.group(0))
    if not isinstance(data, dict) or not isinstance(data.get("move"), dict):
        raise ArcadeError("AI response must be JSON with a move object.")
    return data


def _ai_messages(con: Any, session: dict[str, Any], legal: list[dict[str, Any]], player_key: str) -> tuple[str, list[dict[str, str]]]:
    memory = _memory_snippets(con, session)
    memory_text = ""
    if memory:
        memory_text = "\n\nOptional vault flavor for explanation only:\n" + "\n".join(
            f"- {item['conversation_title']}: {item['snippet']}" for item in memory[:3]
        )
    system = (
        "You are playing a validated board game inside ChatVault Memory Arcade. "
        "Choose exactly one legal move. Return only JSON shaped like "
        '{"move": {...}, "explanation": "short reason"}. '
        "Do not invent moves outside the legal_moves list."
    )
    user = (
        f"Game: {session['game_id']}\n"
        f"You are: {player_key} ({session['players'][player_key]['label']})\n"
        f"Current state JSON:\n{json.dumps(session['state'], ensure_ascii=False)}\n\n"
        f"Legal moves JSON:\n{json.dumps(legal, ensure_ascii=False)}"
        f"{memory_text}"
    )
    return system, [{"role": "user", "content": user}]


def _memory_snippets(con: Any, session: dict[str, Any]) -> list[dict[str, Any]]:
    if not session.get("memory_boost") or not session.get("project_id"):
        return []
    try:
        rows = search_messages(
            con=con,
            query="strategy OR decision OR reasoning",
            project_id=int(session["project_id"]),
            limit=3,
        )
    except Exception:
        return []
    return [
        {
            "message_id": int(row[0]),
            "conversation_id": int(row[1]),
            "conversation_title": row[2],
            "role": row[3],
            "snippet": row[4],
        }
        for row in rows
    ]


def _save_completed_game(con: Any, session: dict[str, Any]) -> None:
    winner = session.get("winner") or "unknown"
    player_label = session["players"].get(winner, {}).get("label") if winner in {"p1", "p2"} else winner
    title = f"Arcade: {session['game_label']} #{session['id']}"
    conv_id = create_conversation(
        con,
        source="arcade",
        title=title,
        external_id=f"arcade:{session['id']}",
        created_at=session.get("started_at"),
        provider="arcade",
    )
    summary = [
        f"Game: {session['game_label']}",
        f"Mode: {session['mode']}",
        f"Players: {session['players']['p1']['label']} vs {session['players']['p2']['label']}",
        f"Result: {player_label}",
    ]
    summary_id = add_message(
        con,
        conv_id,
        source="arcade",
        role="system",
        content="\n".join(summary),
        meta={"arcade_session_id": session["id"], "stage": "summary"},
    )
    tags = _arcade_tags(session)
    for tag in tags:
        add_tag(con, summary_id, tag)

    for move in session.get("moves", []):
        player = session["players"][move["player"]]["label"]
        content = f"Move {move['move_number']}: {player} played {json.dumps(move['move'])}"
        if move.get("explanation"):
            content += f"\nReason: {move['explanation']}"
        mid = add_message(
            con,
            conv_id,
            source="arcade",
            role="assistant",
            content=content,
            meta={"arcade_session_id": session["id"], "stage": "move", "move_number": move["move_number"]},
        )
        for tag in tags:
            add_tag(con, mid, tag)

    cur = con.cursor()
    cur.execute("UPDATE arcade_sessions SET conversation_id=? WHERE id=?", (conv_id, int(session["id"])))
    con.commit()


def _arcade_tags(session: dict[str, Any]) -> list[str]:
    tags = ["arcade", session["game_id"]]
    for player in session.get("players", {}).values():
        backend = player.get("backend")
        if backend:
            tags.append(str(backend))
    out = []
    for tag in tags:
        if tag not in out:
            out.append(tag)
    return out
