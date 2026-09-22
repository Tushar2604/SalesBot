"""Message rendering: variables and spintax.

Two rules, both learned from what goes wrong in outreach tooling:

1. **A missing variable is never rendered.** "Hi , saw you work at " is worse
   than not sending at all, so an unresolved variable without a fallback raises
   and the lead is skipped rather than messaged badly.
2. **Spintax is resolved per lead, deterministically.** Seeded from the
   enrollment id so the same prospect always sees the same wording — a retry
   must not send a subtly different message.
"""

from __future__ import annotations

import random
import re
import uuid
from dataclasses import dataclass
from typing import Any

# {{first_name}} or {{company|there}} — the part after | is the fallback.
_VARIABLE_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_.]+)\s*(?:\|\s*([^}]*?)\s*)?\}\}")
# Innermost {a|b|c} group, so nesting resolves from the inside out.
_SPINTAX_RE = re.compile(r"\{([^{}]*\|[^{}]*)\}")

MAX_INVITE_NOTE_CHARS = 300  # LinkedIn's limit on a connection-request note


class MissingVariableError(Exception):
    """A template referenced a field this lead does not have, with no fallback."""

    def __init__(self, variable: str) -> None:
        super().__init__(f"{variable} is empty for this lead and has no fallback")
        self.variable = variable


@dataclass(slots=True)
class LeadContext:
    """The values a template may reference.

    Deliberately a flat, explicit mapping rather than the ORM object: a
    template must never be able to reach `lead.workspace.members[0].email`.
    """

    values: dict[str, str]

    @classmethod
    def from_lead(cls, lead: Any, *, sender_name: str = "") -> LeadContext:
        values: dict[str, str] = {
            "first_name": (lead.first_name or "").strip(),
            "last_name": (lead.last_name or "").strip(),
            "full_name": (lead.full_name or "").strip(),
            "headline": (lead.headline or "").strip(),
            "company": (lead.company or "").strip(),
            "title": (lead.title or "").strip(),
            "location": (lead.location or "").strip(),
            "country": (lead.country or "").strip(),
            "email": (lead.email or "").strip(),
            "public_id": (lead.public_id or "").strip(),
            "sender_name": sender_name.strip(),
        }
        for key, value in (lead.custom_fields or {}).items():
            if value is None:
                continue
            values[f"custom.{key}"] = str(value).strip()
        return cls(values=values)

    def get(self, name: str) -> str:
        return self.values.get(name, "")


def resolve_spintax(text: str, rng: random.Random) -> str:
    """Collapses {a|b|c} groups, innermost first."""
    # Bounded loop: each pass removes at least one group, and a pathological
    # template must not spin forever.
    for _ in range(50):
        match = _SPINTAX_RE.search(text)
        if match is None:
            return text
        options = match.group(1).split("|")
        text = text[: match.start()] + rng.choice(options) + text[match.end() :]
    return text


def render(
    template: str,
    context: LeadContext,
    *,
    seed: uuid.UUID | str | None = None,
    strict: bool = True,
) -> str:
    """Renders a template for one lead.

    `strict=True` raises `MissingVariableError` rather than emitting a gap.
    """
    # Seeded per enrollment so a retry re-renders the identical message. Not a
    # security decision — this picks wording, not secrets.
    rng = (
        random.Random(str(seed))  # noqa: S311
        if seed is not None
        else random.Random()  # noqa: S311
    )

    def substitute(match: re.Match[str]) -> str:
        name, fallback = match.group(1), match.group(2)
        value = context.get(name)
        if value:
            return value
        if fallback is not None:
            return fallback
        if strict:
            raise MissingVariableError(name)
        return ""

    return resolve_spintax(_VARIABLE_RE.sub(substitute, template), rng).strip()


def variables_used(template: str) -> set[str]:
    """Variable names a template references — for validation in the builder."""
    return {match.group(1) for match in _VARIABLE_RE.finditer(template)}


def variables_without_fallback(template: str) -> set[str]:
    return {match.group(1) for match in _VARIABLE_RE.finditer(template) if match.group(2) is None}


def preview(template: str, *, seed: str = "preview") -> str:
    """Renders with plausible sample data, for the campaign builder."""
    sample = LeadContext(
        values={
            "first_name": "Priya",
            "last_name": "Sharma",
            "full_name": "Priya Sharma",
            "headline": "Head of Sales at Northwind",
            "company": "Northwind",
            "title": "Head of Sales",
            "location": "Bengaluru, India",
            "country": "India",
            "email": "priya@northwind.example",
            "public_id": "priya-sharma",
            "sender_name": "Tushar",
        }
    )
    return render(template, sample, seed=seed, strict=False)


def assign_variant(enrollment_id: uuid.UUID, variants: int = 2) -> str:
    """Deterministic A/B assignment.

    Hashing the enrollment id means the same lead keeps the same variant across
    retries and restarts, which is what makes per-variant stats meaningful.
    """
    index = int(uuid.UUID(str(enrollment_id)).int % max(1, variants))
    return chr(ord("A") + index)
