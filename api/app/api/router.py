"""Aggregates all versioned routers under /api/v1."""

from __future__ import annotations

from fastapi import APIRouter

from app.api import (
    API_V1_PREFIX,
    routes_analytics,
    routes_assistant,
    routes_auth,
    routes_campaigns,
    routes_content,
    routes_inbox,
    routes_leads,
    routes_linkedin,
    routes_linkedin_remote,
    routes_notifications,
    routes_workspaces,
)

api_router = APIRouter(prefix=API_V1_PREFIX)
api_router.include_router(routes_auth.router)
api_router.include_router(routes_workspaces.router)
api_router.include_router(routes_linkedin.router)
api_router.include_router(routes_leads.router)
api_router.include_router(routes_campaigns.router)
api_router.include_router(routes_inbox.router)
api_router.include_router(routes_assistant.router)
api_router.include_router(routes_notifications.router)
api_router.include_router(routes_analytics.router)
api_router.include_router(routes_content.router)
api_router.include_router(routes_linkedin_remote.router)
# Public: LinkedIn redirects the member's browser here after consent, with no
# session of ours attached. The signed `state` parameter is what authenticates it.
api_router.include_router(routes_linkedin.oauth_router)
# WebSocket: authenticates via a short-lived ticket (see routes_linkedin_remote.py)
# rather than the bearer-token dependency, since a browser WebSocket can't set
# an Authorization header.
api_router.include_router(routes_linkedin_remote.ws_router)
