from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from intelli_crawler.config import ScheduleConfig, ScheduleType
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from intelli_crawler.scheduler import APSchedulerAdapter




class _FixedDatetime(datetime):
    @classmethod
    def utcnow(cls):
        return cls(2024, 1, 1, 10, 0, 0)


def test_build_triggers(sample_source_config) -> None:
    adapter = APSchedulerAdapter()
    source_cron = sample_source_config(
        schedule=ScheduleConfig(type=ScheduleType.CRON, value="*/5 * * * *")
    )
    cron_trigger = adapter._build_trigger(source_cron)
    assert isinstance(cron_trigger, CronTrigger)

    source_interval = sample_source_config(
        schedule=ScheduleConfig(type=ScheduleType.INTERVAL, value=30)
    )
    interval_trigger = adapter._build_trigger(source_interval)
    assert isinstance(interval_trigger, IntervalTrigger)
    assert interval_trigger.interval.total_seconds() == 30

    future = (datetime.utcnow() + timedelta(minutes=5)).isoformat()
    source_once = sample_source_config(
        schedule=ScheduleConfig(type=ScheduleType.ONCE, value=future)
    )
    once_trigger = adapter._build_trigger(source_once)
    assert isinstance(once_trigger, DateTrigger)


def test_schedule_source_uses_scheduler(sample_source_config, monkeypatch, snapshot) -> None:
    adapter = APSchedulerAdapter()
    calls: list[dict] = []
    monkeypatch.setattr("intelli_crawler.scheduler.apsched_adapter.datetime", _FixedDatetime)

    class StubScheduler:
        def add_job(self, callback, trigger, id, args, replace_existing):  # noqa: ANN001
            calls.append(
                {
                    "id": id,
                    "args": args,
                    "trigger": str(trigger),
                    "callback": callback,
                    "replace_existing": replace_existing,
                }
            )

        def get_jobs(self):
            return []

        def start(self):
            calls.append({"event": "started"})

        def shutdown(self, wait=False):  # noqa: ARG002
            calls.append({"event": "shutdown"})

        def remove_job(self, job_id):  # noqa: ANN001
            calls.append({"event": "remove", "id": job_id})

    stub = StubScheduler()
    adapter.scheduler = stub  # type: ignore[assignment]
    source = sample_source_config(source_name="AdapterCase")
    adapter.schedule_source(source, lambda s: s)
    assert calls[0]["id"] == f"source::{source.source_name}"
    adapter.start()
    adapter.remove_source(source.source_name)
    adapter.shutdown()
    serialisable = []
    for entry in calls:
        formatted = dict(entry)
        if "args" in formatted:
            formatted["args"] = [getattr(arg, "source_name", str(arg)) for arg in formatted["args"]]
        if "callback" in formatted:
            formatted["callback"] = getattr(formatted["callback"], "__name__", repr(formatted["callback"]))
        serialisable.append(formatted)
    snapshot.assert_match(serialisable, key="schedule_calls")


def test_interval_requires_numeric(sample_source_config) -> None:
    source = sample_source_config(
        schedule=ScheduleConfig(type=ScheduleType.INTERVAL, value={"minutes": 2})
    )
    adapter = APSchedulerAdapter()
    trigger = adapter._build_trigger(source)
    assert isinstance(trigger, IntervalTrigger)
    assert trigger.interval.total_seconds() == 120
    with pytest.raises(ValueError):
        adapter._build_trigger(
            sample_source_config(schedule=ScheduleConfig(type=ScheduleType.INTERVAL, value="fast"))
        )
