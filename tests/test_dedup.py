from pathlib import Path

from intelli_crawler.engine.dedup import DeduplicationStore
from intelli_crawler.infra.storage import SQLiteManager


def test_deduplication_store(tmp_path):
    manager = SQLiteManager()
    db_path = tmp_path / "history.db"
    store = DeduplicationStore(manager, db_path)

    result = store.check_and_store("https://example.com/a", "content", "source")
    assert not result.is_duplicate

    duplicate = store.check_and_store("https://example.com/a", "content", "source")
    assert duplicate.url_duplicate
    assert duplicate.is_duplicate

    content_duplicate = store.check_and_store("https://example.com/b", "content", "source")
    assert content_duplicate.content_duplicate
