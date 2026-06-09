from __future__ import annotations

import re
from urllib.parse import urlparse

from .http import Fetch, default_fetch

_ROBOTS_SITEMAP = re.compile(r"(?im)^\s*sitemap:\s*(\S+)\s*$")

# Common documentation roots to probe when only a bare domain is given.
DOC_CANDIDATES = ("/docs/", "/doc/", "/documentation/", "/en/docs/", "/manual/", "/wiki/")


def find_docs_root(base_url: str, *, fetch: Fetch = default_fetch, timeout: int = 20) -> str:
    """Resolve the documentation root URL.

    If base_url already points at a specific path (not the bare domain), use it as-is.
    Otherwise probe common documentation paths and return the first that responds with
    a 2xx HTML page. Falls back to base_url if nothing matches.
    """
    parsed = urlparse(base_url)
    if (parsed.path or "/") not in ("", "/"):
        return base_url

    root = f"{parsed.scheme}://{parsed.netloc}"
    for candidate in DOC_CANDIDATES:
        url = root + candidate
        try:
            status, content_type, _ = fetch(url, timeout)
        except Exception:  # noqa: BLE001 - probing, ignore unreachable candidates
            continue
        if 200 <= status < 300 and "html" in content_type.lower():
            return url
    return base_url


def _looks_like_sitemap(content_type: str, body: str) -> bool:
    """Accept a response as a sitemap if the type says XML or the body sniffs as
    XML (servers often serve sitemaps as text/plain)."""
    if "xml" in content_type.lower():
        return True
    head = body.lstrip()[:512].lower()
    return head.startswith("<?xml") or "<urlset" in head or "<sitemapindex" in head


def _fetch_sitemap(url: str, fetch: Fetch, timeout: int) -> str | None:
    try:
        status, content_type, text = fetch(url, timeout)
    except Exception:  # noqa: BLE001
        return None
    if not (200 <= status < 300) or not _looks_like_sitemap(content_type, text):
        return None
    return text


def _robots_sitemaps(root: str, fetch: Fetch, timeout: int) -> list[str]:
    """Sitemap: URLs advertised in robots.txt (the canonical, spec'd location)."""
    try:
        status, _ct, text = fetch(root + "/robots.txt", timeout)
    except Exception:  # noqa: BLE001
        return []
    if not (200 <= status < 300):
        return []
    return [m.strip() for m in _ROBOTS_SITEMAP.findall(text or "")]


def find_sitemap_urls(base_url: str, *, fetch: Fetch = default_fetch, timeout: int = 20,
                      max_sitemaps: int = 10) -> list[str]:
    """Return page URLs from the site's sitemap, expanding one level of sitemap-index.

    Sitemaps are located via robots.txt ``Sitemap:`` directives (the canonical,
    spec'd location) and the conventional ``<root>/sitemap.xml`` fallback. Empty
    list if there is no sitemap (caller falls back to link crawling).
    Note: gzipped sitemaps (``sitemap.xml.gz``) are not decompressed.
    """
    from .links import parse_sitemap

    parsed = urlparse(base_url)
    root = f"{parsed.scheme}://{parsed.netloc}"

    # Prefer sitemaps advertised in robots.txt; always also try the conventional path.
    candidates: list[str] = []
    for u in [*_robots_sitemaps(root, fetch, timeout), root + "/sitemap.xml"]:
        if u not in candidates:
            candidates.append(u)

    pages: list[str] = []
    fetched_sub = 0
    for entry in candidates:
        text = _fetch_sitemap(entry, fetch, timeout)
        if text is None:
            continue
        locs = parse_sitemap(text)
        sub = [u for u in locs if u.lower().endswith(".xml")]
        if sub:
            for sm in sub:
                if fetched_sub >= max_sitemaps:
                    break
                fetched_sub += 1
                t2 = _fetch_sitemap(sm, fetch, timeout)
                if t2 is not None:
                    pages.extend(u for u in parse_sitemap(t2) if not u.lower().endswith(".xml"))
        else:
            pages.extend(u for u in locs if not u.lower().endswith(".xml"))
        if pages:
            break  # first sitemap source that yields pages wins
    return pages
