from __future__ import annotations

import os
from typing import Any

import requests
from openai import OpenAI


def _is_true(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _effective_backend(explicit_backend: str | None) -> str:
    backend = (explicit_backend or os.getenv("CHATVAULT_LLM_BACKEND", "openai")).strip().lower()
    if backend not in {"openai", "anthropic", "ollama"}:
        raise RuntimeError(f"Unsupported LLM backend '{backend}'. Use openai, anthropic, or ollama.")
    return backend


def _enforce_offline(backend: str) -> None:
    offline = _is_true(os.getenv("CHATVAULT_OFFLINE", "false"))
    if offline and backend in {"openai", "anthropic"}:
        raise RuntimeError(
            f"Offline mode is enabled but backend '{backend}' is configured. "
            "Please switch CHATVAULT_LLM_BACKEND to 'ollama' or disable offline mode."
        )


def _normalize_messages(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for m in messages:
        role = str(m.get("role", "user"))
        content = m.get("content", "")
        if isinstance(content, list):
            text_parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    text_parts.append(str(item.get("text", "")))
                elif isinstance(item, str):
                    text_parts.append(item)
            content = "\n".join(text_parts)
        if not isinstance(content, str):
            content = str(content)
        out.append({"role": role, "content": content})
    return out


def _with_system(messages: list[dict[str, Any]], system_prompt: str | None) -> list[dict[str, str]]:
    normalized = _normalize_messages(messages)
    if system_prompt and system_prompt.strip():
        return [{"role": "system", "content": system_prompt.strip()}] + normalized
    return normalized


def _openai_chat(messages: list[dict[str, Any]], system_prompt: str | None, temperature: float, max_tokens: int, **kwargs) -> str:
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is not set.")
    model = kwargs.get("model") or os.getenv("OPENAI_MODEL_DEFAULT", "gpt-4o-mini")
    client = OpenAI(api_key=key)
    resp = client.chat.completions.create(
        model=model,
        messages=_with_system(messages, system_prompt),
        temperature=float(temperature),
        max_tokens=int(max_tokens),
    )
    return (resp.choices[0].message.content or "").strip()


def _anthropic_chat(messages: list[dict[str, Any]], system_prompt: str | None, temperature: float, max_tokens: int, **kwargs) -> str:
    key = os.getenv("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set.")
    model = kwargs.get("model") or os.getenv("ANTHROPIC_MODEL_DEFAULT", "claude-3-5-sonnet-20241022")
    payload = {
        "model": model,
        "max_tokens": int(max_tokens),
        "temperature": float(temperature),
        "messages": _normalize_messages(messages),
    }
    if system_prompt and system_prompt.strip():
        payload["system"] = system_prompt.strip()
    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json=payload,
        timeout=90,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Anthropic error: {resp.status_code} {resp.text}")
    data = resp.json()
    blocks = data.get("content") or []
    text = "\n".join([b.get("text", "") for b in blocks if isinstance(b, dict)])
    return text.strip()


def _ollama_chat(messages: list[dict[str, Any]], system_prompt: str | None, temperature: float, max_tokens: int, **kwargs) -> str:
    host = (os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434") or "").rstrip("/")
    model = kwargs.get("model") or os.getenv("OLLAMA_MODEL", "llama3")
    payload = {
        "model": model,
        "messages": _with_system(messages, system_prompt),
        "stream": False,
        "options": {
            "temperature": float(temperature),
            "num_predict": int(max_tokens),
        },
    }

    errors = []
    for endpoint in (f"{host}/v1/chat", f"{host}/api/chat"):
        try:
            resp = requests.post(endpoint, json=payload, timeout=120)
            if resp.status_code >= 400:
                errors.append(f"{endpoint} -> {resp.status_code} {resp.text}")
                continue
            data = resp.json()
            if isinstance(data.get("message"), dict):
                return str(data["message"].get("content", "")).strip()
            if "response" in data:
                return str(data.get("response") or "").strip()
            return str(data).strip()
        except Exception as exc:
            errors.append(f"{endpoint} -> {exc}")
    raise RuntimeError(
        "Ollama request failed. Ensure Ollama is running locally and model is pulled. "
        + " | ".join(errors)
    )


def generate_response(
    messages,
    system_prompt=None,
    temperature=0.2,
    max_tokens=1024,
    backend=None,
    **kwargs,
) -> str:
    """Generate a chat response using the configured LLM backend."""
    backend_name = _effective_backend(backend)
    _enforce_offline(backend_name)

    if backend_name == "openai":
        return _openai_chat(messages, system_prompt, temperature, max_tokens, **kwargs)
    if backend_name == "anthropic":
        return _anthropic_chat(messages, system_prompt, temperature, max_tokens, **kwargs)
    return _ollama_chat(messages, system_prompt, temperature, max_tokens, **kwargs)
