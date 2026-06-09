import json

from docs_crawler.mediawiki import (
    derive_api,
    is_mediawiki,
    list_all_pages,
    page_url,
    siteinfo,
)

SITEINFO = {"query": {"general": {"generator": "MediaWiki 1.38.2",
                                  "server": "https://wiki.example.com",
                                  "articlepath": "/$1"}}}
PAGE1 = {"query": {"allpages": [{"title": "Apt"}, {"title": "Getting Started"}]},
         "continue": {"apcontinue": "T"}}
PAGE2 = {"query": {"allpages": [{"title": "Tmpfs"}]}}


def make_fetch(responses):
    def fetch(url, timeout=20):
        for needle, payload in responses:
            if needle in url:
                return 200, "application/json", json.dumps(payload)
        return 404, "application/json", "{}"
    return fetch


def test_derive_api():
    assert derive_api("https://wiki.example.com") == "https://wiki.example.com/api.php"
    assert derive_api("https://wiki.example.com/api.php") == "https://wiki.example.com/api.php"


def test_derive_api_follows_edituri_for_w_api_php():
    # Wikipedia/mediawiki.org layout: articles at /wiki/$1, API at /w/api.php.
    head = (
        '<html><head>'
        '<link rel="EditURI" type="application/rsd+xml" '
        'href="https://en.wikipedia.org/w/api.php?action=rsd"/>'
        '</head><body>x</body></html>'
    )

    def fetch(url, timeout=20):
        return 200, "text/html", head

    assert derive_api("https://en.wikipedia.org/wiki/Apt", fetch=fetch) == \
        "https://en.wikipedia.org/w/api.php"


def test_derive_api_edituri_attribute_order_independent():
    # Skin/proxy/minifier may emit href before rel; discovery must still work.
    head = (
        '<html><head>'
        '<link type="application/rsd+xml" '
        'href="https://en.wikipedia.org/w/api.php?action=rsd" rel="EditURI"/>'
        '</head><body>x</body></html>'
    )

    def fetch(url, timeout=20):
        return 200, "text/html", head

    assert derive_api("https://en.wikipedia.org/wiki/Apt", fetch=fetch) == \
        "https://en.wikipedia.org/w/api.php"


def test_derive_api_falls_back_to_root_without_edituri():
    def fetch(url, timeout=20):
        return 200, "text/html", "<html><head></head><body>no rsd</body></html>"

    assert derive_api("https://wiki.example.com/wiki/Apt", fetch=fetch) == \
        "https://wiki.example.com/api.php"


def test_is_mediawiki_negative_for_non_wiki_generator():
    fetch = make_fetch([("siteinfo", {"query": {"general": {
        "generator": "WordPress 6.4",
        "server": "https://blog.example.com",
        "articlepath": "/$1",
    }}})])
    assert not is_mediawiki("https://blog.example.com", fetch=fetch)


def test_siteinfo_normalizes_protocol_relative_server():
    fetch = make_fetch([("siteinfo", {"query": {"general": {
        "generator": "MediaWiki 1.41",
        "server": "//wiki.example.com",  # $wgServer protocol-relative default
        "articlepath": "/wiki/$1",
    }}})])
    info = siteinfo("https://wiki.example.com/w/api.php", fetch=fetch)
    assert info["server"] == "https://wiki.example.com"


def test_siteinfo_and_is_mediawiki():
    fetch = make_fetch([("siteinfo", SITEINFO)])
    info = siteinfo("https://wiki.example.com/api.php", fetch=fetch)
    assert info["server"] == "https://wiki.example.com"
    assert is_mediawiki("https://wiki.example.com", fetch=fetch)


def test_list_all_pages_paginates():
    def fetch(url, timeout=20):
        if "apcontinue=T" in url:
            return 200, "application/json", json.dumps(PAGE2)
        if "allpages" in url:
            return 200, "application/json", json.dumps(PAGE1)
        return 404, "application/json", "{}"
    titles = list_all_pages("https://wiki.example.com/api.php", fetch=fetch, page_size=2)
    assert titles == ["Apt", "Getting Started", "Tmpfs"]


def test_page_url():
    assert page_url("https://wiki.example.com", "/$1", "Getting Started") == \
        "https://wiki.example.com/Getting_Started"


def test_fetch_page_html_v2_and_v1():
    from docs_crawler.mediawiki import fetch_page_html
    import json as _json

    def fetch_v2(url, timeout=20):
        return 200, "application/json", _json.dumps({"parse": {"text": "<p>hello</p>"}})

    def fetch_v1(url, timeout=20):
        return 200, "application/json", _json.dumps({"parse": {"text": {"*": "<p>hi</p>"}}})

    assert fetch_page_html("https://w/api.php", "T", fetch=fetch_v2) == "<p>hello</p>"
    assert fetch_page_html("https://w/api.php", "T", fetch=fetch_v1) == "<p>hi</p>"


def test_html_to_markdown_cleans_mediawiki():
    from docs_crawler.mediawiki import html_to_markdown
    frag = ('<div class="mw-parser-output">'
            '<h2>Heading<span class="mw-editsection">[edit]</span></h2>'
            '<table class="infobox"><tr><td>noise</td></tr></table>'
            '<p>This is <b>body</b> text with a <a href="/Example">link</a>.</p></div>')
    md = html_to_markdown(frag)
    assert "edit" not in md
    assert "noise" not in md
    assert "**body**" in md
    assert "link" in md  # link text kept, href stripped
    assert "## Heading" in md


def test_html_to_markdown_noise_class_is_exact_not_substring():
    from docs_crawler.mediawiki import html_to_markdown
    # 'infoboxer' / 'mytoc' contain noise tokens as substrings but must NOT be removed.
    frag = ('<div class="mw-parser-output">'
            '<div class="infoboxer">keepme</div>'
            '<table class="infobox"><tr><td>drop</td></tr></table>'
            '</div>')
    md = html_to_markdown(frag)
    assert "keepme" in md
    assert "drop" not in md
