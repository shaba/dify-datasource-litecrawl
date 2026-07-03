"""Bounded parallel-fetch tests (L5).

Deterministic and network-free: `fetch` is injected. The concurrency-cap test
uses a tiny sleep only to force thread overlap so the cap can be observed; the
deadline test uses a fake clock advanced by fetch (no real waiting for the
budget).
"""

import threading

from docs_crawler.crawl import extract_urls, stream_pages


def ok_extract(html, url):
    return {"content": "body", "title": url, "description": ""}


def make_urls(n):
    return [f"https://h.example/p/{i}/" for i in range(n)]


class CountingFetch:
    """Thread-safe: counts calls; every URL returns a valid HTML page."""

    def __init__(self):
        self.lock = threading.Lock()
        self.calls = 0

    def __call__(self, url, timeout=20):
        with self.lock:
            self.calls += 1
        return 200, "text/html", "<p>x</p>"


def test_parallel_respects_max_pages():
    fetch = CountingFetch()
    urls = make_urls(5000)
    pages = list(
        extract_urls(urls, extract=ok_extract, fetch=fetch, max_pages=50, max_concurrency=8)
    )
    assert len(pages) == 50
    # Never fetches the whole sitemap; overshoot is bounded by the in-flight window.
    assert 50 <= fetch.calls <= 50 + 8


def test_parallel_small_set_is_complete():
    fetch = CountingFetch()
    urls = make_urls(4)
    pages = list(
        extract_urls(urls, extract=ok_extract, fetch=fetch, max_pages=50, max_concurrency=8)
    )
    got = {p.source_url for p in pages}
    assert got == set(urls)
    assert fetch.calls == 4


class ConcurrencyProbe:
    """Records the peak number of overlapping fetches. A short sleep forces the
    pool's workers to overlap so the cap is actually exercised."""

    def __init__(self):
        self.lock = threading.Lock()
        self.active = 0
        self.peak = 0

    def __call__(self, url, timeout=20):
        with self.lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
        try:
            # Brief overlap window (not a time-budget wait); keeps the test <100ms.
            import time

            time.sleep(0.01)
            return 200, "text/html", "<p>x</p>"
        finally:
            with self.lock:
                self.active -= 1


def test_parallel_never_exceeds_concurrency_cap():
    probe = ConcurrencyProbe()
    urls = make_urls(40)
    pages = list(
        extract_urls(urls, extract=ok_extract, fetch=probe, max_pages=40, max_concurrency=4)
    )
    assert len(pages) == 40
    assert probe.peak <= 4  # anti-DoS: cap is honoured
    assert probe.peak >= 2  # ...and fetches really did run in parallel


def test_parallel_sequential_when_concurrency_one():
    probe = ConcurrencyProbe()
    urls = make_urls(10)
    pages = list(
        extract_urls(urls, extract=ok_extract, fetch=probe, max_pages=10, max_concurrency=1)
    )
    assert len(pages) == 10
    assert probe.peak == 1  # max_concurrency<=1 keeps the sequential path


class Clock:
    def __init__(self):
        self.lock = threading.Lock()
        self.t = 0.0

    def advance(self, dt):
        with self.lock:
            self.t += dt

    def __call__(self):
        with self.lock:
            return self.t


class ClockFetch:
    """Advances a shared fake clock per call, modelling cost-per-page without
    real waiting."""

    def __init__(self, clock, per_call=1.0):
        self.clock = clock
        self.per_call = per_call
        self.lock = threading.Lock()
        self.calls = 0

    def __call__(self, url, timeout=20):
        with self.lock:
            self.calls += 1
        self.clock.advance(self.per_call)
        return 200, "text/html", "<p>x</p>"


def test_parallel_deadline_returns_partial_without_hanging():
    clock = Clock()
    fetch = ClockFetch(clock, per_call=1.0)
    urls = make_urls(5000)
    it = extract_urls(urls, extract=ok_extract, fetch=fetch, max_pages=5000, max_concurrency=8)

    progs = list(
        stream_pages(it, source_total=len(urls), max_pages=5000, now=clock, deadline=10.0)
    )
    final = progs[-1]

    assert final.status == "completed"  # terminates, does not hang
    assert final.capped and final.reason == "time_budget"
    assert final.total == 5000  # honest "took N of M"
    assert 0 < final.completed < 5000  # partial result
    assert fetch.calls < 5000  # did not fetch the whole sitemap
