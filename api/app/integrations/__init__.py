"""The integration layer: how other systems work with this one.

Inbound — REST API with API keys
    Every workspace endpoint of the API (leads, campaigns, inbox, accounts...)
    accepts `Authorization: Bearer sr_live_...` as well as a login token. A key
    belongs to one workspace, acts as the person who created it, and never has
    more power than they do (see app/deps.py and api_keys.py).

Outbound — webhooks
    Things that happen (a reply arrives, an invite is accepted, a lead is
    imported...) are written as events into an outbox in the same database
    transaction as the change itself, then POSTed to each subscribed URL with
    an HMAC signature and retries (events.py, webhooks.py,
    app/worker/tasks/webhooks.py).
"""
