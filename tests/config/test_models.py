from __future__ import annotations

from pathlib import Path

import pytest

from intelli_crawler.config import (
    AntiScrapingStrategies,
    GlobalConfig,
    ScheduleConfig,
    ScheduleType,
    TimeRange,
)


def test_schedule_config_interval_requires_numeric() -> None:
    with pytest.raises(ValueError):
        ScheduleConfig(type=ScheduleType.INTERVAL)
    with pytest.raises(ValueError):
        ScheduleConfig(type=ScheduleType.INTERVAL, value="every minute")
    cfg = ScheduleConfig(type=ScheduleType.INTERVAL, value={"minutes": 2})
    assert cfg.value == {"minutes": 2}


def test_schedule_config_cron_requires_string() -> None:
    with pytest.raises(ValueError):
        ScheduleConfig(type=ScheduleType.CRON, value=5)


def test_time_range_validation() -> None:
    with pytest.raises(ValueError):
        TimeRange(start="2024-05-20", end="2024-05-19")  # type: ignore[arg-type]


def test_anti_scraping_delay_validation() -> None:
    strategies = AntiScrapingStrategies(delay_range=(1, 3))
    assert strategies.delay_range == (1.0, 3.0)
    with pytest.raises(ValueError):
        AntiScrapingStrategies(delay_range=(-1, 2))
    with pytest.raises(ValueError):
        AntiScrapingStrategies(delay_range=(3, 1))


def test_global_config_supports_user_agent_file(tmp_path: Path, snapshot) -> None:
    ua_file = tmp_path / "uas.txt"
    ua_file.write_text("UA-1\nUA-2\n", encoding="utf-8")
    config = GlobalConfig(user_agent_list=ua_file)
    snapshot.assert_match({"user_agents": config.user_agent_list}, key="ua_file_loaded")
