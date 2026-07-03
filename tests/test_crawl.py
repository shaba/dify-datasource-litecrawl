from docs_crawler.crawl import crawl, default_path_prefix

SITE = {
    "https://h.example/docs/": '<a href="/docs/a/">a</a> <a href="/docs/b/">b</a> <a href="/out/">o</a>',
    "https://h.example/docs/a/": '<a href="/docs/a/deep/">deep</a>',
    "https://h.example/docs/a/deep/": "<p>deep</p>",
    "https://h.example/docs/b/": "<p>b</p>",
    "https://h.example/out/": "<p>out of scope</p>",
}


def fetch(url, timeout=20):
    if url in SITE:
        return 200, "text/html", SITE[url]
    return 404, "text/html", ""


def extract(html, url):
    return {"content": html, "title": url.rsplit("/", 2)[-2] or "root", "description": ""}


def test_crawl_in_scope_and_collects_pages():
    pages = list(crawl("https://h.example/docs/", extract=extract, fetch=fetch))
    urls = {p.source_url for p in pages}
    assert "https://h.example/docs/" in urls
    assert "https://h.example/docs/a/" in urls
    assert "https://h.example/docs/a/deep/" in urls
    assert "https://h.example/docs/b/" in urls
    assert "https://h.example/out/" not in urls  # out of /docs/ scope


def test_crawl_respects_max_pages():
    pages = list(crawl("https://h.example/docs/", extract=extract, fetch=fetch, max_pages=2))
    assert len(pages) == 2


def test_default_path_prefix_directory_vs_page():
    # page-style start URL scopes to its parent directory (shared by sitemap + BFS)
    assert default_path_prefix("https://h.example/docs/intro") == "/docs/"
    assert default_path_prefix("https://h.example/docs/") == "/docs/"
    assert default_path_prefix("https://h.example") == "/"


def test_crawl_dedups_trailing_slash_variants():
    site = {
        "https://h.example/docs/": '<a href="/docs/a">a</a> <a href="/docs/a/">a-slash</a>',
        "https://h.example/docs/a": "<p>a</p>",
        "https://h.example/docs/a/": "<p>a again</p>",
    }

    def f(url, timeout=20):
        return (200, "text/html", site[url]) if url in site else (404, "text/html", "")

    pages = list(crawl("https://h.example/docs/", extract=extract, fetch=f))
    # /docs/a and /docs/a/ are the same logical page -> fetched once
    assert sum(1 for p in pages if p.source_url.rstrip("/") == "https://h.example/docs/a") == 1


def test_crawl_respects_max_depth():
    pages = list(crawl("https://h.example/docs/", extract=extract, fetch=fetch, max_depth=1))
    urls = {p.source_url for p in pages}
    assert "https://h.example/docs/a/deep/" not in urls  # depth 2 excluded
    assert "https://h.example/docs/a/" in urls
