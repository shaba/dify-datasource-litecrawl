from collections.abc import Generator, Mapping
from typing import Any

from dify_plugin.entities.datasource import (
    WebSiteInfo,
    WebSiteInfoDetail,
    WebsiteCrawlMessage,
)
from dify_plugin.interfaces.datasource.website import WebsiteCrawlDatasource

from docs_crawler.crawl import Page, crawl, extract_urls
from docs_crawler.discover import find_docs_root, find_sitemap_urls
from docs_crawler.extract import extract_page
from docs_crawler.links import in_scope
from docs_crawler.mediawiki import (
    derive_api,
    fetch_page_html,
    html_to_markdown,
    is_mediawiki,
    list_all_pages,
    page_url,
    siteinfo,
)
from urllib.parse import urlparse
from docs_crawler.http import DEFAULT_UA, default_fetch


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

        def _csv(name: str) -> list[str]:
            return [p.strip() for p in str(datasource_parameters.get(name) or "").split(",") if p.strip()]

        include = _csv("include_paths")
        exclude = _csv("exclude_paths")
        strategy = str(datasource_parameters.get("strategy") or "auto").lower()

        credentials = self.runtime.credentials or {}
        user_agent = str(credentials.get("user_agent") or DEFAULT_UA)

        def fetch(target: str, timeout: int = 20) -> tuple[int, str, str]:
            return default_fetch(target, timeout, user_agent=user_agent)

        crawl_res = WebSiteInfo(web_info_list=[], status="processing", total=0, completed=0)
        yield self.create_crawl_message(crawl_res)

        use_mediawiki = strategy == "mediawiki" or (
            strategy == "auto" and is_mediawiki(url, fetch=fetch)
        )

        if use_mediawiki:
            api_url = derive_api(url)
            info = siteinfo(api_url, fetch=fetch)
            host = urlparse(info["server"] or url).netloc
            titles = list_all_pages(api_url, fetch=fetch, max_pages=max_pages)
            pages = []
            for title in titles:
                if len(pages) >= max_pages:
                    break
                url_for_title = page_url(info["server"], info["articlepath"], title)
                if not in_scope(url_for_title, host, None, include=include, exclude=exclude):
                    continue
                try:
                    html = fetch_page_html(api_url, title, fetch=fetch)
                except Exception:  # noqa: BLE001
                    continue
                content = html_to_markdown(html)
                if content.strip():
                    pages.append(Page(
                        source_url=url_for_title,
                        title=title,
                        description="",
                        content=content,
                    ))
        else:
            start_url = find_docs_root(url, fetch=fetch) if discover else url
            host = urlparse(start_url).netloc
            scope = path_prefix or (urlparse(start_url).path or "/")
            sitemap = [
                u for u in find_sitemap_urls(start_url, fetch=fetch)
                if in_scope(u, host, scope, include=include, exclude=exclude)
            ]
            if sitemap:
                pages = extract_urls(sitemap, extract=extract_page, fetch=fetch, max_pages=max_pages)
            else:
                pages = crawl(
                    start_url,
                    extract=extract_page,
                    fetch=fetch,
                    path_prefix=path_prefix,
                    include=include,
                    exclude=exclude,
                    max_pages=max_pages,
                    max_depth=max_depth,
                )

        crawl_res.web_info_list = [
            WebSiteInfoDetail(
                source_url=page.source_url,
                content=page.content,
                title=page.title,
                description=page.description,
            )
            for page in pages
        ]
        crawl_res.status = "completed"
        crawl_res.total = len(pages)
        crawl_res.completed = len(pages)
        yield self.create_crawl_message(crawl_res)
