from __future__ import annotations

from typing import Dict

try:
    from .chatvault_db import add_message, create_conversation
    from .llm_backends import generate_response
except Exception:  # pragma: no cover
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
    for backend_name, answer_key in (("openai", "openai"), ("anthropic", "claude"), ("ollama", "ollama")):
        try:
            answers[answer_key] = _ask_backend(question, backend=backend_name)
        except Exception as exc:
            answers[answer_key] = f"[{backend_name} unavailable] {exc}"

        add_message(
            con,
            conv_id,
            source="council",
            role="assistant",
            content=answers[answer_key],
            meta={"stage": "backend_answer", "backend": answer_key},
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
