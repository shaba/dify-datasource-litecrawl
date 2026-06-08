from __future__ import annotations

from typing import Callable

import requests

DEFAULT_UA = (
    "docs-crawler/0.0.1 (+https://example.com/docs-crawler)"
)

# Fetch: (url, timeout) -> (status_code, content_type, text)
Fetch = Callable[[str, int], "tuple[int, str, str]"]


def default_fetch(url: str, timeout: int = 20, *, user_agent: str = DEFAULT_UA) -> tuple[int, str, str]:
    response = requests.get(url, timeout=timeout, headers={"User-Agent": user_agent})
    return response.status_code, response.headers.get("content-type", ""), response.text
