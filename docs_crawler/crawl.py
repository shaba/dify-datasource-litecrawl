from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from .http import Fetch, default_fetch
from .links import canonical_url, extract_links, in_scope

ExtractFn = Callable[[str, str], dict[str, Any]]


@dataclass
class Page:
    source_url: str
    title: str
    description: str
    content: str


def _default_prefix(start_url: str) -> str:
    path = urlparse(start_url).path or "/"
    return path if path.endswith("/") else path.rsplit("/", 1)[0] + "/"


def crawl(
    start_url: str,
    *,
    extract: ExtractFn,
    fetch: Fetch = default_fetch,
    path_prefix: str | None = None,
    include: list[str] | None = None,
    exclude: list[str] | None = None,
    max_pages: int = 50,
    max_depth: int = 5,
    timeout: int = 20,
) -> list[Page]:
    """BFS-crawl internal links from start_url within host + path_prefix.

    Fetches each HTML page, extracts main content via `extract`, follows in-scope
    links up to max_depth, stops at max_pages. Non-HTML and out-of-scope links are
    skipped; pages with empty extracted content are not emitted.
    """
    host = urlparse(start_url).netloc
    if path_prefix is None:
        path_prefix = _default_prefix(start_url)

    seen: set[str] = {canonical_url(start_url)}
    pages: list[Page] = []
    queue: deque[tuple[str, int]] = deque([(start_url, 0)])

    while queue and len(pages) < max_pages:
        url, depth = queue.popleft()
        try:
            status, content_type, html = fetch(url, timeout)
        except Exception:  # noqa: BLE001 - skip unreachable pages, keep crawling
            continue
        if not (200 <= status < 300) or "html" not in content_type.lower():
            continue

        data = extract(html, url)
        if str(data.get("content") or "").strip():
            pages.append(
                Page(
                    source_url=url,
                    title=str(data.get("title") or ""),
                    description=str(data.get("description") or ""),
                    content=str(data["content"]),
                )
            )

        if depth < max_depth:
            for link in sorted(extract_links(html, url)):
                key = canonical_url(link)
                if key not in seen and in_scope(
                    link, host, path_prefix, include=include, exclude=exclude
                ):
                    seen.add(key)
                    queue.append((link, depth + 1))

    return pages


def extract_urls(
    urls: list[str],
    *,
    extract: ExtractFn,
    fetch: Fetch = default_fetch,
    max_pages: int = 50,
    timeout: int = 20,
) -> list[Page]:
    """Fetch + extract an explicit list of URLs (e.g. from a sitemap), no crawling."""
    pages: list[Page] = []
    for url in urls:
        if len(pages) >= max_pages:
            break
        try:
            status, content_type, html = fetch(url, timeout)
        except Exception:  # noqa: BLE001
            continue
        if not (200 <= status < 300) or "html" not in content_type.lower():
            continue
        data = extract(html, url)
        if str(data.get("content") or "").strip():
            pages.append(
                Page(
                    source_url=url,
                    title=str(data.get("title") or ""),
                    description=str(data.get("description") or ""),
                    content=str(data["content"]),
                )
            )
    return pages
