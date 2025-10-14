"""APScheduler wrapper exposing higher level helpers."""

from __future__ import annotations

from datetime import datetime
from typing import Callable

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from ..config import ScheduleType, SourceConfig
from ..logging_conf import configure_logging


class APSchedulerAdapter:
    """Manage APScheduler jobs for configured sources."""

    def __init__(self) -> None:
        self.scheduler = BackgroundScheduler()
        self.logger = configure_logging().bind(component="scheduler")
        self.started = False

    def start(self) -> None:
        if not self.started:
            self.scheduler.start()
            self.started = True
            self.logger.info("apscheduler_started")

    def shutdown(self) -> None:
        if self.started:
            self.scheduler.shutdown(wait=False)
            self.started = False
            self.logger.info("apscheduler_stopped")

    def schedule_source(self, source: SourceConfig, callback: Callable[[SourceConfig], None]) -> None:
        trigger = self._build_trigger(source)
        job_id = f"source::{source.source_name}"
        self.scheduler.add_job(callback, trigger=trigger, id=job_id, args=[source], replace_existing=True)
        self.logger.info("job_scheduled", source=source.source_name, schedule=source.schedule.model_dump())

    def remove_source(self, source_name: str) -> None:
        job_id = f"source::{source_name}"
        try:
            self.scheduler.remove_job(job_id)
        except Exception:  # noqa: BLE001
            self.logger.warning("job_remove_failed", source=source_name)

    def _build_trigger(self, source: SourceConfig):
        schedule = source.schedule
        if schedule.type is ScheduleType.CRON:
            return CronTrigger.from_crontab(str(schedule.value))
        if schedule.type is ScheduleType.INTERVAL:
            if isinstance(schedule.value, (int, float)):
                return IntervalTrigger(seconds=float(schedule.value))
            if isinstance(schedule.value, dict):
                return IntervalTrigger(**schedule.value)
            raise ValueError("Interval schedule requires seconds or kwargs dict")
        if schedule.type is ScheduleType.ONCE:
            if schedule.value:
                run_date = datetime.fromisoformat(str(schedule.value))
            else:
                run_date = datetime.utcnow()
            return DateTrigger(run_date=run_date)
        raise ValueError(f"Unknown schedule type: {schedule.type}")

    def list_jobs(self) -> list[dict]:
        jobs = []
        for job in self.scheduler.get_jobs():
            jobs.append(
                {
                    "id": job.id,
                    "next_run_time": job.next_run_time,
                    "trigger": str(job.trigger),
                }
            )
        return jobs


__all__ = ["APSchedulerAdapter"]
