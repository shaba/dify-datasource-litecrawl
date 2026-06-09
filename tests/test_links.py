from docs_crawler.links import extract_links, in_scope

HTML = '''
<a href="/docs/a/">A</a> <a href="/docs/b/#frag">B</a>
<a href="https://other.example/docs/x/">ext</a>
<a href="/docs/img.png">img</a> <a href="mailto:x@y">m</a>
<a href="/other/c/">out</a>
'''


def test_extract_links_absolutizes_and_drops_fragments():
    links = extract_links(HTML, "https://h.example/docs/")
    assert "https://h.example/docs/a/" in links
    assert "https://h.example/docs/b/" in links  # fragment stripped
    assert "https://other.example/docs/x/" in links
    assert not any("mailto" in u for u in links)


def test_extract_links_decodes_entities_and_trims_whitespace():
    html = '<a href="/p?a=1&amp;b=2">x</a> <a href=" /docs/y ">y</a>'
    links = extract_links(html, "https://h.example/docs/")
    assert "https://h.example/p?a=1&b=2" in links  # &amp; decoded to &
    assert "https://h.example/docs/y" in links  # surrounding whitespace stripped


def test_extract_links_handles_unquoted_href():
    links = extract_links('<a href=/docs/a>x</a> <a href=/docs/b/>y</a>',
                          "https://h.example/docs/")
    assert "https://h.example/docs/a" in links
    assert "https://h.example/docs/b/" in links


def test_in_scope_host_prefix_and_assets():
    host = "h.example"
    assert in_scope("https://h.example/docs/a/", host, "/docs/")
    assert not in_scope("https://other.example/docs/a/", host, "/docs/")  # host
    assert not in_scope("https://h.example/other/c/", host, "/docs/")  # prefix
    assert not in_scope("https://h.example/docs/img.png", host, "/docs/")  # asset
    assert not in_scope("https://h.example/docs/file.pdf", host, "/docs/")  # pdf -> firecrawl
