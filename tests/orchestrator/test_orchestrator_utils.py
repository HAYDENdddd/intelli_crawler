from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from intelli_crawler.config import DeduplicationConfig
from intelli_crawler.infra import SQLiteManager
from intelli_crawler.orchestrator import DeduplicationStoreFactory, Orchestrator


class FixedDatetime(datetime):
    @classmethod
    def utcnow(cls):
        return cls(2024, 5, 20, 12, 0, 0)


@pytest.fixture
def orchestrator(sample_global_config):
    repo = MagicMock()
    repo.load_global_config.return_value = sample_global_config
    scheduler = MagicMock()
    thread_pool = MagicMock()
    storage = MagicMock()
    orchestrator = Orchestrator(
        config_repository=repo,
        scheduler=scheduler,
        thread_pool=thread_pool,
        storage=storage,
    )
    return orchestrator


def test_enrich_record_fills_defaults(orchestrator, sample_source_config, monkeypatch, snapshot) -> None:
    monkeypatch.setattr("intelli_crawler.orchestrator.datetime", FixedDatetime)
    source = sample_source_config()
    data = {"title": "Insight", "content": "Useful content " * 5}
    enriched = orchestrator._enrich_record(data, source, "https://example.com/insight")
    snapshot.assert_match(
        {
            "url": enriched["url"],
            "source_name": enriched["source_name"],
            "site_type": enriched["site_type"],
            "summary": enriched["summary"],
            "fetched_at": enriched["fetched_at"],
        },
        key="enriched_record",
    )


def test_extract_odaily_payload(orchestrator, sample_source_config, monkeypatch, snapshot) -> None:
    monkeypatch.setattr("intelli_crawler.orchestrator.datetime", FixedDatetime)
    detail = {
        "initData": {
            "detail": {
                "title": "Flash News",
                "description": "Market update",
                "newsUrl": "https://odaily.com/flash",
                "publishTimestamp": 1716206400000,
            }
        }
    }
    raw_html = f"<html><body>{json.dumps(detail)}</body></html>"
    extracted = orchestrator._extract_odaily_from_html(raw_html)
    snapshot.assert_match(extracted, key="odaily_extract")


def test_validate_record(orchestrator, sample_source_config) -> None:
    valid, reason = orchestrator._validate_record({"title": "T", "content": "C" * 50})
    assert valid and reason is None
    assert orchestrator._validate_record({"title": "", "content": "C" * 50}) == (False, "missing_title")
    assert orchestrator._validate_record({"title": "T", "content": "short"}) == (False, "content_too_short")


def test_deduplication_store_factory(sample_global_config, sample_source_config, tmp_path) -> None:
    storage = SQLiteManager()
    global_cfg = sample_global_config.model_copy(update={"history_dir": tmp_path / "history"})
    source = sample_source_config(
        deduplication=DeduplicationConfig(by_url=True, by_content=False, store_path="custom.db")
    )
    store = DeduplicationStoreFactory.build(storage, global_cfg, source)
    assert store.enable_url is True
    assert store.enable_content is False
    assert store.db_path.name == "custom.db"
