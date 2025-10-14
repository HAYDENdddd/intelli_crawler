from __future__ import annotations

from pathlib import Path

from intelli_crawler.engine import Parser


def test_parse_entries_deduplicates(sample_source_config, snapshot) -> None:
    parser = Parser()
    source = sample_source_config(entry_pattern="ul.items li a")
    html = """
    <html><body>
    <ul class="items">
      <li><a href="/a">A</a></li>
      <li><a href="https://ext/b">B</a></li>
      <li><a href="/a">Duplicate</a></li>
      <li><a href="javascript:void(0)">Skip</a></li>
    </ul>
    </body></html>
    """
    entries = parser.parse_entries(source, html, "https://example.com")
    snapshot.assert_match(entries, key="parsed_entries")


def test_parse_detail_with_meta_fallback(sample_source_config, snapshot) -> None:
    source = sample_source_config(
        detail_pattern={
            "title": ["h1::text", 'meta[name="title"]::attr:content'],
            "content": ["article.body::text"],
        }
    )
    html = """
    <html>
      <head>
        <meta name="title" content="From Meta" />
        <meta property="og:description" content="Backup description" />
      </head>
      <body>
        <article class="body"></article>
      </body>
    </html>
    """
    parser = Parser()
    record = parser.parse_detail(source, html, "https://example.com/meta")
    snapshot.assert_match(record.data, key="detail_meta_fallback")


def test_filter_by_keywords(sample_source_config) -> None:
    source = sample_source_config()
    parser = Parser()
    html = "<html><h1>AI breakthroughs</h1><article>Quantum leap</article></html>"
    record = parser.parse_detail(source, html, "https://example.com/detail")
    assert parser.filter_by_keywords(record, ["AI"])
    assert not parser.filter_by_keywords(record, ["Blockchain"])


def test_extract_foresight_records(snapshot) -> None:
    parser = Parser()
    html_path = Path(__file__).with_name("fixtures_foresight.html")
    html_content = html_path.read_text(encoding="utf-8")
    records = parser.extract_foresight_records(html_content, "https://foresightnews.pro")
    snapshot.assert_match(records, key="foresight_records")
