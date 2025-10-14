import pytest

from intelli_crawler.config import AntiScrapingStrategies, DeduplicationConfig, ScheduleConfig, SiteType, SourceConfig
from intelli_crawler.engine import Parser


def build_source(**overrides):
    base = {
        "source_name": "Example",
        "site_type": SiteType.NEWS,
        "target_url": "https://example.com",
        "entry_pattern": "ul.list li a",
        "detail_pattern": {
            "title": "h1",
            "content": "div.article",
        },
        "schedule": ScheduleConfig(),
        "deduplication": DeduplicationConfig(store_path="history/test.db"),
        "anti_scraping_strategies": AntiScrapingStrategies(delay_range=(0, 0)),
    }
    base.update(overrides)
    return SourceConfig(**base)


def test_parse_entries_and_detail():
    parser = Parser()
    source = build_source()
    html = """
    <html><body>
    <ul class="list">
      <li><a href="/a">One</a></li>
      <li><a href="https://external/b">Two</a></li>
      <li><a href="javascript:;">Skip</a></li>
    </ul>
    </body></html>
    """
    entries = parser.parse_entries(source, html, source.target_url)
    assert entries == ["https://example.com/a", "https://external/b"]

    detail_html = "<html><h1>Title</h1><div class='article'>Body</div></html>"
    record = parser.parse_detail(source, detail_html, entries[0])
    assert record.data["title"] == "Title"
    assert record.data["content"] == "Body"
    assert "raw_html" in record.data
    assert record.data["site_type"] == "news"


def test_keyword_filter():
    parser = Parser()
    source = build_source()
    detail_html = "<html><h1>AI wins</h1><div class='article'>Deep dive</div></html>"
    record = parser.parse_detail(source, detail_html, source.target_url)
    assert parser.filter_by_keywords(record, ["AI"])
    assert not parser.filter_by_keywords(record, ["Blockchain"])
