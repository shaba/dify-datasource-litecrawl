from docs_crawler.extract import extract_page


def test_extract_page_markdown_and_metadata(getting_started_html):
    url = "https://docs.example.com/docs/start/getting-started/"
    result = extract_page(getting_started_html, url)
    assert result["title"]  # a non-empty title was extracted
    assert result["description"] == "Example Docs - documentation and support knowledge base."
    assert result["content"].lstrip().startswith("#")  # markdown heading
    assert "{" not in result["content"][:1]  # not raw json/html dump
