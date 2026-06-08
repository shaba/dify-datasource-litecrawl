from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def getting_started_html():
    return (FIXTURES / "page_getting_started.html").read_text(encoding="utf-8")
