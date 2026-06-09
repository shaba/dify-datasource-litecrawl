from __future__ import annotations

import re
from fnmatch import fnmatch
from html import unescape
from urllib.parse import urljoin, urlparse, urlunparse

# Match both quoted (href="...") and unquoted (href=...) attribute forms.
_HREF = re.compile(r"""href=(?:["']([^"'#]+)|([^"'\s>#]+))""", re.IGNORECASE)
_ASSET = re.compile(r"\.(png|jpe?g|gif|svg|css|js|ico|woff2?|ttf|zip|tar|gz|pdf|xml|json)$", re.I)


def extract_links(html: str, base_url: str) -> set[str]:
    out: set[str] = set()
    for quoted, unquoted in _HREF.findall(html or ""):
        href = unescape(quoted or unquoted).strip()  # decode &amp; etc., trim padding whitespace
        if not href:
            continue
        url = urljoin(base_url, href).split("#")[0]
        if url.startswith(("http://", "https://")):
            out.add(url)
    return out


def canonical_url(url: str) -> str:
    """Normalize a URL for dedup: drop fragment, normalize empty/'/' path and
    a single trailing slash, lowercase scheme/host.

    Keeps query strings (they can be semantically significant) but collapses
    ``/docs/page`` and ``/docs/page/`` to one key so the same logical page is not
    fetched twice. The root path ('' or '/') is preserved as '/'.
    """
    p = urlparse(url)
    path = p.path or "/"
    if len(path) > 1:
        path = path.rstrip("/") or "/"
    return urlunparse((p.scheme.lower(), p.netloc.lower(), path, p.params, p.query, ""))


def path_matches(path: str, patterns: list[str]) -> bool:
    """Glob-match a URL path against patterns (firecrawl-style, e.g. 'blog/*')."""
    rel = path.lstrip("/")
    for raw in patterns:
        pat = raw.strip().lstrip("/")
        if not pat:
            continue
        if fnmatch(rel, pat) or fnmatch(rel, pat + "/*") or fnmatch(rel, pat.rstrip("/") + "*"):
            return True
    return False


def in_scope(
    url: str,
    host: str,
    path_prefix: str | None,
    *,
    include: list[str] | None = None,
    exclude: list[str] | None = None,
) -> bool:
    parsed = urlparse(url)
    if parsed.netloc != host:
        return False
    if path_prefix and not parsed.path.startswith(path_prefix):
        return False
    if _ASSET.search(parsed.path):
        return False
    if exclude and path_matches(parsed.path, exclude):
        return False
    if include and not path_matches(parsed.path, include):
        return False
    return True


_LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.IGNORECASE)


def parse_sitemap(xml: str) -> list[str]:
    """Return <loc> URLs from a sitemap or sitemap-index XML."""
    return [u.strip() for u in _LOC.findall(xml or "") if u.strip()]
