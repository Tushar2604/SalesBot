"""Webhook signing, URL safety and the HTTP send.

Signature
    Every request carries

        X-SalesRobo-Signature: t=<unix seconds>,v1=<hex HMAC-SHA256>

    where the HMAC is over f"{t}.{raw request body}" with the endpoint's
    secret. Receivers recompute it, compare in constant time, and reject a
    `t` more than 5 minutes old (replay protection). `verify()` below is the
    reference implementation.

URL safety (SSRF)
    A webhook URL makes *our server* send a request, so a URL pointing at
    localhost, a private network or a cloud metadata address would let a user
    probe our internal services. URLs are checked when saved and again right
    before every send (DNS can change in between), redirects are not
    followed, and only http(s) on standard-looking hosts is accepted.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import secrets
import socket
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.config import settings

SECRET_PREFIX = "whsec_"  # noqa: S105 - a label, not a secret
SIGNATURE_HEADER = "X-SalesRobo-Signature"
TOLERANCE_SECONDS = 300
_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
_MAX_RESPONSE_CHARS = 1000


class UnsafeUrl(ValueError):
    pass


def new_secret() -> str:
    return SECRET_PREFIX + secrets.token_urlsafe(32)


def body_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()


def sign(secret: str, body: bytes, timestamp: int | None = None) -> str:
    t = int(time.time()) if timestamp is None else timestamp
    mac = hmac.new(secret.encode(), f"{t}.".encode() + body, hashlib.sha256).hexdigest()
    return f"t={t},v1={mac}"


def verify(secret: str, body: bytes, header: str, *, now: int | None = None) -> bool:
    """What a receiver does. Also used by our tests."""
    try:
        parts = dict(item.split("=", 1) for item in header.split(","))
        t = int(parts["t"])
        given = parts["v1"]
    except (KeyError, ValueError):
        return False
    if abs((now or int(time.time())) - t) > TOLERANCE_SECONDS:
        return False
    expected = hmac.new(secret.encode(), f"{t}.".encode() + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, given)


def _ip_is_private(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def check_url(url: str) -> str:
    """The URL, normalised, or UnsafeUrl explaining what's wrong with it."""
    url = url.strip()
    parts = urlsplit(url)
    allow_private = settings.allow_private_webhook_urls
    if parts.scheme not in ("https", "http"):
        raise UnsafeUrl("the URL must start with https://")
    if parts.scheme == "http" and not allow_private:
        raise UnsafeUrl("use an https:// URL; plain http would send your data unencrypted")
    if not parts.hostname:
        raise UnsafeUrl("the URL has no host name")
    if parts.username or parts.password:
        raise UnsafeUrl("put credentials in the receiver's checks, not in the URL")
    if len(url) > 2000:
        raise UnsafeUrl("the URL is too long")
    if allow_private:
        return url
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise UnsafeUrl(f"the host {parts.hostname} could not be found") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if _ip_is_private(ip):
            raise UnsafeUrl("the URL points at a private or internal network address")
    return url


@dataclass(slots=True)
class SendResult:
    ok: bool
    status: int | None
    body: str
    error: str
    duration_ms: int


def send(
    url: str,
    secret: str,
    payload: dict[str, Any],
    *,
    delivery_id: str,
    attempt: int,
    transport: httpx.BaseTransport | None = None,
) -> SendResult:
    """POSTs one event. Never raises: every outcome becomes a SendResult."""
    started = time.monotonic()

    def done(ok: bool, status: int | None, body: str, error: str) -> SendResult:
        return SendResult(ok, status, body, error, int((time.monotonic() - started) * 1000))

    try:
        check_url(url)
    except UnsafeUrl as exc:
        return done(False, None, "", f"blocked: {exc}")

    body = body_bytes(payload)
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "SalesRobo-Webhooks/1.0",
        SIGNATURE_HEADER: sign(secret, body),
        "X-SalesRobo-Event": str(payload.get("type", "")),
        "X-SalesRobo-Event-Id": str(payload.get("id", "")),
        "X-SalesRobo-Delivery": delivery_id,
        "X-SalesRobo-Attempt": str(attempt),
    }
    try:
        with httpx.Client(timeout=_TIMEOUT, follow_redirects=False, transport=transport) as client:
            response = client.post(url, content=body, headers=headers)
    except httpx.TimeoutException:
        return done(False, None, "", "timed out after 10 seconds")
    except httpx.HTTPError as exc:
        return done(False, None, "", f"could not connect: {type(exc).__name__}")

    text = response.text[:_MAX_RESPONSE_CHARS]
    if 200 <= response.status_code < 300:
        return done(True, response.status_code, text, "")
    if 300 <= response.status_code < 400:
        return done(
            False, response.status_code, text, "redirects are not followed; use the final URL"
        )
    return done(False, response.status_code, text, f"receiver answered {response.status_code}")
