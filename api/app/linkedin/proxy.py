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


def direct_connection_warning() -> str:
    """The warning the UI shows for any account running without a proxy."""
    return (
        "This account is running over this server's IP address. Every account "
        "here shares it, which is exactly the pattern LinkedIn scores as "
        "automation, and hosted IPs carry poor reputation. Assign a residential "
        "proxy in the same country as the profile before real outreach."
    )
