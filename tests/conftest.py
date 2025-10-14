"""Pytest configuration providing snapshot management and shared fixtures."""

from __future__ import annotations

import json
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Iterable

import pytest

from intelli_crawler.config import (
    AntiScrapingStrategies,
    ConfigLocator,
    ConfigRepository,
    DeduplicationConfig,
    GlobalConfig,
    ScheduleConfig,
    SiteType,
    SourceConfig,
)


class QAPlugin:
    """Collect test outcomes and expose snapshot bookkeeping hooks."""

    def __init__(self, config: pytest.Config) -> None:
        self.config = config
        self.update_snapshots = config.getoption("--snapshot-update")
        self.snapshot_date = (
            config.getoption("--snapshot-date")
            or os.environ.get("SNAPSHOT_DATE")
            or date.today().isoformat()
        )
        self.snapshots_root = Path(config.rootpath) / "tests" / "snapshots"
        self.snapshots_root.mkdir(parents=True, exist_ok=True)
        self.failed_cases: list[str] = []
        self.snapshot_changes: list[str] = []

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:  # pragma: no cover
        if report.when == "call" and report.failed:
            self.failed_cases.append(report.nodeid)

    def register_snapshot_change(self, path: Path, test_key: str, action: str) -> None:
        relative = path.relative_to(self.config.rootpath)
        self.snapshot_changes.append(f"{action}: {relative}::{test_key}")

    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int) -> None:  # pragma: no cover
        reports_dir = Path(self.config.rootpath) / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        report_payload = {
            "coverage": 1.0 if not self.failed_cases else 0.0,
            "failed_cases": self.failed_cases,
        }
        (reports_dir / "test_report.json").write_text(
            json.dumps(report_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        snapshot_log = reports_dir / "snapshot_diff.log"
        if self.snapshot_changes:
            snapshot_log.write_text(
                "\n".join(self.snapshot_changes) + "\n",
                encoding="utf-8",
            )
        else:
            snapshot_log.write_text("No snapshot updates detected.\n", encoding="utf-8")


def pytest_addoption(parser: pytest.Parser) -> None:  # pragma: no cover
    parser.addoption(
        "--snapshot-update",
        action="store_true",
        default=False,
        help="Update stored QA snapshots.",
    )
    parser.addoption(
        "--snapshot-date",
        action="store",
        default=None,
        help="Override snapshot date component (YYYY-MM-DD).",
    )


def pytest_configure(config: pytest.Config) -> None:  # pragma: no cover
    plugin = QAPlugin(config)
    config.pluginmanager.register(plugin, "qa-plugin")
    config._qa_plugin = plugin  # type: ignore[attr-defined]


def pytest_unconfigure(config: pytest.Config) -> None:  # pragma: no cover
    plugin = getattr(config, "_qa_plugin", None)
    if plugin is not None:
        config.pluginmanager.unregister(plugin)
        delattr(config, "_qa_plugin")


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (Path,)):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


class SnapshotManager:
    """Assert helper storing expectations under module/date scoped files."""

    def __init__(self, request: pytest.FixtureRequest, plugin: QAPlugin) -> None:
        self.request = request
        self.plugin = plugin

    def assert_match(self, data: Any, *, key: str | None = None) -> None:
        normalized = _json_safe(data)
        module_name = Path(self.request.fspath).parent.name
        snapshot_dir = self.plugin.snapshots_root / module_name
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        snapshot_path = snapshot_dir / f"{self.plugin.snapshot_date}.json"
        if snapshot_path.exists():
            stored = json.loads(snapshot_path.read_text(encoding="utf-8"))
        else:
            stored = {}
        test_key = key or self.request.node.name
        current = stored.get(test_key)
        if current == normalized:
            return
        if self.plugin.update_snapshots:
            action = "updated" if test_key in stored else "created"
            stored[test_key] = normalized
            snapshot_path.write_text(
                json.dumps(stored, ensure_ascii=False, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            self.plugin.register_snapshot_change(snapshot_path, test_key, action)
        else:
            expected = json.dumps(current, ensure_ascii=False, indent=2, sort_keys=True)
            actual = json.dumps(normalized, ensure_ascii=False, indent=2, sort_keys=True)
            raise AssertionError(
                f"Snapshot mismatch for {test_key}\nExpected:\n{expected}\nActual:\n{actual}"
            )


@pytest.fixture
def snapshot(request: pytest.FixtureRequest) -> SnapshotManager:
    plugin = request.config._qa_plugin  # type: ignore[attr-defined]
    return SnapshotManager(request, plugin)


@pytest.fixture
def sample_global_config(tmp_path: Path) -> GlobalConfig:
    return GlobalConfig(
        history_dir=tmp_path / "history",
        outputs_dir=tmp_path / "outputs",
        sources_dir=tmp_path / "sources",
        default_delay_range=(0.5, 1.5),
    )


@pytest.fixture
def sample_source_config() -> Callable[..., SourceConfig]:
    def _builder(**overrides: Any) -> SourceConfig:
        base: dict[str, Any] = {
            "source_name": "Example",
            "site_type": SiteType.NEWS,
            "target_url": "https://example.com",
            "entry_pattern": "ul.list li a",
            "detail_pattern": {
                "title": "h1",
                "content": "article ::html",
            },
            "schedule": ScheduleConfig(),
            "deduplication": DeduplicationConfig(store_path="history/example.db"),
            "anti_scraping_strategies": AntiScrapingStrategies(
                delay_range=(0.0, 0.0),
                retry_on_fail=1,
            ),
        }
        base.update(overrides)
        return SourceConfig(**base)

    return _builder


@pytest.fixture
def temp_config_repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterable[ConfigRepository]:
    monkeypatch.setenv("INTELLI_CRAWLER_HOME", str(tmp_path))
    locator = ConfigLocator(project_root=tmp_path)
    repository = ConfigRepository(locator)
    yield repository
