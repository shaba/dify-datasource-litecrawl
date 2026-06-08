from __future__ import annotations

from urllib.parse import urlparse

from .http import Fetch, default_fetch

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


def find_sitemap_urls(base_url: str, *, fetch: Fetch = default_fetch, timeout: int = 20,
                      max_sitemaps: int = 10) -> list[str]:
    """Return page URLs from <root>/sitemap.xml, expanding one level of sitemap-index.

    Empty list if there is no sitemap (caller falls back to link crawling).
    """
    from .links import parse_sitemap

    parsed = urlparse(base_url)
    root = f"{parsed.scheme}://{parsed.netloc}"
    try:
        status, content_type, text = fetch(root + "/sitemap.xml", timeout)
    except Exception:  # noqa: BLE001
        return []
    if not (200 <= status < 300) or "xml" not in content_type.lower():
        return []

    locs = parse_sitemap(text)
    pages: list[str] = []
    sub = [u for u in locs if u.lower().endswith(".xml")]
    if sub:
        for sm in sub[:max_sitemaps]:
            try:
                s2, c2, t2 = fetch(sm, timeout)
            except Exception:  # noqa: BLE001
                continue
            if 200 <= s2 < 300 and "xml" in c2.lower():
                pages.extend(u for u in parse_sitemap(t2) if not u.lower().endswith(".xml"))
    else:
        pages = [u for u in locs if not u.lower().endswith(".xml")]
    return pages
