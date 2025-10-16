"""Task orchestrator wiring together fetching, parsing, dedup, export, and progress."""

from __future__ import annotations

from concurrent.futures import Future, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Callable, Iterable
import json
import textwrap
from urllib.parse import urlparse

import structlog
from rich.console import Console

from .config import ConfigRepository, GlobalConfig, SourceConfig
from .engine import DeduplicationStore, FetchRequest, Fetcher, Parser, ThreadPoolManager
from .engine.exporter import BaseExporter, FileExporter, MongoExporter, SQLiteExporter
from .infra import ProxyPool, SQLiteManager, UserAgentPool
from .logging_conf import configure_logging, source_logger
from .ui import ProgressReporter, ProgressActivity


@dataclass(slots=True)
class CrawlWindow:
    """Concrete UTC-normalised time window for filtering crawl results."""

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        self.start = self._normalise(self.start)
        self.end = self._normalise(self.end)
        if self.end <= self.start:
            raise ValueError("CrawlWindow end must be greater than start")

    @staticmethod
    def _normalise(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def as_tuple(self) -> tuple[datetime, datetime]:
        return self.start, self.end


class Orchestrator:
    """Central coordinator managing lifecycle of crawl tasks."""

    def __init__(
        self,
        config_repository: ConfigRepository,
        scheduler,
        thread_pool: ThreadPoolManager,
        storage: SQLiteManager,
        proxy_pool: ProxyPool | None = None,
        ua_pool: UserAgentPool | None = None,
    ) -> None:
        self.config_repository = config_repository
        self.global_config: GlobalConfig = config_repository.load_global_config()
        self.scheduler = scheduler
        self.thread_pool = thread_pool
        self.storage = storage
        self.proxy_pool = proxy_pool
        self.ua_pool = ua_pool
        self.logger = configure_logging().bind(component="orchestrator")
        self._export_lock = Lock()
        # 控制台用于在部分终端打印可见的文本进度行
        try:
            self._console = Console()
        except Exception:
            self._console = None

    # ------------------------------------------------------------------
    def register_schedules(self, sources: Iterable[SourceConfig]) -> None:
        for source in sources:
            self.scheduler.schedule_source(source, self.run_source_async)
        self.scheduler.start()

    def run_source_async(self, source: SourceConfig) -> None:
        self.thread_pool.get().submit(lambda: self.run_source(source.source_name))

    def run_source(
        self,
        source_name: str,
        progress_enabled: bool | None = None,
        progress_factory: Callable[[str], "ProgressReporter"] | None = None,
        window: CrawlWindow | None = None,
    ) -> dict:
        source = self.config_repository.load_source(source_name)
        source_log = source_logger(source.source_name)
        # 过滤窗口提示
        if window:
            source_log.info(
                "using_crawl_window",
                window_start=window.start.isoformat(),
                window_end=window.end.isoformat(),
            )
        # 进度条开关：若入参提供则尊重；默认开启
        progress_flag = True if progress_enabled is None else bool(progress_enabled)
        if progress_factory and progress_flag:
            progress = progress_factory(source.source_name)
        else:
            progress = ProgressReporter(enabled=progress_flag)
        if hasattr(progress, "set_label"):
            try:
                progress.set_label(source.source_name)
            except Exception:
                pass
        fetcher = Fetcher(self.global_config, self.proxy_pool, self.ua_pool, logger=source_log)
        parser = Parser()
        run_tag = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        exporter = self._create_exporter(source, run_tag)
        dedup_store = DeduplicationStoreFactory.build(self.storage, self.global_config, source)

        summary: dict[str, int] = {"success": 0, "failed": 0, "skipped": 0, "window_filtered": 0}

        try:
            # 在未知总量阶段先显示不确定进度（活动指示器或多源任务占位）
            indeterminate_supported = hasattr(progress, "start_indeterminate")
            entry_activity: ProgressActivity | None = None
            if indeterminate_supported:
                # 多源进度：创建任务并显示旋转指示器
                try:
                    progress.start_indeterminate()  # type: ignore[attr-defined]
                except Exception:
                    pass
            else:
                # 单源进度：使用 Rich 状态旋转指示器
                entry_activity = ProgressActivity(enabled=progress_flag)
                entry_activity.start("正在获取入口页面（可能使用无头浏览器），请稍候…")

            entry_response = fetcher.fetch(
                source,
                FetchRequest(
                    url=source.target_url,
                    force_browser=source.use_entry_content,
                    # 为动态入口页在浏览器中等待列表选择器渲染完成
                    wait_selector=(
                        source.entry_interactions.wait_selector or source.entry_pattern
                        if source.use_entry_content
                        else None
                    ),
                    # 入口滚动与点击交互（可选）
                    scroll_rounds=source.entry_interactions.scroll_rounds,
                    scroll_pause_ms=source.entry_interactions.scroll_pause_ms,
                    click_more_selector=source.entry_interactions.click_more_selector,
                    click_more_times=source.entry_interactions.click_more_times,
                    click_wait_selector=source.entry_interactions.click_wait_selector,
                    auto_interactions=source.entry_interactions.auto,
                    auto_max_rounds=source.entry_interactions.auto_max_rounds,
                    auto_stall_rounds=source.entry_interactions.auto_stall_rounds,
                    prefer_scroll_first=source.entry_interactions.prefer_scroll_first,
                ),
            )
            if entry_activity is not None:
                entry_activity.close()
            detail_urls = parser.parse_entries(source, entry_response.text, entry_response.url)
            if not detail_urls:
                detail_urls = [source.target_url]
            initial_total = len(detail_urls)

            # 简洁进度条显示
            def _bar(done: int, total: int, width: int = 20) -> str:
                filled = int(width * (done / total)) if total > 0 else 0
                return "#" * filled + "." * (width - filled)

            # 在确定总量后，切换到确定进度（若支持）；否则初始化单源进度
            try:
                if hasattr(progress, "set_total"):
                    progress.set_total(initial_total)  # type: ignore[attr-defined]
                elif hasattr(progress, "start"):
                    progress.start(initial_total)  # type: ignore[attr-defined]
            except Exception:
                # 进度切换失败不影响抓取流程
                pass

            prefetched_records: dict[str, dict[str, object]] = {}
            if source.use_entry_content:
                hostname = urlparse(entry_response.url).hostname or ""
                if "foresightnews.pro" in hostname:
                    prefetched_records = parser.extract_foresight_records(
                        entry_response.text, entry_response.url
                    )
                elif "odaily.news" in hostname:
                    prefetched_records = parser.extract_odaily_records(
                        entry_response.text, entry_response.url
                    )
                elif "xueqiu.com" in hostname:
                    prefetched_records = parser.extract_xueqiu_records(
                        entry_response.text, entry_response.url
                    )
                else:
                    # 通用入口页记录抽取：使用 entry_pattern 与 detail_pattern 从列表页直接产出记录
                    try:
                        prefetched_records = parser.extract_list_records(source, entry_response.text, entry_response.url)  # type: ignore[assignment]
                    except Exception:
                        prefetched_records = {}
            if prefetched_records:
                detail_urls = list(prefetched_records.keys())

            if source.enable_incremental:
                filtered_urls: list[str] = []
                dedup_skipped = 0
                for target_url in detail_urls:
                    if dedup_store.has_url(target_url):
                        dedup_skipped += 1
                    else:
                        filtered_urls.append(target_url)
                if dedup_skipped:
                    summary["skipped"] += dedup_skipped
                detail_urls = filtered_urls
                if prefetched_records:
                    prefetched_records = {
                        url: prefetched_records[url]
                        for url in detail_urls
                        if url in prefetched_records
                    }

            if not detail_urls:
                return summary

            # 现在已知总量：若先前为不确定任务，则设置总量；否则正常启动进度条
            if indeterminate_supported:
                try:
                    progress.set_total(len(detail_urls))  # type: ignore[attr-defined]
                except Exception:
                    pass
            else:
                progress.start(total=len(detail_urls))

            max_workers = 1 if source.anti_scraping_strategies.use_headless_browser else None
            completed = 0
            executor = self.thread_pool.get(source.source_name, max_workers=max_workers)
            futures: list[Future[ProcessingResult]] = []
            for detail_url in detail_urls:
                futures.append(
                    executor.submit(
                        self._process_detail,
                        fetcher,
                        parser,
                        dedup_store,
                        exporter,
                        source,
                        detail_url,
                        window,
                        prefetched_records.get(detail_url) if prefetched_records else None,
                    )
                )

            for future in as_completed(futures):
                result = future.result()
                if result.status == "success":
                    progress.advance(success=True, current_url=result.url)
                    summary["success"] += 1
                elif result.status == "skipped":
                    progress.advance(skipped=True, current_url=result.url)
                    summary["skipped"] += 1
                    if result.reason == "window_filtered":
                        summary["window_filtered"] += 1
                else:
                    progress.advance(failed=True, current_url=result.url)
                    summary["failed"] += 1
                completed += 1
        finally:
            progress.close()
            exporter.flush()
            exporter.close()
            fetcher.close()
        return summary

    def _process_detail(
        self,
        fetcher: Fetcher,
        parser: Parser,
        dedup_store: DeduplicationStore,
        exporter: BaseExporter,
        source: SourceConfig,
        url: str,
        window: CrawlWindow | None,
        prefetched: dict[str, object] | None = None,
    ) -> "ProcessingResult":
        try:
            if prefetched is not None:
                enriched = self._enrich_record(prefetched, source, url)
                valid, reason = self._validate_record(enriched, strict=False)
                if valid:
                    status = "success"
                    reason = None
                else:
                    status = "invalid"
            else:
                status, enriched, reason = self._fetch_and_validate(
                    fetcher, parser, source, url, force_browser=False
                )
            if status == "skipped":
                return ProcessingResult(status="skipped", url=url, reason=reason)
            if status == "invalid" and self._should_force_browser(source):
                try:
                    status, enriched, reason = self._fetch_and_validate(
                        fetcher, parser, source, url, force_browser=True
                    )
                except Exception as exc:  # noqa: BLE001
                    structlog.get_logger("intelli_crawler").warning(
                        "browser_fallback_failed",
                        url=url,
                        source=source.source_name,
                        error=str(exc),
                    )
                    status, reason = "failed", str(exc)
            if status != "success":
                return ProcessingResult(
                    status="failed", url=url, reason=reason or "validation_failed"
                )
            if window and not self._within_window(enriched, window, source.source_name):
                self.logger.info(
                    "window_filtered",
                    source=source.source_name,
                    url=url,
                    window_start=window.start.isoformat(),
                    window_end=window.end.isoformat(),
                )
                return ProcessingResult(status="skipped", url=url, reason="window_filtered")

            content_seed = enriched.get("content") or enriched.get("raw_html") or ""
            dedup_result = dedup_store.check_and_store(url, content_seed, source.source_name)
            if source.enable_incremental and dedup_result.is_duplicate:
                return ProcessingResult(status="skipped", url=url, reason="duplicate")
            with self._export_lock:
                exporter.export(enriched)
            return ProcessingResult(status="success", url=url, reason=None)
        except Exception as exc:  # noqa: BLE001
            structlog.get_logger("intelli_crawler").error(
                "detail_error", url=url, source=source.source_name, error=str(exc)
            )
            return ProcessingResult(status="failed", url=url, reason=str(exc))

    def _fetch_and_validate(
        self,
        fetcher: Fetcher,
        parser: Parser,
        source: SourceConfig,
        url: str,
        *,
        force_browser: bool,
    ) -> tuple[str, dict[str, object] | None, str | None]:
        response = fetcher.fetch(source, FetchRequest(url=url, force_browser=force_browser))
        record = parser.parse_detail(source, response.text, url)
        if not parser.filter_by_keywords(record, source.keywords_filter):
            return "skipped", None, "keyword"
        enriched = self._enrich_record(record.data, source, url)
        valid, reason = self._validate_record(enriched)
        if not valid:
            return "invalid", None, reason
        return "success", enriched, None

    def _enrich_record(
        self, data: dict[str, object], source: SourceConfig, url: str
    ) -> dict[str, object]:
        enriched = dict(data)
        enriched.setdefault("url", url)
        enriched.setdefault("source_name", source.source_name)
        enriched["site_type"] = source.site_type.value
        enriched.setdefault("fetched_at", datetime.utcnow().isoformat(timespec="seconds") + "Z")
        if not enriched.get("content"):
            odaily = self._extract_odaily_from_html(enriched.get("raw_html"))
            if odaily:
                for key, value in odaily.items():
                    if value:
                        enriched.setdefault(key, value)
        content = enriched.get("content")
        if isinstance(content, str):
            summary = textwrap.shorten(
                content.replace("\n", " ").strip(), width=240, placeholder="…"
            )
            enriched.setdefault("summary", summary)
        return enriched

    def _within_window(
        self, record: dict[str, object], window: CrawlWindow, source_name: str
    ) -> bool:
        timestamp = self._extract_record_datetime(record, fallback_year=window.start.year)
        if timestamp is None:
            self.logger.debug(
                "window_timestamp_missing",
                source=source_name,
                url=record.get("url"),
            )
            return True
        start, end = window.as_tuple()
        if start <= timestamp <= end:
            return True
        self.logger.debug(
            "window_out_of_range",
            source=source_name,
            url=record.get("url"),
            record_timestamp=timestamp.isoformat(),
            window_start=start.isoformat(),
            window_end=end.isoformat(),
        )
        return False

    def _extract_record_datetime(
        self,
        record: dict[str, object],
        *,
        fallback_year: int | None = None,
    ) -> datetime | None:
        timestamp_fields = (
            "published_at",
            "published_at_utc",
            "publish_time",
            "publishTimestamp",
            "timestamp",
            "time",
            "fetched_at",
        )
        for field in timestamp_fields:
            candidate = record.get(field)
            dt = self._coerce_datetime(candidate, fallback_year=fallback_year)
            if dt is not None:
                return dt
        return None

    def _coerce_datetime(
        self, value: object, *, fallback_year: int | None = None
    ) -> datetime | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            dt = value
        elif isinstance(value, (int, float)):
            numeric = float(value)
            if numeric > 1_000_000_000_000:  # assume milliseconds
                numeric /= 1000.0
            dt = datetime.fromtimestamp(numeric, tz=timezone.utc)
            return dt
        elif isinstance(value, str):
            text = value.strip()
            if not text:
                return None
            normalised = text
            if normalised.endswith("Z"):
                normalised = normalised[:-1] + "+00:00"
            try:
                dt = datetime.fromisoformat(normalised)
            except ValueError:
                for fmt in (
                    "%Y-%m-%d %H:%M:%S",
                    "%Y-%m-%d %H:%M",
                    "%Y/%m/%d %H:%M:%S",
                    "%Y/%m/%d %H:%M",
                    "%Y-%m-%d",
                    "%Y/%m/%d",
                    "%m-%d %H:%M",
                    "%m/%d %H:%M",
                ):
                    try:
                        parsed = datetime.strptime(normalised, fmt)
                    except ValueError:
                        continue
                    if "%Y" not in fmt:
                        year = fallback_year or datetime.utcnow().year
                        parsed = parsed.replace(year=year)
                    dt = parsed
                    break
                else:
                    return None
        else:
            return None
        if dt.tzinfo is None:
            local_tz = datetime.now().astimezone().tzinfo or timezone.utc
            dt = dt.replace(tzinfo=local_tz)
        return dt.astimezone(timezone.utc)

    def _extract_odaily_from_html(self, raw_html: object) -> dict[str, object] | None:
        if not isinstance(raw_html, str) or '"initData"' not in raw_html:
            return None
        try:
            marker_index = raw_html.find('"initData"')
            start = raw_html.rfind("{", 0, marker_index)
            if start == -1:
                return None
            brace_count = 0
            end = None
            for idx in range(start, len(raw_html)):
                ch = raw_html[idx]
                if ch == "{":
                    brace_count += 1
                elif ch == "}":
                    brace_count -= 1
                    if brace_count == 0:
                        end = idx + 1
                        break
            if end is None:
                return None
            payload = json.loads(raw_html[start:end])
            detail = payload.get("initData", {}).get("detail")
            if not isinstance(detail, dict):
                return None
            published_at = detail.get("publishTimestamp")
            if isinstance(published_at, (int, float)):
                published = datetime.fromtimestamp(published_at / 1000, tz=timezone.utc).isoformat()
            else:
                published = None
            return {
                "title": detail.get("title"),
                "content": detail.get("description"),
                "original_url": detail.get("newsUrl"),
                "published_at": published,
            }
        except Exception:
            return None

    def _validate_record(
        self, record: dict[str, object], *, strict: bool = True
    ) -> tuple[bool, str | None]:
        title = str(record.get("title") or "").strip()
        content = str(record.get("content") or "").strip()
        if not title:
            return False, "missing_title"
        if strict and len(content) < 40:
            return False, "content_too_short"
        return True, None

    def _should_force_browser(self, source: SourceConfig) -> bool:
        if source.anti_scraping_strategies.use_headless_browser:
            return True
        try:  # detect optional dependency
            import playwright  # noqa: F401
        except ImportError:
            return False
        return True

    def _create_exporter(self, source: SourceConfig, run_tag: str) -> BaseExporter:
        base_dir = Path(self.global_config.outputs_dir)
        base_dir.mkdir(parents=True, exist_ok=True)
        if source.output_format in {"json", "csv", "txt"}:
            return FileExporter(base_dir, source.source_name, source.output_format, run_tag=run_tag)
        if source.output_format == "mongodb":
            uri = "mongodb://localhost:27017"
            return MongoExporter(uri, database="intelli_crawler", collection=source.source_name)
        if source.output_format == "sqlite":
            path = base_dir / f"{source.source_name}.db"
            return SQLiteExporter(path)
        raise ValueError(f"Unsupported output format: {source.output_format}")

    def view_history(self, source_name: str, limit: int = 20) -> list[tuple[str, str]]:
        source = self.config_repository.load_source(source_name)
        path = source.resolved_history_path(self.global_config.history_dir)
        conn = self.storage.connect(path)
        rows = conn.execute(
            "SELECT url, timestamp FROM crawl_history WHERE source_name=? ORDER BY timestamp DESC LIMIT ?",
            (source.source_name, limit),
        ).fetchall()
        return [(row["url"], row["timestamp"]) for row in rows]

    def reset_history(self, source_name: str) -> None:
        source = self.config_repository.load_source(source_name)
        path = source.resolved_history_path(self.global_config.history_dir)
        self.storage.reset(path)


@dataclass(slots=True)
class ProcessingResult:
    status: str
    url: str
    reason: str | None


class DeduplicationStoreFactory:
    @staticmethod
    def build(
        storage: SQLiteManager, global_config: GlobalConfig, source: SourceConfig
    ) -> DeduplicationStore:
        history_path = source.resolved_history_path(Path(global_config.history_dir))
        return DeduplicationStore(
            storage,
            history_path,
            enable_url=source.deduplication.by_url,
            enable_content=source.deduplication.by_content,
        )


__all__ = ["Orchestrator", "CrawlWindow"]
