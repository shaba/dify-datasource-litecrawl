from __future__ import annotations

import ipaddress
import socket
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

import requests


def _manifest_version() -> str:
    """Read the plugin version from manifest.yaml so the UA never drifts.

    Falls back to "0" if the manifest is missing (e.g. core package used
    standalone in tests). Avoids a YAML dependency: scans for the top-level
    ``version:`` line.
    """
    manifest = Path(__file__).resolve().parent.parent / "manifest.yaml"
    try:
        for line in manifest.read_text(encoding="utf-8").splitlines():
            if line.startswith("version:"):
                return line.split(":", 1)[1].strip().strip("\"'")
    except OSError:
        pass
    return "0"


DEFAULT_UA = f"litecrawl/{_manifest_version()} (+https://github.com/shaba/dify-datasource-litecrawl)"

# Fetch: (url, timeout) -> (status_code, content_type, text)
Fetch = Callable[[str, int], "tuple[int, str, str]"]

_MAX_REDIRECTS = 5


class SSRFError(ValueError):
    """Raised when a target resolves to a non-public address (SSRF guard)."""


def _is_public_ip(ip: str) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return not (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
    )


def _guard_url(url: str) -> None:
    """Block URLs whose host resolves to a private/loopback/link-local address.

    Raises SSRFError for non-http(s) schemes or any target that does not resolve
    to at least one public IP — closing the SSRF surface (cloud metadata at
    169.254.169.254, localhost, RFC1918, etc.) for user-supplied crawl URLs.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise SSRFError(f"unsupported URL scheme: {parsed.scheme!r}")
    host = parsed.hostname
    if not host:
        raise SSRFError("URL has no host")
    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
    except OSError as exc:
        raise SSRFError(f"cannot resolve host {host!r}: {exc}") from exc
    if not all(_is_public_ip(info[4][0]) for info in infos):
        raise SSRFError(f"host {host!r} resolves to a non-public address")


def default_fetch(url: str, timeout: int = 20, *, user_agent: str = DEFAULT_UA) -> tuple[int, str, str]:
    """Fetch a URL with an SSRF guard and manual, re-validated redirect following.

    Each hop (including redirect targets, which may point at a different host) is
    validated against the public-IP guard before the request is issued.

    Residual risk: the guard resolves the host with ``getaddrinfo`` and then
    ``requests.get`` resolves it again to connect, leaving a DNS-rebinding TOCTOU
    window (a hostname whose DNS flips between the two lookups could pass the
    guard yet connect to a private/metadata address). Closing this fully requires
    pinning the validated IP for the actual connection; the per-hop re-validation
    here raises the bar but is not airtight.
    """
    headers = {"User-Agent": user_agent}
    for _ in range(_MAX_REDIRECTS + 1):
        _guard_url(url)
        response = requests.get(url, timeout=timeout, headers=headers, allow_redirects=False)
        if response.is_redirect and "location" in response.headers:
            url = requests.compat.urljoin(url, response.headers["location"])
            continue
        return response.status_code, response.headers.get("content-type", ""), response.text
    raise SSRFError("too many redirects")
