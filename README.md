# dify-datasource-litecrawl

A Dify datasource plugin that crawls a static documentation site or wiki and extracts
clean, per-page markdown — ready to feed a Dify Knowledge base.

It works with any site that exposes either a `sitemap.xml` or navigable in-page links,
which covers the common static-site generators — **VitePress, MkDocs, Docusaurus, Sphinx,
Hugo, Jekyll, GitBook, mdBook** and similar — as well as **MediaWiki** wikis (crawled via
the MediaWiki API). Page content is converted to markdown with Trafilatura.

## How it works

Choose a crawl `strategy`:

- **auto** (default) — detect the site type: if it is a MediaWiki, use its API; otherwise
  use the sitemap when present, and fall back to following links breadth-first.
- **html** — use the sitemap when present, otherwise a breadth-first link crawl.
- **mediawiki** — enumerate pages via the MediaWiki API (`api.php`, allpages) and render
  each page via `action=parse`.

## Parameters

- `url` (required) — documentation site URL, or a bare domain for auto-discovery.
- `strategy` — `auto` | `html` | `mediawiki` (default `auto`).
- `discover` — when a bare domain is given, probe common documentation paths (e.g. `/docs/`).
- `path_prefix` — restrict the crawl to a path, e.g. `/docs/`.
- `include_paths` / `exclude_paths` — comma-separated glob patterns to include or skip.
- `max_pages` — stop after N pages (default 50).
- `max_depth` — link-follow depth from the start URL (default 5).

## Development

```sh
python3 -m pytest -q
ruff check .
yamllint .
```

The crawler logic (discovery, sitemap parsing, BFS link crawl, MediaWiki, and content
extraction) lives in the `docs_crawler` package, which is independent of the Dify SDK and
covered by unit tests with mocked network calls.

## License

Apache-2.0. Copyright © 2026 Alexey Shabalin.

## Repository

<https://github.com/shaba/dify-datasource-litecrawl> — issues and pull requests welcome.
