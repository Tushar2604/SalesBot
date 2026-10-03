"""People-data providers for the lead finder.

Every provider takes the same SearchCriteria and returns Candidates with a
LinkedIn profile URL (people without one are dropped: without it a campaign
cannot act on them). None of them uses a LinkedIn account or session.

    exa     semantic search over an index of public profiles. Best at fuzzy,
            natural-language asks. Pay per search.
    pdl     People Data Labs: a licensed person dataset queried with
            Elasticsearch filters. Most precise filters. 1 credit per person
            returned.
    apollo  Apollo.io: search is free but hides LinkedIn URLs, so the top
            matches are enriched (people/bulk_match, 1 credit each).
    brave   Brave Search "X-ray": `site:linkedin.com/in` web search over
            public profile pages. Cheapest; thinnest data (name, title,
            company parsed from the result title).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, ClassVar

import httpx

from app.config import settings
from app.core.logging import get_logger
from app.leadsearch.criteria import SearchCriteria
from app.services.lead_service import extract_public_id

log = get_logger(__name__)

_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


class ProviderError(Exception):
    """A provider refused or failed (bad key, out of credits, outage)."""


@dataclass(slots=True)
class Candidate:
    public_id: str
    first_name: str = ""
    last_name: str = ""
    headline: str = ""
    title: str = ""
    company: str = ""
    location: str = ""
    avatar_url: str = ""
    provider: str = ""
    # Why this person matched, shown next to the result.
    match_reasons: list[str] = field(default_factory=list)
    score: float = 0.0

    @property
    def profile_url(self) -> str:
        return f"https://www.linkedin.com/in/{self.public_id}"

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "profile_url": self.profile_url}


def _split_name(full: str) -> tuple[str, str]:
    parts = full.strip().split()
    if not parts:
        return "", ""
    return parts[0], " ".join(parts[1:])


def _s(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


class Provider:
    name: ClassVar[str]

    def api_key(self) -> str:
        raise NotImplementedError

    async def search(
        self, criteria: SearchCriteria, limit: int, client: httpx.AsyncClient
    ) -> list[Candidate]:
        raise NotImplementedError

    @staticmethod
    def _raise_for(response: httpx.Response, provider: str) -> None:
        if response.status_code < 400:
            return
        detail = response.text[:300]
        if response.status_code in (401, 403):
            raise ProviderError(f"{provider} rejected the API key or plan ({response.status_code})")
        if response.status_code in (402, 429):
            raise ProviderError(f"{provider} is out of credits or rate-limited: {detail}")
        raise ProviderError(f"{provider} failed ({response.status_code}): {detail}")


# ── Exa ──────────────────────────────────────────────────────────────────────


class ExaProvider(Provider):
    name = "exa"
    URL = "https://api.exa.ai/search"

    def api_key(self) -> str:
        return settings.exa_api_key.get_secret_value()

    async def search(
        self, criteria: SearchCriteria, limit: int, client: httpx.AsyncClient
    ) -> list[Candidate]:
        response = await client.post(
            self.URL,
            headers={"x-api-key": self.api_key()},
            json={
                "query": criteria.as_sentence(),
                "category": "people",
                "type": "auto",
                # Some results are not profiles; ask for headroom.
                "numResults": min(100, limit * 2),
            },
        )
        self._raise_for(response, "Exa")
        out = []
        for row in response.json().get("results") or []:
            public_id = extract_public_id(_s(row.get("url")))
            if not public_id:
                continue
            person = _exa_person(row.get("entities"))
            first, last = _split_name(_s(person.get("name")))
            if person.get("firstName") or person.get("lastName"):
                first, last = _s(person.get("firstName")), _s(person.get("lastName"))
            title, company = _current_job(person.get("workHistory"))
            parsed = _parse_profile_title(_s(row.get("title")))
            out.append(
                Candidate(
                    public_id=public_id,
                    first_name=first or parsed["first_name"],
                    last_name=last or parsed["last_name"],
                    headline=parsed["headline"],
                    title=title or parsed["title"],
                    company=company or parsed["company"],
                    location=_location_text(person.get("location")),
                    avatar_url=_s(row.get("image")),
                    provider=self.name,
                )
            )
        return out


def _exa_person(entities: Any) -> dict[str, Any]:
    for entity in entities or []:
        if not isinstance(entity, dict):
            continue
        if entity.get("type") not in (None, "person"):
            continue
        props = entity.get("properties")
        return props if isinstance(props, dict) else entity
    return {}


def _current_job(history: Any) -> tuple[str, str]:
    """Title and company of the first (most recent) role."""
    for job in history or []:
        if not isinstance(job, dict):
            continue
        company = job.get("company")
        name = _s(company.get("name")) if isinstance(company, dict) else _s(company)
        return _s(job.get("title")), name
    return "", ""


def _location_text(location: Any) -> str:
    if isinstance(location, str):
        return location.strip()
    if isinstance(location, dict):
        return ", ".join(
            _s(location.get(k)) for k in ("city", "region", "country") if _s(location.get(k))
        ) or _s(location.get("name"))
    return ""


# ── People Data Labs ─────────────────────────────────────────────────────────

_PDL_LEVELS = {
    "owner": "owner",
    "founder": "owner",
    "c_suite": "cxo",
    "partner": "partner",
    "vp": "vp",
    "head": "director",
    "director": "director",
    "manager": "manager",
    "senior": "senior",
    "entry": "entry",
}
_PDL_SIZES = [
    (1, 10, "1-10"),
    (11, 50, "11-50"),
    (51, 200, "51-200"),
    (201, 500, "201-500"),
    (501, 1000, "501-1000"),
    (1001, 5000, "1001-5000"),
    (5001, 10000, "5001-10000"),
    (10001, 10**9, "10001+"),
]


def _size_range(company_size: str) -> tuple[int, int] | None:
    match = re.fullmatch(r"\s*(\d+)\s*,\s*(\d*)\s*", company_size or "")
    if not match:
        return None
    low = int(match.group(1))
    high = int(match.group(2)) if match.group(2) else 10**9
    return (low, high) if high >= low else None


def _any_of(field_name: str, values: list[str], kind: str = "match_phrase") -> dict[str, Any]:
    return {
        "bool": {"should": [{kind: {field_name: v}} for v in values], "minimum_should_match": 1}
    }


def pdl_query(criteria: SearchCriteria) -> dict[str, Any]:
    """The Elasticsearch query for these criteria (PDL person schema)."""
    must: list[dict[str, Any]] = [{"exists": {"field": "linkedin_url"}}]
    if criteria.titles:
        must.append(_any_of("job_title", criteria.titles))
    if criteria.locations:
        # "Bengaluru, India" → match on the city part; location_name holds the full text.
        must.append(
            _any_of("location_name", [loc.split(",")[0] for loc in criteria.locations], "match")
        )
    if criteria.companies:
        must.append(_any_of("job_company_name", criteria.companies))
    if criteria.industries:
        must.append(_any_of("job_company_industry", criteria.industries, "match"))
    for keyword in criteria.keywords:
        must.append(
            {
                "bool": {
                    "should": [
                        {"match": {"skills": keyword}},
                        {"match": {"job_title": keyword}},
                        {"match": {"headline": keyword}},
                    ],
                    "minimum_should_match": 1,
                }
            }
        )
    levels = sorted({_PDL_LEVELS[s] for s in criteria.seniorities if s in _PDL_LEVELS})
    if levels:
        must.append({"terms": {"job_title_levels": levels}})
    size = _size_range(criteria.company_size)
    if size:
        buckets = [label for lo, hi, label in _PDL_SIZES if lo <= size[1] and hi >= size[0]]
        if buckets:
            must.append({"terms": {"job_company_size": buckets}})
    return {"bool": {"must": must}}


class PdlProvider(Provider):
    name = "pdl"
    URL = "https://api.peopledatalabs.com/v5/person/search"

    def api_key(self) -> str:
        return settings.pdl_api_key.get_secret_value()

    async def search(
        self, criteria: SearchCriteria, limit: int, client: httpx.AsyncClient
    ) -> list[Candidate]:
        response = await client.post(
            self.URL,
            headers={"X-Api-Key": self.api_key()},
            json={"query": pdl_query(criteria), "size": min(100, limit), "titlecase": True},
        )
        if response.status_code == 404:  # PDL's "no records matched"
            return []
        self._raise_for(response, "People Data Labs")
        out = []
        for row in response.json().get("data") or []:
            public_id = extract_public_id(_s(row.get("linkedin_url"))) or extract_public_id(
                _s(row.get("linkedin_username"))
            )
            if not public_id:
                continue
            first, last = _s(row.get("first_name")), _s(row.get("last_name"))
            if not first:
                first, last = _split_name(_s(row.get("full_name")))
            out.append(
                Candidate(
                    public_id=public_id,
                    first_name=first,
                    last_name=last,
                    headline=_s(row.get("headline")),
                    title=_s(row.get("job_title")),
                    company=_s(row.get("job_company_name")),
                    location=_s(row.get("location_name")),
                    provider=self.name,
                )
            )
        return out


# ── Apollo ───────────────────────────────────────────────────────────────────


# httpx's own query-parameter type (lists are invariant, so it must match).
_Param = tuple[str, str | int | float | bool | None]


class ApolloProvider(Provider):
    name = "apollo"
    SEARCH_URL = "https://api.apollo.io/api/v1/mixed_people/api_search"
    ENRICH_URL = "https://api.apollo.io/api/v1/people/bulk_match"
    _ENRICH_BATCH = 10  # Apollo's per-call maximum

    def api_key(self) -> str:
        return settings.apollo_api_key.get_secret_value()

    def _params(self, criteria: SearchCriteria, limit: int) -> list[_Param]:
        params: list[_Param] = [("page", 1), ("per_page", min(100, limit))]
        params += [("person_titles[]", t) for t in criteria.titles]
        params += [("person_locations[]", loc) for loc in criteria.locations]
        params += [("person_seniorities[]", s) for s in criteria.seniorities]
        if _size_range(criteria.company_size):
            params.append(
                ("organization_num_employees_ranges[]", criteria.company_size.replace(" ", ""))
            )
        keywords = " ".join(criteria.keywords + criteria.industries + criteria.companies).strip()
        if keywords:
            params.append(("q_keywords", keywords[:200]))
        return params

    async def search(
        self, criteria: SearchCriteria, limit: int, client: httpx.AsyncClient
    ) -> list[Candidate]:
        headers = {"x-api-key": self.api_key(), "Cache-Control": "no-cache"}
        found = await client.post(
            self.SEARCH_URL,
            headers=headers,
            params=self._params(criteria, limit),
        )
        self._raise_for(found, "Apollo")
        ids = [p["id"] for p in found.json().get("people") or [] if p.get("id")][:limit]

        # Search results carry no LinkedIn URL; enrichment does (1 credit each).
        out = []
        for start in range(0, len(ids), self._ENRICH_BATCH):
            batch = ids[start : start + self._ENRICH_BATCH]
            enriched = await client.post(
                self.ENRICH_URL, headers=headers, json={"details": [{"id": i} for i in batch]}
            )
            self._raise_for(enriched, "Apollo")
            for person in enriched.json().get("matches") or []:
                if not isinstance(person, dict):
                    continue
                public_id = extract_public_id(_s(person.get("linkedin_url")))
                if not public_id:
                    continue
                org = person.get("organization") or {}
                out.append(
                    Candidate(
                        public_id=public_id,
                        first_name=_s(person.get("first_name")),
                        last_name=_s(person.get("last_name")),
                        headline=_s(person.get("headline")),
                        title=_s(person.get("title")),
                        company=_s(org.get("name")) if isinstance(org, dict) else "",
                        location=", ".join(
                            _s(person.get(k))
                            for k in ("city", "state", "country")
                            if _s(person.get(k))
                        ),
                        avatar_url=_s(person.get("photo_url")),
                        provider=self.name,
                    )
                )
        return out


# ── Brave Search X-ray ───────────────────────────────────────────────────────


def _quoted_any(values: list[str]) -> str:
    cleaned = [v.replace('"', "").strip() for v in values if v.strip()]
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return f'"{cleaned[0]}"'
    return "(" + " OR ".join(f'"{v}"' for v in cleaned) + ")"


def xray_query(criteria: SearchCriteria) -> str:
    parts = ["site:linkedin.com/in"]
    for group in (
        criteria.titles[:4],
        [loc.split(",")[0] for loc in criteria.locations[:3]],
        criteria.companies[:4],
        criteria.industries[:3],
    ):
        clause = _quoted_any(group)
        if clause:
            parts.append(clause)
    parts += [f'"{k.replace(chr(34), "")}"' for k in criteria.keywords[:4] if k.strip()]
    return " ".join(parts)


# Profile page titles separate parts with "-", "|" or an en dash (U+2013).
_SEPARATORS = re.escape("-|" + chr(0x2013))
_TITLE_SUFFIX = re.compile(rf"\s*[{_SEPARATORS}]\s*LinkedIn\s*$", re.IGNORECASE)
_TITLE_SEPARATOR = re.compile(rf"\s+[{_SEPARATORS}]\s+")


def _parse_profile_title(text: str) -> dict[str, str]:
    """Splits "Priya Sharma - Head of HR - Acme | LinkedIn" into its parts."""
    text = _TITLE_SUFFIX.sub("", text or "").strip()
    pieces = [p.strip() for p in _TITLE_SEPARATOR.split(text) if p.strip()]
    first, last = _split_name(pieces[0]) if pieces else ("", "")
    title = pieces[1] if len(pieces) > 1 else ""
    company = pieces[2] if len(pieces) > 2 else ""
    if not company and " at " in title:
        title, company = (s.strip() for s in title.split(" at ", 1))
    return {
        "first_name": first,
        "last_name": last,
        "title": title,
        "company": company,
        "headline": " - ".join(pieces[1:]),
    }


class BraveProvider(Provider):
    name = "brave"
    URL = "https://api.search.brave.com/res/v1/web/search"
    _PAGE = 20

    def api_key(self) -> str:
        return settings.brave_search_api_key.get_secret_value()

    async def search(
        self, criteria: SearchCriteria, limit: int, client: httpx.AsyncClient
    ) -> list[Candidate]:
        query = xray_query(criteria)
        out: list[Candidate] = []
        seen: set[str] = set()
        for offset in range(3):  # at most 60 results: plenty for 25 people
            response = await client.get(
                self.URL,
                headers={"X-Subscription-Token": self.api_key(), "Accept": "application/json"},
                params={"q": query, "count": self._PAGE, "offset": offset},
            )
            self._raise_for(response, "Brave Search")
            rows = (response.json().get("web") or {}).get("results") or []
            for row in rows:
                public_id = extract_public_id(_s(row.get("url")))
                if not public_id or public_id in seen:
                    continue
                seen.add(public_id)
                parsed = _parse_profile_title(_s(row.get("title")))
                location = ""
                snippet = _s(row.get("description"))
                loc_match = re.search(r"Location:\s*([^·\n]+)", snippet)
                if loc_match:
                    location = loc_match.group(1).strip()[:120]
                out.append(
                    Candidate(
                        public_id=public_id,
                        first_name=parsed["first_name"],
                        last_name=parsed["last_name"],
                        headline=parsed["headline"],
                        title=parsed["title"],
                        company=parsed["company"],
                        location=location,
                        provider=self.name,
                    )
                )
            if len(out) >= limit or len(rows) < self._PAGE:
                break
        return out


PROVIDERS: dict[str, Provider] = {
    p.name: p for p in (ExaProvider(), PdlProvider(), ApolloProvider(), BraveProvider())
}


def configured() -> list[Provider]:
    """Providers in the configured order that have a key."""
    names = [n.strip().lower() for n in settings.lead_search_providers.split(",")]
    return [PROVIDERS[n] for n in names if n in PROVIDERS and PROVIDERS[n].api_key()]


def new_client(transport: httpx.AsyncBaseTransport | None = None) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=_TIMEOUT, transport=transport)
