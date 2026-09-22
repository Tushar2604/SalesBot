"""HTTP layer: routers only. No business logic below this package."""

# Single source of truth for the mounted API prefix. The refresh cookie's Path
# is derived from it: a cookie scoped to "/auth" would never be sent to
# "/api/v1/auth/refresh", silently breaking session persistence.
API_V1_PREFIX = "/api/v1"
