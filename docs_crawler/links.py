from __future__ import annotations

import re
from fnmatch import fnmatch
from urllib.parse import urljoin, urlparse

_HREF = re.compile(r"""href=["']([^"'#]+)""", re.IGNORECASE)
_ASSET = re.compile(r"\.(png|jpe?g|gif|svg|css|js|ico|woff2?|ttf|zip|tar|gz|pdf|xml|json)$", re.I)


def extract_links(html: str, base_url: str) -> set[str]:
    out: set[str] = set()
    for href in _HREF.findall(html or ""):
        url = urljoin(base_url, href).split("#")[0]
        if url.startswith(("http://", "https://")):
            out.add(url)
    return out


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
