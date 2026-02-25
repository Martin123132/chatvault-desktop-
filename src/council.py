from __future__ import annotations

from typing import Dict

from chatvault_db import add_message, create_conversation
from llm_backends import generate_response


def _ask_backend(question: str, backend: str) -> str:
    return generate_response(
        messages=[{"role": "user", "content": question}],
        backend=backend,
        temperature=0.4,
        max_tokens=900,
    )


def _synthesize(openai_answer: str, claude_answer: str, ollama_answer: str, question: str) -> str:
import os
from typing import Dict

import requests
from openai import OpenAI

from chatvault_db import add_message, create_conversation

OPENAI_MODEL = os.getenv("OPENAI_COUNCIL_MODEL", os.getenv("OPENAI_MODEL_DEFAULT", "gpt-4o-mini"))
CLAUDE_MODEL = os.getenv("CLAUDE_COUNCIL_MODEL", "claude-3-5-sonnet-20241022")
OLLAMA_MODEL = os.getenv("OLLAMA_COUNCIL_MODEL", "llama3.1")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")


def _ask_openai(question: str) -> str:
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not set")
    client = OpenAI(api_key=key)
    resp = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[{"role": "user", "content": question}],
        temperature=0.4,
    )
    return (resp.choices[0].message.content or "").strip()


def _ask_claude(question: str) -> str:
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")
    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": CLAUDE_MODEL,
            "max_tokens": 700,
            "messages": [{"role": "user", "content": question}],
        },
        timeout=60,
    )
    resp.raise_for_status()
    payload = resp.json()
    blocks = payload.get("content") or []
    text = "\n".join([b.get("text", "") for b in blocks if isinstance(b, dict)])
    return text.strip()


def _ask_ollama(question: str) -> str:
    resp = requests.post(
        OLLAMA_URL,
        json={"model": OLLAMA_MODEL, "prompt": question, "stream": False},
        timeout=120,
    )
    resp.raise_for_status()
    payload = resp.json()
    return str(payload.get("response") or "").strip()


def _synthesize(openai_answer: str, claude_answer: str, ollama_answer: str, question: str) -> str:
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        return "OpenAI synthesis unavailable: OPENAI_API_KEY is not set."
    prompt = (
        "Synthesize a single, practical final answer from three model responses. "
        "Preserve key agreements, call out useful disagreements briefly, and end with concrete next steps.\n\n"
        f"Question:\n{question}\n\n"
        f"OpenAI:\n{openai_answer}\n\n"
        f"Claude:\n{claude_answer}\n\n"
        f"Ollama:\n{ollama_answer}"
    )
    return generate_response(
        messages=[{"role": "user", "content": prompt}],
        backend="openai",
        temperature=0.2,
        max_tokens=900,
    )
    client = OpenAI(api_key=key)
    resp = client.chat.completions.create(
        model=OPENAI_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
    )
    return (resp.choices[0].message.content or "").strip()


def run_council(con, question: str) -> Dict[str, str]:
    conv_id = create_conversation(
        con,
        source="council",
        title=f"Council: {question[:80]}",
        external_id=None,
        created_at=None,
        provider="multi",
    )
    add_message(con, conv_id, source="council", role="user", content=question, meta={"stage": "question"})

    answers: Dict[str, str] = {}
    for name in ("openai", "anthropic", "ollama"):
        try:
            text = _ask_backend(question, backend=name)
            answers[name if name != "anthropic" else "claude"] = text
        except Exception as exc:
            answers[name if name != "anthropic" else "claude"] = f"[{name} unavailable] {exc}"
        key = name if name != "anthropic" else "claude"
    for name, fn in (("openai", _ask_openai), ("claude", _ask_claude), ("ollama", _ask_ollama)):
        try:
            text = fn(question)
            answers[name] = text
        except Exception as exc:
            answers[name] = f"[{name} unavailable] {exc}"
        add_message(
            con,
            conv_id,
            source="council",
            role="assistant",
            content=answers[key],
            meta={"stage": "backend_answer", "backend": key},
        )

    try:
        final = _synthesize(
            answers.get("openai", ""),
            answers.get("claude", ""),
            answers.get("ollama", ""),
            question,
        )
    except Exception as exc:
        final = f"[synthesis unavailable] {exc}"

            content=answers[name],
            meta={"stage": "backend_answer", "backend": name},
        )

    final = _synthesize(
        answers.get("openai", ""),
        answers.get("claude", ""),
        answers.get("ollama", ""),
        question,
    )
    add_message(
        con,
        conv_id,
        source="council",
        role="assistant",
        content=final,
        meta={"stage": "synthesis", "backend": "openai"},
    )

    answers["synthesis"] = final
    answers["conversation_id"] = str(conv_id)
    return answers
