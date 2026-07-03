import logging
import time
from collections.abc import Generator, Iterator, Mapping
from typing import Any

from dify_plugin.entities.datasource import (
    WebSiteInfo,
    WebSiteInfoDetail,
    WebsiteCrawlMessage,
)
from dify_plugin.interfaces.datasource.website import WebsiteCrawlDatasource

from docs_crawler.crawl import (
    CRAWL_TIME_BUDGET,
    CrawlProgress,
    Page,
    crawl,
    extract_urls,
    stream_pages,
)
from docs_crawler.discover import find_docs_root, sitemap_pages
from docs_crawler.extract import extract_page
from docs_crawler.links import in_scope
from docs_crawler.mediawiki import (
    derive_api,
    detect_mediawiki,
    fetch_page_html,
    html_to_markdown,
    list_all_pages,
    page_url,
    siteinfo,
)
from urllib.parse import urlparse
from docs_crawler.http import DEFAULT_UA, default_fetch

logger = logging.getLogger(__name__)


class DocsCrawlDatasource(WebsiteCrawlDatasource):
    def _get_website_crawl(
        self, datasource_parameters: Mapping[str, Any]
    ) -> Generator[WebsiteCrawlMessage, None, None]:
        url = str(datasource_parameters.get("url") or "").strip()
        if not url:
            raise ValueError("url is required")

        discover = bool(datasource_parameters.get("discover", True))
        path_prefix = str(datasource_parameters.get("path_prefix") or "").strip() or None
        max_pages = int(datasource_parameters.get("max_pages") or 50)
        max_depth = int(datasource_parameters.get("max_depth") or 5)
        # Bounded parallel fetch for the sitemap path. Modest default, capped at
        # 16 so a large sitemap can't be turned into a DoS against the server.
        max_concurrency = max(1, min(16, int(datasource_parameters.get("max_concurrency") or 5)))
        request_delay_ms = max(0, int(datasource_parameters.get("request_delay_ms") or 0))

        def _csv(name: str) -> list[str]:
            return [p.strip() for p in str(datasource_parameters.get(name) or "").split(",") if p.strip()]

        include = _csv("include_paths")
        exclude = _csv("exclude_paths")
        strategy = str(datasource_parameters.get("strategy") or "auto").lower()

        credentials = self.runtime.credentials or {}
        user_agent = str(credentials.get("user_agent") or DEFAULT_UA)

        def fetch(target: str, timeout: int = 20) -> tuple[int, str, str]:
            return default_fetch(target, timeout, user_agent=user_agent)

        # Time budget: stop fetching before the 300 s request cap so a
        # partial-but-completed result is always returned (see CRAWL_TIME_BUDGET).
        now = time.monotonic
        deadline = now() + CRAWL_TIME_BUDGET

        crawl_res = WebSiteInfo(web_info_list=[], status="processing", total=0, completed=0)
        yield self.create_crawl_message(crawl_res)

        # Resolve api_url + siteinfo once. In auto mode detect_mediawiki reuses the
        # same probe; in explicit mediawiki mode we fetch siteinfo directly.
        api_info: tuple[str, dict] | None = None
        if strategy == "auto":
            api_info = detect_mediawiki(url, fetch=fetch)
        elif strategy == "mediawiki":
            # Explicit strategy: a misconfiguration must surface, not silently
            # degrade to an HTML crawl. Fail hard if the target is not a MediaWiki.
            try:
                api_url = derive_api(url, fetch=fetch)
                info = siteinfo(api_url, fetch=fetch)
            except Exception as exc:  # noqa: BLE001
                raise ValueError(
                    f"strategy=mediawiki but {url!r} does not expose a working "
                    f"MediaWiki API: {exc}"
                ) from exc
            if "mediawiki" not in info["generator"].lower():
                raise ValueError(
                    f"strategy=mediawiki but {url!r} is not a MediaWiki "
                    f"(generator={info['generator']!r})"
                )
            api_info = (api_url, info)

        if api_info is not None:
            api_url, info = api_info
            # $wgServer can be unset/blank on real installs; fall back to the
            # api.php origin so page URLs are absolute and host-scoping works.
            api_parsed = urlparse(api_url)
            server = info["server"] or f"{api_parsed.scheme}://{api_parsed.netloc}"
            host = urlparse(server).netloc
            try:
                titles = list_all_pages(api_url, fetch=fetch, max_pages=max_pages)
            except Exception:  # noqa: BLE001 - emit whatever we have, don't abort mid-stream
                titles = []
            source_total: int | None = len(titles)

            def mediawiki_pages() -> Iterator[Page]:
                # Lazy: fetch each article only as it is consumed, so the time
                # budget can stop the crawl without fetching every remaining page.
                for title in titles:
                    url_for_title = page_url(server, info["articlepath"], title)
                    # path_prefix restricts the wiki crawl too; titles aren't assets.
                    if not in_scope(
                        url_for_title, host, path_prefix,
                        include=include, exclude=exclude, skip_assets=False,
                    ):
                        continue
                    try:
                        html = fetch_page_html(api_url, title, fetch=fetch)
                    except Exception:  # noqa: BLE001
                        continue
                    content = html_to_markdown(html)
                    if content.strip():
                        yield Page(
                            source_url=url_for_title,
                            title=title,
                            description="",
                            content=content,
                        )

            page_iter: Iterator[Page] = mediawiki_pages()
        else:
            # Sitemap first, scoped to the user-supplied URL (its own directory or
            # an explicit path_prefix) -- NOT to a discovered docs root. Discovery
            # can false-positive on catch-all SPA sites (e.g. VitePress answering
            # 200 for /wiki/) and would then filter out every real sitemap entry.
            sitemap = sitemap_pages(
                url, fetch=fetch, path_prefix=path_prefix, include=include, exclude=exclude
            )
            if sitemap:
                source_total = len(sitemap)
                page_iter = extract_urls(
                    sitemap,
                    extract=extract_page,
                    fetch=fetch,
                    max_pages=max_pages,
                    max_concurrency=max_concurrency,
                    request_delay_ms=request_delay_ms,
                )
            else:
                # No usable sitemap: discover the docs root (for bare domains) and BFS.
                # Source size is unbounded/unknown -> total is reported as N.
                source_total = None
                start_url = find_docs_root(url, fetch=fetch) if discover else url
                page_iter = crawl(
                    start_url,
                    extract=extract_page,
                    fetch=fetch,
                    path_prefix=path_prefix,
                    include=include,
                    exclude=exclude,
                    max_pages=max_pages,
                    max_depth=max_depth,
                )

        # Stream the crawl: emit periodic `processing` progress (only total/
        # completed are read by Dify for these) and a final `completed` message
        # whose web_info_list carries the collected pages. The generator is lazy,
        # so we never fetch or hold more than max_pages + the time budget allows.
        last: CrawlProgress | None = None
        for progress in stream_pages(
            page_iter, source_total=source_total, max_pages=max_pages,
            now=now, deadline=deadline,
        ):
            crawl_res.web_info_list = [
                WebSiteInfoDetail(
                    source_url=page.source_url,
                    content=page.content,
                    title=page.title,
                    description=page.description,
                )
                for page in progress.web_info
            ]
            crawl_res.status = progress.status
            crawl_res.total = progress.total
            crawl_res.completed = progress.completed
            yield self.create_crawl_message(crawl_res)
            last = progress

        if last is not None and last.capped:
            logger.info(
                "litecrawl: capped crawl of %s -- took %d of %d pages (limited by %s)",
                url, last.completed, last.total, last.reason,
            )
