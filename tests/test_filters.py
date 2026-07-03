from docs_crawler.crawl import crawl
from docs_crawler.links import in_scope, path_matches

HOST = "h.example"


def test_path_matches_glob():
    assert path_matches("/docs/a/", ["docs/*"])
    assert path_matches("/docs/a/b/", ["docs/*"])
    assert path_matches("/start/x/", ["start/*", "docs/*"])
    assert not path_matches("/blog/x/", ["docs/*"])


def test_path_matches_bare_pattern_is_segment_not_prefix():
    # bare 'blog' matches the segment, not '/blogging' (no unbounded prefix glob)
    assert path_matches("/blog", ["blog"])
    assert path_matches("/blog/x/", ["blog"])
    assert not path_matches("/blogging/x/", ["blog"])
    assert not path_matches("/documentation/", ["doc"])
    # explicit trailing '*' opts into prefix matching
    assert path_matches("/blogging/x/", ["blog*"])


def test_in_scope_include_exclude():
    assert in_scope("https://h.example/docs/a/", HOST, "/docs/", include=["docs/*"])
    assert not in_scope("https://h.example/docs/blog/x/", HOST, "/docs/", exclude=["docs/blog/*"])
    # include set but no match -> excluded
    assert not in_scope("https://h.example/docs/a/", HOST, "/docs/", include=["other/*"])


SITE = {
    "https://h.example/docs/": '<a href="/docs/keep/">k</a> <a href="/docs/blog/skip/">b</a>',
    "https://h.example/docs/keep/": "<p>keep</p>",
    "https://h.example/docs/blog/skip/": "<p>skip</p>",
}


def fetch(url, timeout=20):
    return (200, "text/html", SITE[url]) if url in SITE else (404, "text/html", "")


def extract(html, url):
    return {"content": html, "title": "t", "description": ""}


def test_crawl_applies_exclude():
    pages = list(crawl("https://h.example/docs/", extract=extract, fetch=fetch, exclude=["docs/blog/*"]))
    urls = {p.source_url for p in pages}
    assert "https://h.example/docs/keep/" in urls
    assert "https://h.example/docs/blog/skip/" not in urls
