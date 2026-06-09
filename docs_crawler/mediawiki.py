from __future__ import annotations

import json
import re
from urllib.parse import quote, urlencode, urljoin, urlparse

from .http import Fetch, default_fetch

# api.php is advertised in every MediaWiki page head via <link rel="EditURI">,
# whose href points at api.php?action=rsd. This is the canonical, layout-agnostic
# way to locate the API (handles /api.php, /w/api.php, and custom script paths).
# rel and href are matched independently within the tag so attribute order does
# not matter (skins/proxies/minifiers may emit href before rel).
_LINK_TAG = re.compile(r"<link\b[^>]*>", re.IGNORECASE)
_REL_EDITURI = re.compile(r"""\brel=["']?EditURI\b""", re.IGNORECASE)
_TAG_HREF = re.compile(r"""\bhref=["']?([^"'\s>]+)""", re.IGNORECASE)


def _api_from_html(html: str, base_url: str) -> str | None:
    for tag in _LINK_TAG.findall(html or ""):
        if not _REL_EDITURI.search(tag):
            continue
        m = _TAG_HREF.search(tag)
        if not m:
            continue
        href = urljoin(base_url, m.group(1).strip()).split("#")[0].split("?")[0]
        if href.endswith("api.php"):
            return href
    return None


def derive_api(base_url: str, *, fetch: Fetch | None = None, timeout: int = 20) -> str:
    """Resolve the MediaWiki api.php endpoint from a wiki URL.

    If the URL already points at api.php, use it. Otherwise, when a ``fetch`` is
    given, read the page and follow its ``<link rel="EditURI">`` (which advertises
    api.php) — this handles the common ``/w/api.php`` layout (Wikipedia,
    mediawiki.org) where articles live under ``/wiki/$1``. Falls back to
    ``<host>/api.php`` at the root if discovery is unavailable.
    """
    parsed = urlparse(base_url)
    if parsed.path.rstrip("/").endswith("api.php"):
        return base_url.split("?")[0]
    if fetch is not None:
        try:
            status, _ct, text = fetch(base_url, timeout)
        except Exception:  # noqa: BLE001 - discovery is best-effort
            text = ""
            status = 0
        if 200 <= status < 300:
            found = _api_from_html(text, base_url)
            if found:
                return found
    return f"{parsed.scheme}://{parsed.netloc}/api.php"


def _api_get(api_url: str, params: dict, *, fetch: Fetch, timeout: int) -> dict:
    sep = "&" if "?" in api_url else "?"
    status, _content_type, text = fetch(f"{api_url}{sep}{urlencode(params)}", timeout)
    if not (200 <= status < 300):
        raise ValueError(f"MediaWiki API returned {status}")
    return json.loads(text)


def siteinfo(api_url: str, *, fetch: Fetch = default_fetch, timeout: int = 20) -> dict:
    data = _api_get(
        api_url,
        {"action": "query", "meta": "siteinfo", "siprop": "general", "format": "json"},
        fetch=fetch,
        timeout=timeout,
    )
    general = data.get("query", {}).get("general", {})
    server = str(general.get("server") or "")
    if server.startswith("//"):  # protocol-relative $wgServer default
        server = f"{urlparse(api_url).scheme}:{server}"
    return {
        "generator": str(general.get("generator") or ""),
        "server": server,
        "articlepath": str(general.get("articlepath") or "/$1"),
    }


def detect_mediawiki(
    base_url: str, *, fetch: Fetch = default_fetch, timeout: int = 20
) -> tuple[str, dict] | None:
    """Probe whether base_url is a MediaWiki; return (api_url, siteinfo) or None.

    Returns the resolved api.php endpoint and siteinfo so callers can reuse them
    without a second round-trip.
    """
    try:
        api_url = derive_api(base_url, fetch=fetch, timeout=timeout)
        info = siteinfo(api_url, fetch=fetch, timeout=timeout)
    except Exception:  # noqa: BLE001
        return None
    if "mediawiki" not in info["generator"].lower():
        return None
    return api_url, info


def is_mediawiki(base_url: str, *, fetch: Fetch = default_fetch, timeout: int = 20) -> bool:
    return detect_mediawiki(base_url, fetch=fetch, timeout=timeout) is not None


def list_all_pages(
    api_url: str,
    *,
    fetch: Fetch = default_fetch,
    namespace: int = 0,
    page_size: int = 500,
    max_pages: int = 1000,
    timeout: int = 20,
) -> list[str]:
    """Return page titles via action=query&list=allpages, following apcontinue."""
    titles: list[str] = []
    cont: dict = {}
    while len(titles) < max_pages:
        params: dict = {
            "action": "query",
            "list": "allpages",
            "apnamespace": namespace,
            "aplimit": min(page_size, max_pages - len(titles)),
            "format": "json",
        }
        params.update(cont)  # echo the full continuation object back
        data = _api_get(api_url, params, fetch=fetch, timeout=timeout)
        pages = data.get("query", {}).get("allpages", [])
        titles.extend(str(p["title"]) for p in pages if "title" in p)
        cont = data.get("continue") or {}
        if not cont or not pages:
            break
    return titles[:max_pages]


def page_url(server: str, articlepath: str, title: str) -> str:
    encoded = quote(title.replace(" ", "_"), safe="/:")
    return server.rstrip("/") + articlepath.replace("$1", encoded)


def fetch_page_html(api_url: str, title: str, *, fetch: Fetch = default_fetch, timeout: int = 20) -> str:
    """Return the rendered article HTML via action=parse (clean, no site chrome)."""
    data = _api_get(
        api_url,
        {"action": "parse", "page": title, "prop": "text", "formatversion": 2, "format": "json"},
        fetch=fetch,
        timeout=timeout,
    )
    text = data.get("parse", {}).get("text")
    if isinstance(text, dict):  # formatversion=1 returns {"*": html}
        text = text.get("*", "")
    return str(text or "")


_NOISE_CLASSES = ("mw-editsection", "infobox", "navbox", "metadata", "noprint",
                  "mw-empty-elt", "toc", "mw-jump-link", "printfooter")


def html_to_markdown(fragment_html: str) -> str:
    """Clean MediaWiki article HTML (action=parse) and convert to markdown.

    Removes edit-section links, infoboxes, navboxes, TOC, styles/scripts, then
    converts with markdownify (links/images flattened). Better than trafilatura
    for MediaWiki fragments.
    """
    from bs4 import BeautifulSoup
    from markdownify import markdownify

    noise = set(_NOISE_CLASSES)
    soup = BeautifulSoup(fragment_html or "", "html.parser")
    for tag in soup.find_all(["style", "script"]):
        tag.decompose()
    for el in soup.find_all(
        lambda t: t.has_attr("class") and noise & set(t.get("class", []))
    ):
        el.decompose()
    markdown = markdownify(str(soup), heading_style="ATX", strip=["a", "img"])
    return re.sub(r"\n{3,}", "\n\n", markdown).strip()
