"""AI assistance for the post composer.

Everything here is *suggestion only*. There is no code path from a generated
draft to a published post: the model returns text, the text lands in the editor,
and a person still has to press Schedule or Publish. That is a deliberate
product rule, not an oversight.

Reuses the client pattern from `app.ai.classify` and the already-configured but
previously unused `AI_GENERATION_MODEL`.
"""

from __future__ import annotations

from typing import Any

import anthropic

from app.config import settings
from app.core.errors import UpstreamError
from app.core.logging import get_logger

log = get_logger(__name__)

MAX_INPUT_CHARS = 8000

_SYSTEM = (
    "You write and edit LinkedIn posts for B2B professionals. House style: "
    "specific over generic, no corporate filler, no em dashes, no invented "
    "statistics or customer names. Keep the author's voice and any factual "
    "claims exactly as given — you may rephrase, never fabricate. LinkedIn "
    "posts are plain text: no markdown headings, bold, or bullet syntax beyond "
    "simple line breaks and emoji. Stay under 3000 characters."
)

# What each editor action asks the model to do. Keeping them here rather than in
# the request means the client cannot smuggle its own instructions through.
ACTIONS: dict[str, str] = {
    "rewrite": "Rewrite this post so it reads better, keeping its meaning and length.",
    "shorter": "Make this post materially shorter while keeping its point and its best line.",
    "longer": "Expand this post with more substance — detail, example, or context. Do not pad.",
    "professional": "Rewrite this post in a more professional, measured register.",
    "conversational": "Rewrite this post in a warmer, more conversational register.",
    "hook": (
        "Rewrite only the opening so it earns the 'see more' click. The first line must "
        "stand alone and create a reason to keep reading. Return the whole post."
    ),
    "cta": (
        "Add a natural call to action at the end — a question or an invitation, not a "
        "sales pitch. Return the whole post."
    ),
    "hashtags": (
        "Return the same post with 3 to 5 relevant hashtags appended on their own line. "
        "Do not change the body text."
    ),
    "grammar": (
        "Fix spelling, grammar and punctuation only. Change nothing else — not the "
        "wording, not the structure."
    ),
    "variations": "Write three distinct versions of this post, each taking a different angle.",
    "repurpose": (
        "Turn this into a new post on the same subject with a different structure and "
        "opening, so it can be published again without repeating itself."
    ),
}

# Actions that legitimately return several options rather than one rewrite.
_MULTI = {"variations"}

_TOOL: dict[str, Any] = {
    "name": "return_posts",
    "description": "Return the finished LinkedIn post text.",
    "input_schema": {
        "type": "object",
        "properties": {
            "posts": {
                "type": "array",
                "items": {"type": "string"},
                "description": "One item per version. Plain text, ready to publish.",
            },
            "note": {
                "type": "string",
                "description": "One short sentence on what changed. Optional.",
            },
        },
        "required": ["posts"],
    },
}


def _client() -> anthropic.Anthropic:
    api_key = settings.anthropic_api_key.get_secret_value()
    if not api_key:
        raise UpstreamError(
            "AI assistance is not configured on this deployment (no Anthropic API key)."
        )
    return anthropic.Anthropic(api_key=api_key)


def _call(prompt: str, *, max_variants: int) -> tuple[list[str], str]:
    try:
        response = _client().messages.create(
            model=settings.ai_generation_model,
            max_tokens=2048,
            system=_SYSTEM,
            tools=[_TOOL],
            tool_choice={"type": "tool", "name": "return_posts"},
            messages=[{"role": "user", "content": prompt[:MAX_INPUT_CHARS]}],
        )
    except anthropic.APIError as exc:
        log.warning("ai.content_failed", error=str(exc))
        raise UpstreamError("the AI assistant is unavailable right now; try again") from exc

    for block in response.content:
        if block.type == "tool_use" and block.name == "return_posts":
            raw = block.input.get("posts") or []
            posts = [str(item).strip() for item in raw if str(item).strip()]
            if posts:
                return posts[:max_variants], str(block.input.get("note") or "")

    raise UpstreamError("the AI assistant returned nothing usable; try again")


def improve(content: str, action: str) -> tuple[list[str], str]:
    """Applies one editor action to existing copy."""
    instruction = ACTIONS.get(action)
    if instruction is None:
        raise UpstreamError(f"“{action}” is not something the assistant can do")

    prompt = f"{instruction}\n\nHere is the post:\n\n{content}"
    return _call(prompt, max_variants=3 if action in _MULTI else 1)


def generate(*, topic: str, audience: str, tone: str, goal: str) -> tuple[list[str], str]:
    """Drafts a post from a brief. The result goes to the editor, never further."""
    lines = [
        "Write a LinkedIn post.",
        f"Subject: {topic}",
        f"Audience: {audience}"
        if audience.strip()
        else "Audience: a general professional audience",
        f"Tone: {tone}",
        f"Goal: {goal}",
        "",
        "Open with a line that earns attention on its own. Keep paragraphs short. "
        "End with something that invites a response. Do not invent statistics, "
        "customer names, or results.",
    ]
    return _call("\n".join(lines), max_variants=1)
