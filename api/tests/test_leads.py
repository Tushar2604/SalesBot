"""CSV import: URL parsing, column guessing, dedupe, blocklists.

Import is where a customer's data quality meets ours. Every case here came from
a real CSV shape: exports name their columns differently, paste URLs with
tracking parameters, repeat rows, and sometimes map the wrong column entirely.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.services.lead_service import extract_public_id, guess_mapping


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://www.linkedin.com/in/priya-sharma/", "priya-sharma"),
        ("https://linkedin.com/in/arjun-mehta", "arjun-mehta"),
        ("www.linkedin.com/in/sara-lund?trk=people-search", "sara-lund"),
        ("http://LinkedIn.com/IN/Mixed-Case", "mixed-case"),
        # Locale-prefixed URLs are common in European exports.
        ("https://de.linkedin.com/in/hans-mueller", "hans-mueller"),
        ("linkedin.com/in/with.dots", "with.dots"),
        # A bare handle is legitimate and indistinguishable from any other slug.
        ("priya-sharma", "priya-sharma"),
        ("  Priya-Sharma  ", "priya-sharma"),
    ],
)
def test_profile_urls_are_parsed(value: str, expected: str) -> None:
    assert extract_public_id(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "",
        "   ",
        # Looks like a URL but is not a LinkedIn profile — the wrong column.
        "not-a-url.com",
        "https://example.com/in/someone",
        "https://twitter.com/someone",
        "priya@northwind.example",
        "Priya Sharma",
        "ab",  # too short to be a handle
        # A company page is not a person.
        "https://www.linkedin.com/company/northwind",
    ],
)
def test_non_profiles_are_rejected(value: str) -> None:
    assert extract_public_id(value) == ""


def test_headers_are_guessed_across_spellings() -> None:
    """The regression this exists for: "Job Title" was not being mapped."""
    mapping = guess_mapping(
        [
            "Name",
            "LinkedIn Profile",
            "Job Title",
            "Work Email",
            "Company Name",
            "Segment",
        ]
    )

    assert mapping["LinkedIn Profile"] == "public_id"
    assert mapping["Job Title"] == "title"
    assert mapping["Work Email"] == "email"
    assert mapping["Company Name"] == "company"
    assert mapping["Name"] == "full_name"
    # Unrecognised columns are left alone and become custom fields.
    assert "Segment" not in mapping


@pytest.mark.parametrize(
    "header",
    ["job_title", "JobTitle", "Job-Title", "JOB TITLE", "position", "Role"],
)
def test_title_aliases_all_map(header: str) -> None:
    assert guess_mapping([header]) == {header: "title"}


def test_one_profile_column_wins_not_several() -> None:
    """A file with both a URL column and a handle column must not map both."""
    mapping = guess_mapping(["LinkedIn URL", "public_id"])
    assert list(mapping.values()).count("public_id") == 1


# ── the import endpoint ──────────────────────────────────────────────────────

CSV_BODY = b"""Name,LinkedIn Profile,Company Name,Job Title,Work Email,Segment
Priya Sharma,https://www.linkedin.com/in/priya-demo/,Northwind,Head of Sales,priya@northwind.example,Enterprise
Arjun Mehta,https://linkedin.com/in/arjun-demo,Contoso,VP Revenue,arjun@contoso.example,Mid-market
Broken Row,not-a-url.com,Nowhere,,,
Dup Priya,https://www.linkedin.com/in/priya-demo/,Northwind,Head of Sales,,
"""


async def register(client: AsyncClient) -> tuple[str, str]:
    signup = await client.post(
        "/api/v1/auth/signup",
        json={
            "email": "owner@example.com",
            "password": "correct horse 7",
            "full_name": "Owner",
            "workspace_name": "Acme",
        },
    )
    token = signup.json()["access_token"]
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    return token, me.json()["workspaces"][0]["workspace"]["id"]


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def test_import_accounts_for_every_row(client: AsyncClient) -> None:
    token, ws = await register(client)

    response = await client.post(
        f"/api/v1/workspaces/{ws}/leads/import-csv",
        headers=auth(token),
        files={"file": ("leads.csv", CSV_BODY, "text/csv")},
        data={"list_name": "Demo"},
    )

    assert response.status_code == 201, response.text
    report = response.json()
    assert report["total_rows"] == 4
    assert report["imported"] == 2
    assert report["skipped"] == 2

    reasons = {problem["reason"] for problem in report["problems"]}
    assert any("profile" in reason for reason in reasons)
    assert any("duplicate" in reason for reason in reasons)

    leads = (await client.get(f"/api/v1/workspaces/{ws}/leads", headers=auth(token))).json()
    assert leads["total"] == 2
    by_handle = {lead["public_id"]: lead for lead in leads["items"]}
    assert set(by_handle) == {"priya-demo", "arjun-demo"}

    priya = by_handle["priya-demo"]
    assert priya["first_name"] == "Priya"
    assert priya["last_name"] == "Sharma"
    assert priya["title"] == "Head of Sales"
    assert priya["company"] == "Northwind"
    # An unmapped column survives as a custom field for templating.
    assert priya["custom_fields"]["Segment"] == "Enterprise"


async def test_reimporting_updates_rather_than_duplicating(client: AsyncClient) -> None:
    token, ws = await register(client)
    files = {"file": ("leads.csv", CSV_BODY, "text/csv")}

    first = await client.post(
        f"/api/v1/workspaces/{ws}/leads/import-csv", headers=auth(token), files=files
    )
    second = await client.post(
        f"/api/v1/workspaces/{ws}/leads/import-csv",
        headers=auth(token),
        files={"file": ("leads.csv", CSV_BODY, "text/csv")},
    )

    assert first.json()["imported"] == 2
    assert second.json()["updated"] == 2
    assert second.json()["imported"] == 0

    leads = (await client.get(f"/api/v1/workspaces/{ws}/leads", headers=auth(token))).json()
    assert leads["total"] == 2


async def test_a_file_without_a_profile_column_is_refused(client: AsyncClient) -> None:
    token, ws = await register(client)

    response = await client.post(
        f"/api/v1/workspaces/{ws}/leads/import-csv",
        headers=auth(token),
        files={"file": ("bad.csv", b"Name,Company\nPriya,Northwind\n", "text/csv")},
    )

    assert response.status_code == 422
    assert "profile" in response.json()["error"]["message"]


async def test_blocklisted_company_is_skipped_on_import(client: AsyncClient) -> None:
    token, ws = await register(client)

    await client.post(
        f"/api/v1/workspaces/{ws}/blocklist",
        json={"kind": "company", "value": "Northwind"},
        headers=auth(token),
    )

    response = await client.post(
        f"/api/v1/workspaces/{ws}/leads/import-csv",
        headers=auth(token),
        files={"file": ("leads.csv", CSV_BODY, "text/csv")},
    )

    report = response.json()
    assert report["imported"] == 1  # only Arjun at Contoso
    assert any("blocklist" in problem["reason"] for problem in report["problems"])


async def test_blocklist_values_are_normalised(client: AsyncClient) -> None:
    """Matching must not depend on how the entry was typed."""
    token, ws = await register(client)

    created = await client.post(
        f"/api/v1/workspaces/{ws}/blocklist",
        json={"kind": "domain", "value": "  @Competitor.COM  "},
        headers=auth(token),
    )
    assert created.json()["value"] == "competitor.com"

    profile = await client.post(
        f"/api/v1/workspaces/{ws}/blocklist",
        json={"kind": "profile", "value": "https://www.linkedin.com/in/Someone-Else/"},
        headers=auth(token),
    )
    assert profile.json()["value"] == "someone-else"


async def test_adding_the_same_blocklist_entry_twice_is_idempotent(
    client: AsyncClient,
) -> None:
    token, ws = await register(client)
    body = {"kind": "domain", "value": "competitor.com"}

    first = await client.post(f"/api/v1/workspaces/{ws}/blocklist", json=body, headers=auth(token))
    second = await client.post(f"/api/v1/workspaces/{ws}/blocklist", json=body, headers=auth(token))

    assert first.json()["id"] == second.json()["id"]
    entries = (await client.get(f"/api/v1/workspaces/{ws}/blocklist", headers=auth(token))).json()
    assert len(entries) == 1


async def test_another_tenant_cannot_read_your_leads(client: AsyncClient) -> None:
    token, ws = await register(client)
    await client.post(
        f"/api/v1/workspaces/{ws}/leads/import-csv",
        headers=auth(token),
        files={"file": ("leads.csv", CSV_BODY, "text/csv")},
    )

    outsider = await client.post(
        "/api/v1/auth/signup",
        json={
            "email": "outsider@example.org",
            "password": "correct horse 7",
            "full_name": "Outsider",
            "workspace_name": "Other",
        },
    )
    outsider_token = outsider.json()["access_token"]

    response = await client.get(f"/api/v1/workspaces/{ws}/leads", headers=auth(outsider_token))
    assert response.status_code == 404
