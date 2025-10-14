from __future__ import annotations

from pathlib import Path

import pytest

from intelli_crawler.config.loader import ConfigLocator, ConfigRepository, _slugify
from intelli_crawler.config.models import GlobalConfig


def test_config_locator_uses_env_and_creates_directories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, snapshot
) -> None:
    monkeypatch.setenv("INTELLI_CRAWLER_HOME", str(tmp_path))
    locator = ConfigLocator()
    data = {
        "project_root": str(locator.project_root.relative_to(tmp_path)),
        "history_dir": str(locator.history_dir.relative_to(tmp_path)),
        "outputs_dir": str(locator.outputs_dir.relative_to(tmp_path)),
        "sources_dir": str(locator.sources_dir.relative_to(tmp_path)),
        "logs_dir": str(locator.logs_dir.relative_to(tmp_path)),
        "global_config": str(locator.global_config_path().relative_to(tmp_path)),
    }
    for path in (locator.history_dir, locator.outputs_dir, locator.sources_dir, locator.logs_dir):
        assert path.exists()
    snapshot.assert_match(data, key="locator_paths")


def test_config_repository_global_roundtrip(tmp_path: Path, snapshot) -> None:
    locator = ConfigLocator(project_root=tmp_path)
    repo = ConfigRepository(locator)
    config = GlobalConfig(
        default_delay_range=(0.2, 0.4),
        enable_progress_bar=False,
    )
    repo.save_global_config(config)
    loaded = repo.load_global_config()
    assert loaded == config
    snapshot.assert_match(loaded.model_dump(mode="json"), key="global_config_roundtrip")


def test_config_repository_source_cycle(temp_config_repository: ConfigRepository, snapshot, sample_source_config) -> None:
    source = sample_source_config(
        source_name="DeepTech",
        target_url="https://example.com/deep",
        detail_pattern={"title": "h1::text", "content": "article ::html"},
    )
    path = temp_config_repository.save_source(source)
    assert path.exists()
    loaded = temp_config_repository.load_source(source.source_name)
    snapshot.assert_match(loaded.model_dump(mode="json"), key="source_roundtrip")


def test_config_repository_missing_source(temp_config_repository: ConfigRepository) -> None:
    with pytest.raises(FileNotFoundError):
        temp_config_repository.load_source("missing")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Example Source", "example-source"),
        ("Already-Slug", "already-slug"),
        ("C++ Archive", "c---archive"),
    ],
)
def test_slugify_behaviour(raw: str, expected: str) -> None:
    assert _slugify(raw) == expected
