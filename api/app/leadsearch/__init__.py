"""AI lead finder: "find me 15 heads of HR at fintechs in Bangalore" → people.

Why this never touches LinkedIn
-------------------------------
Running people searches through a member's LinkedIn session (the Voyager
search endpoint, or a browser on /search/results/people) is the fastest way
to get that account restricted: search volume, commercial-use limits and
pagination patterns are exactly what LinkedIn's abuse detection watches. So
the finder asks licensed people-data providers instead, and the only LinkedIn
traffic a found lead ever causes is the campaign's own paced profile visit,
later, one at a time, under the account's normal caps.

    criteria.py   the chat message → structured filters (one LLM call)
    providers.py  filters → people, from Exa / People Data Labs / Apollo /
                  Brave (search-engine "X-ray" over public profile pages)

The service (app/services/lead_search_service.py) runs the two, dedupes,
drops blocklisted and already-contacted people, and stores the results so
importing them never trusts data sent back by the browser.
"""
