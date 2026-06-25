from docs_crawler.crawl import extract_urls
from docs_crawler.discover import find_sitemap_urls, sitemap_pages
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


def test_find_sitemap_via_robots_txt():
    def fetch(url, timeout=20):
        if url.endswith("/robots.txt"):
            return 200, "text/plain", "User-agent: *\nSitemap: https://h.example/custom-sitemap.xml\n"
        if url.endswith("/custom-sitemap.xml"):
            return 200, "application/xml", SITEMAP
        return 404, "text/html", ""
    urls = find_sitemap_urls("https://h.example/docs/", fetch=fetch)
    assert urls == ["https://h.example/docs/a/", "https://h.example/docs/b/"]


def test_find_sitemap_accepts_text_plain_xml_body():
    # Server serves XML as text/plain; content-sniffing should still accept it.
    def fetch(url, timeout=20):
        if url.endswith("/robots.txt"):
            return 404, "text/plain", ""
        if url.endswith("/sitemap.xml"):
            return 200, "text/plain", SITEMAP
        return 404, "text/html", ""
    urls = find_sitemap_urls("https://h.example/docs/", fetch=fetch)
    assert "https://h.example/docs/a/" in urls


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


def test_sitemap_pages_scope_from_url_not_discovery():
    # Catch-all SPA: every path answers 200 + HTML; robots.txt advertises a root
    # sitemap whose pages live at /apps/... . sitemap_pages scopes by the *given
    # URL* (root '/'), so all pages pass -- discovery cannot shrink it to a bogus
    # sub-path (the bug that returned only the start page on VitePress wikis).
    sm = (
        '<?xml version="1.0"?><urlset>'
        "<url><loc>https://wiki.example/apps/a/</loc></url>"
        "<url><loc>https://wiki.example/apps-gnome/</loc></url>"
        "</urlset>"
    )

    def fetch(url, timeout=20):
        if url.endswith("/robots.txt"):
            return 200, "text/plain", "Sitemap: https://wiki.example/sitemap.xml\n"
        if url.endswith("/sitemap.xml"):
            return 200, "application/xml", sm
        return 200, "text/html", "<html>spa</html>"  # catch-all

    pages = sitemap_pages("https://wiki.example", fetch=fetch)
    assert pages == ["https://wiki.example/apps/a/", "https://wiki.example/apps-gnome/"]


def test_sitemap_pages_respects_path_prefix():
    sm = (
        '<?xml version="1.0"?><urlset>'
        "<url><loc>https://h.example/docs/a/</loc></url>"
        "<url><loc>https://h.example/blog/x/</loc></url>"
        "</urlset>"
    )

    def fetch(url, timeout=20):
        if url.endswith("/sitemap.xml"):
            return 200, "application/xml", sm
        return 404, "text/html", ""

    pages = sitemap_pages("https://h.example", fetch=fetch, path_prefix="/docs/")
    assert pages == ["https://h.example/docs/a/"]
