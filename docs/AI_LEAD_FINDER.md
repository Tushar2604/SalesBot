# AI Lead Finder

Users describe who they want in plain language ("15 heads of HR at fintechs in
Bengaluru"). The lead finder returns the top matches and adds the chosen people
to a lead list, ready for a campaign. Page: `/leads/find`.

## Why it doesn't use LinkedIn search

The earlier version searched LinkedIn through a connected account, and LinkedIn
banned that account. LinkedIn watches for exactly that pattern: high search
volume, paging through results, and commercial-use limits on one member
session. The official APIs don't allow people search either: the Marketing API
has none, and Sales Navigator's SNAP program is partner-only.

**The rule:** searching never touches a LinkedIn account. The lead finder asks
licensed people-data providers from the server. A found lead only reaches
LinkedIn later, through the campaign's normal paced profile visit, one person
at a time and within the account's daily caps. The test
`test_the_lead_finder_never_uses_a_linkedin_account` enforces this.

## How it works

```
chat message ──► LLM (OpenAI → Gemini → Anthropic chain)  →  SearchCriteria
                  titles, locations, seniority, industry, size, keywords, count
SearchCriteria ─► providers in LEAD_SEARCH_PROVIDERS order, until enough people
                  exa → pdl → apollo → brave   (no key = skipped, error = next)
people ─────────► dedupe · drop already-contacted · drop blocklisted
                  · score + "why it matched" · top N (5–25, default 15)
                  → stored on lead_searches
"Add to leads" ─► LeadList (source ai_search) built from the stored rows,
                  never from data the browser sends back
```

Follow-up messages refine the same search ("only directors", "Pune instead").
Asking for "more" never shows the same person twice in a chat. Each workspace
gets `LEAD_SEARCH_DAILY_LIMIT` searches per day (default 50), because every
search spends provider credits.

## Providers

| Provider | How it finds people | Returns LinkedIn URL | Cost model | Best for |
|---|---|---|---|---|
| **Exa** (`EXA_API_KEY`) | Semantic search over 1B+ public profiles (`category: "people"`) | Yes | Per search | Fuzzy, natural-language asks |
| **People Data Labs** (`PDL_API_KEY`) | Licensed person dataset, Elasticsearch filters | Yes | 1 credit per person returned | The most precise filters (title, seniority, company size) |
| **Apollo** (`APOLLO_API_KEY`) | Search (free, but hides URLs and last names), then `people/bulk_match` | After enrichment | 1 credit per enriched person, plus a paid plan with API access | Teams already paying for Apollo |
| **Brave Search** (`BRAVE_SEARCH_API_KEY`) | "X-ray" search: `site:linkedin.com/in` over public pages | Yes | Per query, cheapest | Budget fallback; thinnest data |

Ruled out:

- **Proxycurl:** shut down in July 2025 after LinkedIn sued it.
- **Google Custom Search JSON API:** closed to new customers, and switched off on 2027-01-01.
- **Bing Search API:** retired in 2025.
- **Cookie-based "LinkedIn APIs"** (Unipile, Linked API) and self-hosted scrapers: they run through a member's session, which is the same ban risk as before.

**Recommended setup:** use Exa as the primary provider, add PDL for tight
filters, and keep Brave as a cheap fallback.

## Setup

1. Add at least one key to `.env`:
   ```
   LEAD_SEARCH_PROVIDERS=exa,pdl,apollo,brave
   EXA_API_KEY=...
   PDL_API_KEY=...
   ```
2. Apply the keys and the migration:
   ```
   docker compose up -d api worker
   docker exec salesrobo-api-1 alembic upgrade head
   ```
3. Open **Leads → Find with AI**.

## Compliance notes

- These providers license or index public data. You are still the controller
  of the personal data you import. Honour opt-outs by adding them to the
  blocklist, and keep outreach within LinkedIn's own limits (the campaign
  engine's caps).
- Avoid heavy provider use for EU/UK residents unless you have a documented
  lawful basis (legitimate interest assessment) for B2B outreach.

## Code

- `api/app/leadsearch/criteria.py`: turns a message into search criteria (with a keyword fallback when no AI provider is available)
- `api/app/leadsearch/providers.py`: the four provider clients
- `api/app/services/lead_search_service.py`: chat, ranking, filtering, import
- `api/app/api/routes_lead_search.py`: `/workspaces/{id}/lead-search/*`
- `web/app/(app)/leads/find/page.tsx`: the chat UI
- `api/tests/test_lead_search.py`
