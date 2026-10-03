"""Auto-like topic rules: which posts the engine may like, and that it obeys them."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.linkedin import like_rules
from app.models.campaigns import ActionTask, StepType
from app.worker.tasks import auto_engage

AI_POST = {"urn": "urn:li:activity:1", "text": "Our new machine learning model cut churn by 20%"}
HIRING_POST = {"urn": "urn:li:activity:2", "text": "We're hiring backend engineers in Pune!"}
POLITICS_POST = {"urn": "urn:li:activity:3", "text": "Thoughts on the election and politics today"}
SAID_POST = {"urn": "urn:li:activity:4", "text": "She said the quarter went well"}


def rules(**kw: Any) -> like_rules.LikeRules:
    return like_rules.resolve({"use_ai": False, **kw})


# ── the rules ────────────────────────────────────────────────────────────────


def test_topics_mode_without_topics_falls_back_to_any() -> None:
    assert like_rules.resolve({"mode": "topics", "topics": []}).mode == "any"
    assert like_rules.resolve(None).mode == "any"


def test_topics_are_cleaned_deduplicated_and_capped() -> None:
    resolved = like_rules.resolve(
        {"mode": "topics", "topics": ["  SaaS ", "saas", "", "AI"] + ["x"] * 40}
    )
    assert resolved.topics[:2] == ["SaaS", "AI"]
    assert len(resolved.topics) <= like_rules.MAX_TOPICS


def test_a_topic_phrase_matches_any_of_its_parts() -> None:
    r = rules(mode="topics", topics=["AI and machine learning"])
    assert like_rules.keyword_verdict(AI_POST, r).like
    assert like_rules.keyword_verdict(AI_POST, r).topic == "AI and machine learning"
    assert not like_rules.keyword_verdict(HIRING_POST, r).like


def test_matching_is_by_whole_word() -> None:
    """ "AI" must not match "said"."""
    assert not like_rules.keyword_verdict(SAID_POST, rules(mode="topics", topics=["AI"])).like


def test_excluded_topics_always_win() -> None:
    r = rules(mode="any", exclude=["Politics"])
    assert like_rules.keyword_verdict(HIRING_POST, r).like
    verdict = like_rules.keyword_verdict(POLITICS_POST, r)
    assert not verdict.like and "excluded" in verdict.reason


def test_ai_matches_by_meaning(monkeypatch: pytest.MonkeyPatch) -> None:
    """A post about LLMs has no keyword "AI" in it; the AI judge still gets it."""
    llm_post = {"urn": "u", "text": "Fine-tuning large language models on support tickets"}
    monkeypatch.setattr("app.ai.assistant.available_providers", lambda: ["gemini"])
    monkeypatch.setattr(
        "app.ai.assistant.ask_structured",
        lambda system, user, schema: schema(
            posts=[{"index": 0, "topic": "AI and machine learning", "excluded": ""}]
        ),
    )
    r = like_rules.resolve(
        {"mode": "topics", "topics": ["AI and machine learning"], "use_ai": True}
    )
    assert not like_rules.keyword_verdict(llm_post, r).like
    [verdict] = like_rules.judge([llm_post], r)
    assert verdict.like and verdict.by == "ai"


def test_a_keyword_exclusion_is_never_overridden_by_the_ai(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.ai.assistant.available_providers", lambda: ["gemini"])
    monkeypatch.setattr(
        "app.ai.assistant.ask_structured",
        lambda system, user, schema: schema(posts=[{"index": 0, "topic": "", "excluded": ""}]),
    )
    r = like_rules.resolve({"mode": "any", "exclude": ["Politics"], "use_ai": True})
    [verdict] = like_rules.judge([POLITICS_POST], r)
    assert not verdict.like


def test_without_an_ai_provider_keywords_are_used(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.ai.assistant.available_providers", lambda: [])
    r = like_rules.resolve({"mode": "topics", "topics": ["hiring"], "use_ai": True})
    verdicts = like_rules.judge([AI_POST, HIRING_POST], r)
    assert [v.like for v in verdicts] == [False, True]


def test_verdicts_are_cached_per_rule_set(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []
    real = like_rules.judge
    monkeypatch.setattr(
        like_rules, "judge", lambda posts, r: calls.append(len(posts)) or real(posts, r)
    )
    r = rules(mode="topics", topics=["hiring"])
    feed, changed = like_rules.judge_feed([AI_POST, HIRING_POST], r)
    assert changed and calls == [2]
    _, changed_again = like_rules.judge_feed(feed, r)
    assert not changed_again and calls == [2]  # nothing re-judged
    like_rules.judge_feed(feed, rules(mode="topics", topics=["sales"]))
    assert calls == [2, 2]  # new rules → judged again


# ── the engine obeys them ────────────────────────────────────────────────────


def _auto_like_account(sdb: Session, rules_raw: dict[str, Any], feed: list[dict[str, Any]]) -> Any:
    from tests.test_inbox import make_account, make_workspace

    workspace = make_workspace(sdb)
    account = make_account(sdb, workspace)
    account.auto_like_enabled = True
    account.auto_like_rules = rules_raw
    account.cached_feed = feed
    account.cached_feed_at = datetime.now(UTC)
    account.caps = {
        **(account.caps or {}),
        "working_hours": {"start": "00:00", "end": "23:59"},
        "weekdays_only": False,
    }
    sdb.flush()
    return account


def test_the_engine_only_likes_posts_about_the_chosen_topics(
    sdb: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.test_inbox import _bind_session_scope

    account = _auto_like_account(
        sdb,
        {"mode": "topics", "topics": ["hiring"], "use_ai": False},
        [AI_POST, HIRING_POST, POLITICS_POST],
    )
    monkeypatch.setattr(auto_engage.random, "random", lambda: 0.0)  # always try this tick
    with _bind_session_scope(monkeypatch, auto_engage, sdb):
        result = auto_engage.consider_auto_like(str(account.id))
    assert result["status"] == "queued" and result["post_urn"] == HIRING_POST["urn"]
    task = sdb.execute(
        select(ActionTask).where(
            ActionTask.linkedin_account_id == account.id,
            ActionTask.action_type == StepType.LIKE_POST,
        )
    ).scalar_one()
    assert task.payload["matched_topic"] == "hiring"


def test_nothing_is_liked_when_no_post_matches(
    sdb: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.test_inbox import _bind_session_scope

    account = _auto_like_account(
        sdb,
        {"mode": "topics", "topics": ["cybersecurity"], "use_ai": False},
        [AI_POST, HIRING_POST],
    )
    monkeypatch.setattr(auto_engage.random, "random", lambda: 0.0)
    with _bind_session_scope(monkeypatch, auto_engage, sdb):
        result = auto_engage.consider_auto_like(str(account.id))
    assert result["status"] == "no_matching_posts"


# ── the API ──────────────────────────────────────────────────────────────────


async def test_rules_can_be_saved_and_previewed(client: AsyncClient, db: Any) -> None:
    from tests.test_inbox_api import auth, make_conversation, register

    token, ws = await register(client)
    # make_conversation creates an account in this workspace; reuse it.
    await make_conversation(db, ws)
    accounts = (
        await client.get(f"/api/v1/workspaces/{ws}/linkedin-accounts", headers=auth(token))
    ).json()
    account_id = accounts[0]["id"]
    from app.models.linkedin import LinkedInAccount

    row = await db.get(LinkedInAccount, account_id)
    row.cached_feed = [AI_POST, HIRING_POST, POLITICS_POST]
    await db.flush()
    url = f"/api/v1/workspaces/{ws}/linkedin-accounts/{account_id}/auto-like-rules"

    empty = await client.put(url, json={"mode": "topics", "topics": []}, headers=auth(token))
    assert empty.status_code == 422

    saved = await client.put(
        url,
        json={
            "mode": "topics",
            "topics": ["hiring", "AI"],
            "exclude": ["politics"],
            "use_ai": False,
        },
        headers=auth(token),
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["topics"] == ["hiring", "AI"]
    assert (await client.get(url, headers=auth(token))).json()["exclude"] == ["politics"]

    preview = (
        await client.post(
            f"{url}/preview",
            json={"mode": "topics", "topics": ["hiring"], "use_ai": False},
            headers=auth(token),
        )
    ).json()
    assert preview["matching"] == 1
    assert [p["would_like"] for p in preview["posts"]] == [False, True, False]
