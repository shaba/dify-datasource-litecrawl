"""Progressive streaming + time-budget tests (L1/L2/L3).

Deterministic: a fake clock is advanced by the fake fetch (each fetched page
"costs" a fixed number of seconds), so no real time passes and nothing sleeps.
"""

from docs_crawler.crawl import extract_urls, stream_pages


class Clock:
    """Manually-advanced monotonic clock."""

    def __init__(self) -> None:
        self.t = 0.0

    def advance(self, dt: float) -> None:
        self.t += dt

    def __call__(self) -> float:
        return self.t


class FakeFetch:
    """Records every fetch and advances the shared clock by `per_call` seconds,
    modelling a fixed cost-per-page. Never touches the network."""

    def __init__(self, clock: Clock, per_call: float = 0.0) -> None:
        self.clock = clock
        self.per_call = per_call
        self.calls = 0

    def __call__(self, url, timeout=20):
        self.calls += 1
        self.clock.advance(self.per_call)
        return 200, "text/html", "<p>x</p>"


def ok_extract(html, url):
    return {"content": "body", "title": url, "description": ""}


def make_urls(n):
    return [f"https://h.example/p/{i}/" for i in range(n)]


def test_stops_at_max_pages_without_fetching_everything():
    clock = Clock()
    fetch = FakeFetch(clock)
    urls = make_urls(5000)
    it = extract_urls(urls, extract=ok_extract, fetch=fetch, max_pages=50)

    progs = list(stream_pages(it, source_total=len(urls), max_pages=50, now=clock))
    final = progs[-1]

    assert final.status == "completed"
    assert final.completed == 50
    assert final.total == 5000  # capped -> reports the true source size (M)
    assert final.capped and final.reason == "max_pages"
    # Laziness: only 50 of the 5000 URLs were ever fetched.
    assert fetch.calls == 50
    # Progressive `processing` messages were emitted before completion.
    assert any(p.status == "processing" for p in progs)


def test_stops_at_time_budget_with_partial_result():
    clock = Clock()
    fetch = FakeFetch(clock, per_call=1.0)  # 1 second per page
    urls = make_urls(5000)
    it = extract_urls(urls, extract=ok_extract, fetch=fetch, max_pages=5000)

    # Budget of 10 s -> ~10 pages before we stop.
    deadline = 10.0
    progs = list(
        stream_pages(it, source_total=len(urls), max_pages=5000, now=clock, deadline=deadline)
    )
    final = progs[-1]

    assert final.status == "completed"
    assert final.capped and final.reason == "time_budget"
    assert final.total == 5000  # honest "took N of M"
    assert final.completed == 10
    assert fetch.calls == 10  # did NOT fetch all 5000
    assert any(p.status == "processing" for p in progs)


def test_processing_snapshots_report_growing_progress():
    clock = Clock()
    fetch = FakeFetch(clock)
    urls = make_urls(200)
    it = extract_urls(urls, extract=ok_extract, fetch=fetch, max_pages=200)

    # web_info is a live cumulative view (no per-snapshot copy -> no O(n^2)
    # intermediate lists); a consumer reads it at yield time. Snapshot len here.
    snapshots = []  # (status, completed, len_at_yield)
    for p in stream_pages(
        it, source_total=len(urls), max_pages=200, now=clock,
        progress_every_pages=25, progress_every_seconds=5.0,
    ):
        snapshots.append((p.status, p.completed, len(p.web_info)))

    processing = [s for s in snapshots if s[0] == "processing"]
    completed = [s for s in snapshots if s[0] == "completed"]

    assert len(completed) == 1
    assert len(processing) >= 1
    # completed counts are monotonically non-decreasing
    counts = [s[1] for s in snapshots]
    assert counts == sorted(counts)
    # at yield time each snapshot's accumulated list matches its completed count
    for status, completed_n, length in snapshots:
        assert length == completed_n


def test_small_site_completes_without_capping():
    clock = Clock()
    fetch = FakeFetch(clock)
    urls = make_urls(3)
    it = extract_urls(urls, extract=ok_extract, fetch=fetch, max_pages=50)

    progs = list(stream_pages(it, source_total=len(urls), max_pages=50, now=clock))
    final = progs[-1]

    assert final.status == "completed"
    assert not final.capped and final.reason == ""
    assert final.completed == 3 and final.total == 3
    assert fetch.calls == 3


def test_bfs_unknown_source_total_reports_n_on_budget():
    # source_total=None (BFS): a budget-truncated crawl reports total == completed
    # (we can't know the true site size), but is still flagged capped.
    clock = Clock()
    fetch = FakeFetch(clock, per_call=2.0)
    urls = make_urls(1000)
    it = extract_urls(urls, extract=ok_extract, fetch=fetch, max_pages=1000)

    progs = list(
        stream_pages(it, source_total=None, max_pages=1000, now=clock, deadline=6.0)
    )
    final = progs[-1]

    assert final.status == "completed"
    assert final.capped and final.reason == "time_budget"
    assert final.total == final.completed  # unknown M -> total == N
    assert final.completed == 3
