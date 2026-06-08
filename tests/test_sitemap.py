from docs_crawler.crawl import extract_urls
from docs_crawler.discover import find_sitemap_urls
from docs_crawler.links import parse_sitemap

SITEMAP = """<?xml version="1.0"?><urlset>
<url><loc>https://h.example/docs/a/</loc></url>
<url><loc>https://h.example/docs/b/</loc></url>
</urlset>"""

INDEX = """<sitemapindex><sitemap><loc>https://h.example/sm1.xml</loc></sitemap></sitemapindex>"""


def test_parse_sitemap():
    assert parse_sitemap(SITEMAP) == ["https://h.example/docs/a/", "https://h.example/docs/b/"]


def test_find_sitemap_urls_direct():
    def fetch(url, timeout=20):
        if url.endswith("/sitemap.xml"):
            return 200, "application/xml", SITEMAP
        return 404, "text/html", ""
    urls = find_sitemap_urls("https://h.example/docs/", fetch=fetch)
    assert urls == ["https://h.example/docs/a/", "https://h.example/docs/b/"]


def test_find_sitemap_index_expands():
    def fetch(url, timeout=20):
        if url.endswith("/sitemap.xml"):
            return 200, "application/xml", INDEX
        if url.endswith("/sm1.xml"):
            return 200, "application/xml", SITEMAP
        return 404, "text/html", ""
    urls = find_sitemap_urls("https://h.example", fetch=fetch)
    assert "https://h.example/docs/a/" in urls


def test_extract_urls():
    pages = extract_urls(
        ["https://h.example/docs/a/"],
        extract=lambda html, url: {"content": "# x", "title": "T", "description": "D"},
        fetch=lambda url, timeout=20: (200, "text/html", "<p>x</p>"),
    )
    assert len(pages) == 1 and pages[0].title == "T"
