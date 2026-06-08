from __future__ import annotations

from typing import Any

import trafilatura


def extract_page(html: str, url: str) -> dict[str, Any]:
    """Extract main content as markdown plus title/description via trafilatura."""
    content = trafilatura.extract(html, output_format="markdown", with_metadata=False, url=url) or ""
    title = ""
    description = ""
    meta = trafilatura.extract_metadata(html, default_url=url)
    if meta is not None:
        title = str(getattr(meta, "title", "") or "")
        description = str(getattr(meta, "description", "") or "")
    return {"content": content, "title": title, "description": description}
