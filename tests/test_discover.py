from docs_crawler.discover import find_docs_root


def make_fetch(ok_paths):
    def fetch(url, timeout=20):
        for p in ok_paths:
            if url.endswith(p):
                return 200, "text/html; charset=utf-8", "<html>ok</html>"
        return 404, "text/html", "not found"
    return fetch


def test_specific_path_used_as_is():
    # already points inside docs -> returned unchanged, no probing
    url = "https://docs.example.com/docs/"
    assert find_docs_root(url, fetch=make_fetch([])) == url


def test_bare_domain_probes_docs():
    base = "https://docs.example.com"
    root = find_docs_root(base, fetch=make_fetch(["/docs/"]))
    assert root == "https://docs.example.com/docs/"


def test_bare_domain_fallback_to_base():
    base = "https://x.example"
    assert find_docs_root(base, fetch=make_fetch([])) == base


def test_catch_all_spa_returns_base():
    # A site answering 200 + HTML for ANY path (SPA soft-404, e.g. VitePress) must
    # not yield a bogus docs root from probing -- base_url is returned unchanged.
    def fetch(url, timeout=20):
        return 200, "text/html; charset=utf-8", "<html>spa shell</html>"

    base = "https://spa.example"
    assert find_docs_root(base, fetch=fetch) == base
