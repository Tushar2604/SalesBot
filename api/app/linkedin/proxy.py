"""Proxy resolution for an account's egress identity.

One account, one proxy, for life. Assignment happens at connect time and the
`proxies.assigned_account_id` unique constraint keeps two accounts off one IP.

**Running without a proxy is supported and unsafe.** All of a workspace's
accounts then share the server's IP, which is the clustering signal LinkedIn
looks for, and on a cloud host it is a datacenter IP with poor reputation. It
exists so the product can be tested end-to-end before a provider is contracted;
`direct_connection_warning()` is the text the UI must show whenever it applies.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

import httpx

from app.core.crypto import decrypt_str
from app.models.linkedin import Proxy


@dataclass(slots=True)
class ResolvedProxy:
    """A usable proxy URL plus safe-to-display metadata."""

    url: str
    label: str
    country: str
    public_url: str

    @property
    def is_direct(self) -> bool:
        return False


def resolve(proxy: Proxy | None) -> ResolvedProxy | None:
    """Builds the httpx proxy URL, decrypting credentials at the last moment.

    Returns None for a direct connection, which every caller must treat as the
    degraded path rather than the default.
    """
    if proxy is None:
        return None

    userinfo = ""
    if proxy.username_ciphertext:
        username = quote(decrypt_str(proxy.username_ciphertext), safe="")
        password = (
            quote(decrypt_str(proxy.password_ciphertext), safe="")
            if proxy.password_ciphertext
            else ""
        )
        # Providers encode the sticky-session token into the username, so it is
        # appended here rather than sent as a separate parameter.
        if proxy.sticky_session_id:
            username = f"{username}-session-{quote(proxy.sticky_session_id, safe='')}"
        userinfo = f"{username}:{password}@" if password else f"{username}@"

    return ResolvedProxy(
        url=f"{proxy.scheme}://{userinfo}{proxy.host}:{proxy.port}",
        label=proxy.label or proxy.host,
        country=proxy.country,
        public_url=proxy.public_url,
    )


@dataclass(slots=True)
class ExitProbe:
    """Where a proxy really comes out on the internet, as LinkedIn will see it."""

    ok: bool
    ip: str = ""
    country: str = ""
    city: str = ""
    org: str = ""
    error: str = ""

    @property
    def looks_like_datacenter(self) -> bool:
        org = self.org.lower()
        return any(marker in org for marker in _DATACENTER_MARKERS)


# Networks that host servers, not homes. LinkedIn scores these IPs poorly: a
# person does not browse from a data centre.
_DATACENTER_MARKERS = (
    "amazon", "aws", "google", "microsoft", "azure", "digitalocean", "ovh", "hetzner",
    "linode", "akamai", "vultr", "choopa", "oracle", "alibaba", "tencent", "contabo",
    "leaseweb", "m247", "datacamp", "cloudflare", "hosting", "server", "data center",
    "datacenter",
)
_PROBE_URL = "https://ipinfo.io/json"


async def probe_exit(url: str) -> ExitProbe:
    """Connects through the proxy once and asks where the request came from.

    One ordinary HTTPS request to an IP-information service; LinkedIn is not
    contacted. Never raises: a failure is reported in the result.
    """
    try:
        async with httpx.AsyncClient(proxy=url, timeout=12.0) as client:
            response = await client.get(_PROBE_URL)
            response.raise_for_status()
            data = response.json()
    except Exception as exc:  # any failure means "cannot use this proxy"
        return ExitProbe(ok=False, error=type(exc).__name__)
    return ExitProbe(
        ok=True,
        ip=str(data.get("ip") or "")[:64],
        country=str(data.get("country") or "").upper()[:2],
        city=str(data.get("city") or "")[:80],
        org=str(data.get("org") or "")[:200],
    )


def direct_connection_warning() -> str:
    """The warning the UI shows for any account running without a proxy."""
    return (
        "This account is running over this server's IP address. Every account "
        "here shares it, which is exactly the pattern LinkedIn scores as "
        "automation, and hosted IPs carry poor reputation. Assign a residential "
        "proxy in the same country as the profile before real outreach."
    )
