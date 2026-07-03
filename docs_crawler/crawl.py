from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from .http import Fetch, default_fetch
from .links import canonical_url, extract_links, in_scope

ExtractFn = Callable[[str, str], dict[str, Any]]

# Wall-clock budget for a single crawl request. The plugin runs inside one Dify
# request capped at MAX_REQUEST_TIMEOUT (300 s, see main.py); we stop fetching
# well before that so a partial-but-completed result is always returned instead
# of the whole request being killed mid-stream. Overridable per call for tests.
CRAWL_TIME_BUDGET = 240.0


@dataclass
class Page:
    source_url: str
    title: str
    description: str
    content: str


@dataclass
class CrawlProgress:
    """A snapshot emitted while streaming a crawl. `web_info` is the cumulative
    list of pages collected so far (bounded by max_pages + time budget)."""

    web_info: list[Page]
    completed: int
    total: int
    status: str  # "processing" | "completed"
    capped: bool  # stopped before the source was exhausted
    reason: str  # "" | "max_pages" | "time_budget"


def default_path_prefix(start_url: str) -> str:
    """Scope prefix for a start URL: its path if it ends in '/', else the parent
    directory (e.g. /docs/intro -> /docs/). Shared by the BFS crawl and the
    sitemap pre-filter so both strategies scope identically.
    """
    path = urlparse(start_url).path or "/"
    return path if path.endswith("/") else path.rsplit("/", 1)[0] + "/"


# Backwards-compatible private alias.
_default_prefix = default_path_prefix


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
) -> Iterator[Page]:
    """BFS-crawl internal links from start_url within host + path_prefix.

    A lazy generator: fetches each HTML page, extracts main content via
    `extract`, follows in-scope links up to max_depth, and yields at most
    max_pages Page objects. Non-HTML and out-of-scope links are skipped; pages
    with empty extracted content are not emitted. Because it is lazy, a consumer
    can abandon it (e.g. on a time budget) to stop fetching immediately.
    """
    host = urlparse(start_url).netloc
    if path_prefix is None:
        path_prefix = _default_prefix(start_url)

    seen: set[str] = {canonical_url(start_url)}
    emitted = 0
    queue: deque[tuple[str, int]] = deque([(start_url, 0)])

    while queue and emitted < max_pages:
        url, depth = queue.popleft()
        try:
            status, content_type, html = fetch(url, timeout)
        except Exception:  # noqa: BLE001 - skip unreachable pages, keep crawling
            continue
        if not (200 <= status < 300) or "html" not in content_type.lower():
            continue

        data = extract(html, url)
        if str(data.get("content") or "").strip():
            yield Page(
                source_url=url,
                title=str(data.get("title") or ""),
                description=str(data.get("description") or ""),
                content=str(data["content"]),
            )
            emitted += 1

        if depth < max_depth:
            for link in sorted(extract_links(html, url)):
                key = canonical_url(link)
                if key not in seen and in_scope(
                    link, host, path_prefix, include=include, exclude=exclude
                ):
                    seen.add(key)
                    queue.append((link, depth + 1))


def _fetch_page(
    url: str,
    extract: ExtractFn,
    fetch: Fetch,
    timeout: int,
    delay: float = 0.0,
) -> Page | None:
    """Fetch one URL and extract a Page, or None if unreachable / non-HTML /
    empty. Never raises -- a failed page must not abort the crawl. Runs in a
    worker thread under the parallel path, so it owns the optional politeness
    delay applied before the request."""
    if delay:
        time.sleep(delay)
    try:
        status, content_type, html = fetch(url, timeout)
    except Exception:  # noqa: BLE001
        return None
    if not (200 <= status < 300) or "html" not in content_type.lower():
        return None
    data = extract(html, url)
    if not str(data.get("content") or "").strip():
        return None
    return Page(
        source_url=url,
        title=str(data.get("title") or ""),
        description=str(data.get("description") or ""),
        content=str(data["content"]),
    )


def extract_urls(
    urls: Iterable[str],
    *,
    extract: ExtractFn,
    fetch: Fetch = default_fetch,
    max_pages: int = 50,
    timeout: int = 20,
    max_concurrency: int = 1,
    request_delay_ms: int = 0,
) -> Iterator[Page]:
    """Fetch + extract an explicit list of URLs (e.g. from a sitemap), no
    crawling. A lazy generator yielding at most max_pages pages, so callers only
    fetch as many URLs as they consume.

    With ``max_concurrency > 1`` pages are fetched by a bounded thread pool (a
    sliding window of at most ``max_concurrency`` in-flight requests, so the
    server is never hit with more than that at once). Ordering becomes
    unordered. ``max_concurrency <= 1`` keeps the original sequential behaviour.
    ``request_delay_ms`` optionally sleeps before each request for politeness.
    """
    delay = max(0, int(request_delay_ms)) / 1000.0
    if max_concurrency and max_concurrency > 1:
        yield from _extract_urls_parallel(
            urls,
            extract=extract,
            fetch=fetch,
            max_pages=max_pages,
            timeout=timeout,
            max_concurrency=int(max_concurrency),
            delay=delay,
        )
        return

    emitted = 0
    for url in urls:
        if emitted >= max_pages:
            break
        page = _fetch_page(url, extract, fetch, timeout, delay)
        if page is not None:
            yield page
            emitted += 1


def _extract_urls_parallel(
    urls: Iterable[str],
    *,
    extract: ExtractFn,
    fetch: Fetch,
    max_pages: int,
    timeout: int,
    max_concurrency: int,
    delay: float,
) -> Iterator[Page]:
    """Bounded-pool variant of extract_urls. Keeps a sliding window of at most
    ``max_concurrency`` in-flight fetches, yields pages as they complete, and
    stops submitting once ``max_pages`` pages have been emitted. Still lazy: if
    the consumer stops early (e.g. on the time budget) GeneratorExit closes the
    pool, which drains the in-flight fetches -- no new requests are launched."""
    url_iter = iter(urls)
    emitted = 0
    with ThreadPoolExecutor(max_workers=max_concurrency) as pool:
        inflight: set = set()

        def submit_next() -> bool:
            for u in url_iter:
                inflight.add(pool.submit(_fetch_page, u, extract, fetch, timeout, delay))
                return True
            return False

        # Prime the window: at most max_concurrency requests are ever in flight.
        for _ in range(max_concurrency):
            if not submit_next():
                break

        while inflight and emitted < max_pages:
            done, _ = wait(inflight, return_when=FIRST_COMPLETED)
            for fut in done:
                inflight.discard(fut)
                if emitted >= max_pages:
                    continue
                page = fut.result()  # _fetch_page swallows errors -> None
                if page is not None:
                    yield page
                    emitted += 1
                # Refill the window (per completed future) until we hit the cap.
                if emitted < max_pages:
                    submit_next()
        # Leaving `with` shuts the pool down (wait=True), draining any remaining
        # in-flight fetches on both normal completion and early GeneratorExit.


def stream_pages(
    page_iter: Iterable[Page],
    *,
    source_total: int | None,
    max_pages: int,
    now: Callable[[], float] = time.monotonic,
    deadline: float | None = None,
    progress_every_pages: int = 25,
    progress_every_seconds: float = 5.0,
) -> Iterator[CrawlProgress]:
    """Lazily consume a Page iterator, emitting periodic ``processing`` progress
    snapshots and a final ``completed`` snapshot.

    Stops early when the wall-clock ``deadline`` (measured via ``now``) passes.
    Because ``page_iter`` is lazy, breaking out of the loop stops the underlying
    fetch loop -- no further pages are fetched, and pages are never materialised
    beyond what has been collected.

    ``source_total`` is the size of the source when known (e.g. len(sitemap)) so
    a capped crawl can honestly report "took N of M"; pass ``None`` when the
    source size is unbounded/unknown (BFS crawl).

    Time and clock are injectable (``now``/``deadline``) so tests stay
    deterministic without sleeping.
    """
    pages: list[Page] = []
    last_n = 0
    last_t = now()
    truncated = False

    # iter() + explicit close so that when we stop early on the deadline the
    # underlying generator's cleanup runs promptly -- for the parallel fetch
    # path this shuts down the thread pool (draining in-flight requests) before
    # we emit the final `completed`.
    src = iter(page_iter)
    try:
        for page in src:
            pages.append(page)
            n = len(pages)
            t = now()
            if (n - last_n) >= progress_every_pages or (t - last_t) >= progress_every_seconds:
                last_n, last_t = n, t
                yield CrawlProgress(
                    web_info=pages,
                    completed=n,
                    total=max(source_total or 0, n),
                    status="processing",
                    capped=False,
                    reason="",
                )
            if deadline is not None and now() >= deadline:
                truncated = True
                break
    finally:
        close = getattr(src, "close", None)
        if callable(close):
            close()

    n = len(pages)
    if truncated:
        capped, reason = True, "time_budget"
    elif n >= max_pages and source_total is not None and source_total > max_pages:
        # The generator hit its own max_pages cap while the source still had more.
        capped, reason = True, "max_pages"
    else:
        # Source exhausted (whether below the cap or exactly at a bounded source).
        capped, reason = False, ""

    total = source_total if (capped and source_total is not None) else n
    yield CrawlProgress(
        web_info=pages,
        completed=n,
        total=total,
        status="completed",
        capped=capped,
        reason=reason,
    )
