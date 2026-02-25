"""Context window builder utilities."""

from typing import List, Dict, Sequence
from openai.types.chat import ChatCompletionMessageParam
import tiktoken

# Fallback encoding name works for all GPT-4+/5 models
ENCODING_NAME = "cl100k_base"


def count_tokens(messages: Sequence[ChatCompletionMessageParam]) -> int:
    enc = tiktoken.get_encoding(ENCODING_NAME)
    total = 0
    for m in messages:
        # Allow special tokens to be treated as normal text to avoid encode errors on
        # strings that contain reserved markers like <|endoftext|>.
        # ChatCompletionMessageParam is a TypedDict; treat content as str for counting
        total += len(enc.encode(m.get("content", ""), disallowed_special=()))  # type: ignore[arg-type]
    return total


def build_context(
    *,
    system_message: ChatCompletionMessageParam | None,
    conversation_messages: Sequence[ChatCompletionMessageParam],
    max_tokens: int,
    reserve_tokens: int = 512
) -> List[ChatCompletionMessageParam]:
    """
    Deterministically build a context window.

    - system_message is always first (if provided)
    - messages are added from newest -> oldest
    - stops exactly at token limit
    - no summarisation
    """

    context: List[ChatCompletionMessageParam] = []

    if system_message:
        context.append(system_message)

    # tokens already used
    used = count_tokens(context)

    # walk backwards through history
    for m in reversed(conversation_messages):
        if m["role"] not in ("user", "assistant", "tool"):
            continue

        tokens = count_tokens([m])
        if used + tokens + reserve_tokens > max_tokens:
            break

        context.insert(1 if system_message else 0, m)
        used += tokens

    return context
