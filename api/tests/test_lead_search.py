"""AI lead finder: criteria → providers → ranked, filtered results → import.

No real provider or LLM is called: HTTP goes through httpx.MockTransport and
the criteria step is replaced with a fixed reading. The one property that
matters most — no LinkedIn account is touched — has its own test.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import httpx
import pytest
from httpx import AsyncClient

from app.leadsearch import criteria as criteria_mod
from app.leadsearch import providers as providers_mod
from app.leadsearch.criteria import Interpretation, SearchCriteria
from app.services import lead_search_service
from tests.test_inbox_api import auth, register

CRITERIA = SearchCriteria(
    titles=["Head of HR", "HR Director"],
    locations=["Bengaluru, India"],
    industries=["fintech"],
    count=5,
)


def _profile(i: int, **extra: Any) -> dict[str, Any]:
    return {
        "linkedin_url": f"linkedin.com/in/person-{i}",
        "first_name": f"First{i}",
        "last_name": f"Last{i}",
        "job_title": "Head of HR",
        "job_company_name": f"Fintech {i}",
        "location_name": "Bengaluru, Karnataka, India",
        **extra,
    }


def _only(monkeypatch: pytest.MonkeyPatch, **keys: str) -> None:
    """Configure exactly these providers (in this order)."""
    for name in ("exa", "pdl", "apollo"):
        monkeypatch.setattr(providers_mod.settings, f"{name}_api_key", _secret(keys.get(name, "")))
    monkeypatch.setattr(
        providers_mod.settings, "brave_search_api_key", _secret(keys.get("brave", ""))
    )
    monkeypatch.setattr(providers_mod.settings, "lead_search_providers", ",".join(keys))


def _secret(value: str) -> Any:
    from pydantic import SecretStr

    return SecretStr(value)


def _mock(monkeypatch: pytest.MonkeyPatch, handler: Any) -> list[httpx.Request]:
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    transport = httpx.MockTransport(record)
    monkeypatch.setattr(
        lead_search_service.providers_mod,
        "new_client",
        lambda _t=None: httpx.AsyncClient(transport=transport),
    )
    return seen


def _reading(monkeypatch: pytest.MonkeyPatch, criteria: SearchCriteria = CRITERIA) -> None:
    monkeypatch.setattr(
        criteria_mod,
        "interpret",
        lambda message, previous=None: Interpretation(
            criteria=criteria,
            reply="Looking for HR heads at fintechs in Bengaluru.",
            needs_clarification=False,
        ),
    )


# ── provider request building and parsing ───────────────────────────────────


def test_pdl_query_combines_every_filter() -> None:
    query = providers_mod.pdl_query(
        CRITERIA.model_copy(
            update={"seniorities": ["director", "c_suite"], "company_size": "11,200"}
        )
    )
    must = query["bool"]["must"]
    assert {"exists": {"field": "linkedin_url"}} in must
    titles = must[1]["bool"]["should"]
    assert {"match_phrase": {"job_title": "Head of HR"}} in titles
    assert {"match": {"location_name": "Bengaluru"}} in must[2]["bool"]["should"]
    assert {"terms": {"job_title_levels": ["cxo", "director"]}} in must
    assert {"terms": {"job_company_size": ["11-50", "51-200"]}} in must


def test_xray_query_targets_public_profile_pages() -> None:
    query = providers_mod.xray_query(CRITERIA)
    assert query.startswith("site:linkedin.com/in ")
    assert '("Head of HR" OR "HR Director")' in query
    assert '"Bengaluru"' in query


def test_a_search_result_title_is_split_into_name_title_company() -> None:
    parsed = providers_mod._parse_profile_title("Priya Sharma - Head of HR - Acme Pay | LinkedIn")
    assert parsed["first_name"] == "Priya" and parsed["last_name"] == "Sharma"
    assert parsed["title"] == "Head of HR" and parsed["company"] == "Acme Pay"


async def test_exa_results_use_the_person_entity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(providers_mod.settings, "exa_api_key", _secret("k"))
    body = {
        "results": [
            {
                "url": "https://www.linkedin.com/in/priya-s",
                "title": "Priya S | LinkedIn",
                "entities": [
                    {
                        "type": "person",
                        "properties": {
                            "name": "Priya Sharma",
                            "location": "Bengaluru, India",
                            "workHistory": [
                                {"title": "Head of HR", "company": {"name": "Acme Pay"}}
                            ],
                        },
                    }
                ],
            },
            {"url": "https://example.com/blog", "title": "not a profile"},
        ]
    }
    transport = httpx.MockTransport(lambda r: httpx.Response(200, json=body))
    async with httpx.AsyncClient(transport=transport) as client:
        rows = await providers_mod.ExaProvider().search(CRITERIA, 5, client)
    assert [(r.public_id, r.first_name, r.title, r.company, r.location) for r in rows] == [
        ("priya-s", "Priya", "Head of HR", "Acme Pay", "Bengaluru, India")
    ]


async def test_apollo_enriches_search_hits_to_get_linkedin_urls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(providers_mod.settings, "apollo_api_key", _secret("k"))

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/mixed_people/api_search"):
            assert request.url.params.get_list("person_titles[]") == CRITERIA.titles
            return httpx.Response(200, json={"people": [{"id": "a1"}, {"id": "a2"}]})
        details = json.loads(request.content)["details"]
        assert details == [{"id": "a1"}, {"id": "a2"}]
        return httpx.Response(
            200,
            json={
                "matches": [
                    {
                        "linkedin_url": "http://www.linkedin.com/in/ravi-k",
                        "first_name": "Ravi",
                        "last_name": "K",
                        "title": "HR Director",
                        "city": "Bengaluru",
                        "country": "India",
                        "organization": {"name": "PayCo"},
                    },
                    {"linkedin_url": None, "first_name": "No URL"},
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        rows = await providers_mod.ApolloProvider().search(CRITERIA, 5, client)
    assert [(r.public_id, r.company, r.location) for r in rows] == [
        ("ravi-k", "PayCo", "Bengaluru, India")
    ]


def test_without_an_llm_the_message_is_searched_as_keywords(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(criteria_mod.ai, "ask_structured", lambda *a, **k: None)
    reading = criteria_mod.interpret("python developers in pune")
    assert reading.criteria.keywords == ["python developers in pune"]
    assert not reading.needs_clarification

    reading = criteria_mod.interpret("Find me 12 HR heads at fintechs with 50-500 employees")
    assert reading.criteria.count == 12
    assert reading.criteria.keywords == ["HR heads at fintechs with 50-500 employees"]


# ── the chat endpoint ────────────────────────────────────────────────────────


async def test_chat_finds_ranks_and_filters_people(
    client: AsyncClient, db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.models.leads import BlocklistEntry, BlocklistKind, ContactedLead

    token, ws = await register(client)
    _only(monkeypatch, pdl="k")
    _reading(monkeypatch)
    people = [_profile(i) for i in range(1, 8)]
    people[0]["job_title"] = "Software Engineer"  # a weak match ranks last
    seen = _mock(monkeypatch, lambda r: httpx.Response(200, json={"data": people}))

    db.add(ContactedLead(workspace_id=uuid.UUID(ws), public_id="person-2"))
    db.add(
        BlocklistEntry(workspace_id=uuid.UUID(ws), kind=BlocklistKind.COMPANY, value="fintech 3")
    )
    await db.flush()

    response = await client.post(
        f"/api/v1/workspaces/{ws}/lead-search/chat",
        json={"message": "HR heads at fintechs in Bangalore"},
        headers=auth(token),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    ids = [r["public_id"] for r in body["search"]["results"]]
    assert "person-2" not in ids and "person-3" not in ids  # contacted, blocklisted
    assert len(ids) == 5  # the count asked for
    assert ids[-1] == "person-1"  # the weak title match ranks last
    top = body["search"]["results"][0]
    assert any("title matches" in reason for reason in top["match_reasons"])
    assert [r.headers["x-api-key"] for r in seen] == ["k"]
    assert [m["role"] for m in body["search"]["messages"]] == ["user", "assistant"]


async def test_the_lead_finder_never_uses_a_linkedin_account(
    client: AsyncClient, db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The whole point: searching must not go through a LinkedIn session."""
    import app.linkedin as linkedin_pkg

    def forbidden(*_a: Any, **_k: Any) -> None:
        raise AssertionError("the lead finder built a LinkedIn driver")

    monkeypatch.setattr(linkedin_pkg, "build_driver", forbidden)
    token, ws = await register(client)
    _only(monkeypatch, pdl="k")
    _reading(monkeypatch)
    seen = _mock(monkeypatch, lambda r: httpx.Response(200, json={"data": [_profile(1)]}))
    response = await client.post(
        f"/api/v1/workspaces/{ws}/lead-search/chat", json={"message": "x"}, headers=auth(token)
    )
    assert response.status_code == 200
    assert all("linkedin.com" not in r.url.host for r in seen)


async def test_a_failing_provider_falls_through_to_the_next(
    client: AsyncClient, db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    token, ws = await register(client)
    _only(monkeypatch, pdl="k", brave="b")
    _reading(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        if "peopledatalabs" in request.url.host:
            return httpx.Response(402, json={"error": "out of credits"})
        return httpx.Response(
            200,
            json={
                "web": {
                    "results": [
                        {
                            "url": "https://in.linkedin.com/in/asha-m",
                            "title": "Asha M - HR Director - PayCo | LinkedIn",
                            "description": "Location: Bengaluru · 500+ connections",
                        }
                    ]
                }
            },
        )

    _mock(monkeypatch, handler)
    body = (
        await client.post(
            f"/api/v1/workspaces/{ws}/lead-search/chat", json={"message": "x"}, headers=auth(token)
        )
    ).json()
    assert [r["public_id"] for r in body["search"]["results"]] == ["asha-m"]
    assert body["search"]["provider"] == "brave"
    assert any("out of credits" in n for n in body["notices"])


async def test_no_provider_configured_explains_instead_of_failing(
    client: AsyncClient, db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    token, ws = await register(client)
    _only(monkeypatch)
    _reading(monkeypatch)
    body = (
        await client.post(
            f"/api/v1/workspaces/{ws}/lead-search/chat", json={"message": "x"}, headers=auth(token)
        )
    ).json()
    assert "No lead data provider" in body["reply"]
    assert body["search"]["results"] == []


async def test_asking_for_more_never_repeats_people(
    client: AsyncClient, db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    token, ws = await register(client)
    _only(monkeypatch, pdl="k")
    _reading(monkeypatch)
    _mock(
        monkeypatch,
        lambda r: httpx.Response(200, json={"data": [_profile(i) for i in range(1, 12)]}),
    )
    url = f"/api/v1/workspaces/{ws}/lead-search/chat"
    first = (await client.post(url, json={"message": "x"}, headers=auth(token))).json()
    second = (
        await client.post(
            url, json={"message": "more", "search_id": first["search"]["id"]}, headers=auth(token)
        )
    ).json()
    before = {r["public_id"] for r in first["search"]["results"]}
    after = {r["public_id"] for r in second["search"]["results"]}
    assert before and after and not (before & after)


async def test_daily_limit(client: AsyncClient, db: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    token, ws = await register(client)
    _only(monkeypatch, pdl="k")
    _reading(monkeypatch)
    _mock(monkeypatch, lambda r: httpx.Response(200, json={"data": [_profile(1)]}))
    monkeypatch.setattr(lead_search_service.settings, "lead_search_daily_limit", 1)
    url = f"/api/v1/workspaces/{ws}/lead-search/chat"
    assert (await client.post(url, json={"message": "x"}, headers=auth(token))).status_code == 200
    blocked = await client.post(url, json={"message": "y"}, headers=auth(token))
    assert blocked.status_code >= 400 and "today" in blocked.text


async def test_importing_found_people_creates_a_lead_list(
    client: AsyncClient, db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    token, ws = await register(client)
    _only(monkeypatch, pdl="k")
    _reading(monkeypatch)
    _mock(monkeypatch, lambda r: httpx.Response(200, json={"data": [_profile(1), _profile(2)]}))
    chat = (
        await client.post(
            f"/api/v1/workspaces/{ws}/lead-search/chat", json={"message": "x"}, headers=auth(token)
        )
    ).json()
    search_id = chat["search"]["id"]

    imported = await client.post(
        f"/api/v1/workspaces/{ws}/lead-search/searches/{search_id}/import",
        json={"public_ids": ["person-1", "someone-else"], "list_name": "HR heads"},
        headers=auth(token),
    )
    assert imported.status_code == 201, imported.text
    report = imported.json()
    assert report["imported"] == 1 and report["skipped"] == 1  # not from this search

    leads = (
        await client.get(
            f"/api/v1/workspaces/{ws}/leads",
            params={"list_id": report["list_id"]},
            headers=auth(token),
        )
    ).json()["items"]
    assert [(lead["public_id"], lead["first_name"], lead["company"]) for lead in leads] == [
        ("person-1", "First1", "Fintech 1")
    ]
    again = (
        await client.get(
            f"/api/v1/workspaces/{ws}/lead-search/searches/{search_id}", headers=auth(token)
        )
    ).json()
    marked = {r["public_id"]: r["in_leads"] for r in again["results"]}
    assert marked == {"person-1": True, "person-2": False}
