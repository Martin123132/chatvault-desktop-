from __future__ import annotations

import json
import os
from functools import lru_cache
from math import sqrt
from typing import Iterable, List, Sequence, Tuple

DEFAULT_EMBED_MODEL = os.getenv("CHATVAULT_EMBEDDINGS_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
DEFAULT_EMBED_BACKEND = os.getenv("CHATVAULT_EMBEDDINGS_BACKEND", "sentence-transformers")


@lru_cache(maxsize=1)
def _load_model(model_name: str = DEFAULT_EMBED_MODEL):
    backend = (DEFAULT_EMBED_BACKEND or "sentence-transformers").strip().lower()
    if backend != "sentence-transformers":
        raise RuntimeError(
            f"Unsupported embeddings backend '{backend}'. "
            "Currently only 'sentence-transformers' is supported."
        )
    try:
        from sentence_transformers import SentenceTransformer
    except Exception as exc:  # pragma: no cover - dependency guard
        raise RuntimeError(
            "sentence-transformers is required for semantic embeddings. "
            "Install requirements and retry."
        ) from exc

    try:
        return SentenceTransformer(model_name)
    except Exception as exc:  # pragma: no cover - model initialization guard
        raise RuntimeError(
            f"Failed to load local embeddings model '{model_name}'. If this is your first run, "
            "you may need to be online once to download the model. After download, embeddings "
            f"work offline. Original error: {exc}"
        ) from exc


def embed_text(text: str, model_name: str = DEFAULT_EMBED_MODEL) -> List[float]:
    model = _load_model(model_name)
    vec = model.encode([text], normalize_embeddings=True)[0]
    return [float(x) for x in vec]


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b:
        return 0.0
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sqrt(sum(x * x for x in a))
    nb = sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def dumps_embedding(vec: Iterable[float]) -> str:
    return json.dumps([float(x) for x in vec])


def loads_embedding(raw: str) -> List[float]:
    arr = json.loads(raw)
    return [float(x) for x in arr]


def rank_by_similarity(query_vec: Sequence[float], rows: Iterable[Tuple[int, int, str, str, str, str]], limit: int):
    scored = []
    for message_id, conversation_id, title, role, snippet, emb_json in rows:
        sim = cosine_similarity(query_vec, loads_embedding(emb_json))
        scored.append((sim, message_id, conversation_id, title, role, snippet))
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored[: max(1, limit)]
