"""Pydantic models used across Intelli-Crawler configuration flow."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Literal, Union

from pydantic import BaseModel, Field, field_validator, model_validator


class SiteType(str, Enum):
    """Supported site categories."""

    NEWS = "news"
    SOCIAL = "social"


class ScheduleType(str, Enum):
    """Scheduler modes allowed by requirements."""

    CRON = "cron"
    INTERVAL = "interval"
    ONCE = "once"


class ScheduleConfig(BaseModel):
    """Configuration describing when a source should run."""

    type: ScheduleType = Field(default=ScheduleType.ONCE)
    value: Any = Field(
        default=None,
        description="Cron expression, interval seconds or ISO datetime, depending on type.",
    )

    @model_validator(mode="after")
    def _validate_value(self) -> "ScheduleConfig":
        if self.type is ScheduleType.CRON and not isinstance(self.value, str):
            raise ValueError("Cron schedule requires string expression")
        if self.type is ScheduleType.INTERVAL and not isinstance(self.value, (int, float, dict)):
            raise ValueError("Interval schedule requires seconds (int/float) or kwargs dict")
        if (
            self.type is ScheduleType.ONCE
            and self.value is not None
            and not isinstance(self.value, str)
        ):
            raise ValueError("Once schedule expects ISO datetime string or null")
        return self


class TimeRange(BaseModel):
    """时间范围配置，支持固定日期和相对时间表达式。

    支持的格式：
    1. 固定日期范围：start: 2025-01-14, end: 2025-01-15
    2. 相对时间表达式：relative: "last_24_hours" 或 "last_7_days"
    """

    start: date | None = None
    end: date | None = None
    relative: str | None = None

    @model_validator(mode="after")
    def _validate_range(self) -> "TimeRange":
        """验证时间范围配置的有效性"""
        # 检查是否同时配置了固定日期和相对时间
        has_fixed = self.start is not None and self.end is not None
        has_relative = self.relative is not None

        if has_fixed and has_relative:
            raise ValueError("不能同时配置固定日期范围和相对时间表达式")

        if not has_fixed and not has_relative:
            raise ValueError("必须配置固定日期范围或相对时间表达式")

        # 验证固定日期范围
        if has_fixed:
            if self.end < self.start:
                raise ValueError("结束日期不能早于开始日期")

        # 验证相对时间表达式
        if has_relative:
            valid_relatives = ["last_24_hours", "last_7_days", "last_30_days"]
            if self.relative not in valid_relatives:
                raise ValueError(
                    f"不支持的相对时间表达式: {self.relative}，支持的格式: {valid_relatives}"
                )

        return self

    def get_date_range(self, reference_time: datetime | None = None) -> tuple[date, date]:
        """获取实际的日期范围

        Args:
            reference_time: 参考时间，默认为当前时间

        Returns:
            tuple[date, date]: (开始日期, 结束日期)
        """
        if self.start is not None and self.end is not None:
            # 固定日期范围
            return self.start, self.end

        if self.relative is not None:
            # 相对时间表达式
            if reference_time is None:
                reference_time = datetime.now()

            if self.relative == "last_24_hours":
                end_date = reference_time.date()
                start_date = (reference_time - timedelta(days=1)).date()
            elif self.relative == "last_7_days":
                end_date = reference_time.date()
                start_date = (reference_time - timedelta(days=7)).date()
            elif self.relative == "last_30_days":
                end_date = reference_time.date()
                start_date = (reference_time - timedelta(days=30)).date()
            else:
                raise ValueError(f"不支持的相对时间表达式: {self.relative}")

            return start_date, end_date

        raise ValueError("时间范围配置无效")


class LoginCredentials(BaseModel):
    """Login credentials stored per source; password kept optional."""

    username: str = ""
    password: str = ""


class AntiScrapingStrategies(BaseModel):
    """Feature flags and parameters governing anti-bot strategy chain."""

    user_agent_rotation: bool = False
    proxy_pool: bool = False
    delay_range: tuple[float, float] = (0.0, 0.0)
    retry_on_fail: int = 0
    use_headless_browser: bool = False
    captcha_solver: bool = False
    # 新增stealth相关参数
    use_stealth_js: bool = False
    randomize_viewport: bool = False
    fake_webdriver: bool = False
    hide_automation_flags: bool = False
    viewport_size: tuple[int, int] = (1920, 1080)
    extra_headers: dict[str, str] = Field(default_factory=dict)
    # 新增浏览器模式控制
    headless_mode: bool = True  # 控制是否使用无头模式
    page_timeout: int = 30000  # 页面超时设置（毫秒）
    navigation_timeout: int = 30000  # 导航超时设置（毫秒）

    @field_validator("delay_range", mode="before")
    @classmethod
    def _coerce_delay(cls, value: Any) -> tuple[float, float]:
        if value in (None, ""):
            return (0.0, 0.0)
        if isinstance(value, (list, tuple)) and len(value) == 2:
            low, high = float(value[0]), float(value[1])
            if low < 0 or high < 0:
                raise ValueError("Delay range values must be non-negative")
            if high < low:
                raise ValueError("Delay range upper bound must be >= lower bound")
            return (low, high)
        raise ValueError("Delay range expects a two-item list or tuple")


class DeduplicationConfig(BaseModel):
    """Per-source deduplication settings."""

    by_url: bool = True
    by_content: bool = True
    store_path: Path = Field(default=Path("data/history/default_history.db"))

    @field_validator("store_path", mode="before")
    @classmethod
    def _coerce_path(cls, value: Any) -> Path:
        return Path(value)


class SourceConfig(BaseModel):
    """Full definition of a scrape source."""

    source_name: str
    site_type: SiteType
    target_url: str
    requires_login: bool = False
    login_credentials: LoginCredentials = Field(default_factory=LoginCredentials)
    crawl_depth: int = 1
    entry_pattern: str
    detail_pattern: dict[str, str | list[str]] = Field(default_factory=dict)
    keywords_filter: list[str] = Field(default_factory=list)
    output_format: Literal["json", "csv", "txt", "mongodb", "sqlite"] = "json"
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    time_range: TimeRange | None = None
    anti_scraping_strategies: AntiScrapingStrategies = Field(default_factory=AntiScrapingStrategies)
    enable_incremental: bool = True
    use_entry_content: bool = False
    deduplication: DeduplicationConfig = Field(default_factory=DeduplicationConfig)

    # Entry page interactions for dynamic content (optional)
    # - wait_selector: CSS selector to wait for after navigation
    # - scroll_rounds: number of times to scroll to page bottom to load more
    # - scroll_pause_ms: pause between scrolls in milliseconds
    # - click_more_selector: CSS selector for a "load more" button
    # - click_more_times: number of clicks to attempt
    # - click_wait_selector: selector to wait after each click
    class EntryInteractions(BaseModel):
        wait_selector: str | None = None
        scroll_rounds: int = 0
        scroll_pause_ms: int = 300
        click_more_selector: str | None = None
        click_more_times: int = 0
        click_wait_selector: str | None = None
        # 自动入口交互：智能选择滚动与点击
        auto: bool = False
        auto_max_rounds: int = 20
        auto_stall_rounds: int = 3
        prefer_scroll_first: bool = True

        @model_validator(mode="after")
        def _validate_non_negative(self) -> "SourceConfig.EntryInteractions":
            if self.scroll_rounds < 0:
                raise ValueError("scroll_rounds must be >= 0")
            if self.scroll_pause_ms < 0:
                raise ValueError("scroll_pause_ms must be >= 0")
            if self.click_more_times < 0:
                raise ValueError("click_more_times must be >= 0")
            if self.auto_max_rounds < 0:
                raise ValueError("auto_max_rounds must be >= 0")
            if self.auto_stall_rounds < 0:
                raise ValueError("auto_stall_rounds must be >= 0")
            return self

    entry_interactions: EntryInteractions = Field(default_factory=EntryInteractions)

    @model_validator(mode="after")
    def _validate_patterns(self) -> "SourceConfig":
        if self.crawl_depth < 1:
            raise ValueError("crawl_depth must be >= 1")
        if not self.entry_pattern:
            raise ValueError("entry_pattern cannot be empty")
        return self

    def resolved_history_path(self, base_dir: Path) -> Path:
        """Return deduplication store path relative to project data directory."""

        history_path = self.deduplication.store_path
        if not history_path.is_absolute():
            return (base_dir / history_path).resolve()
        return history_path


class ProxyPoolConfig(BaseModel):
    """Permutation of proxy pool options."""

    enabled: bool = False
    source: str | None = None
    refresh_interval: int | None = None


class GlobalConfig(BaseModel):
    """Global controls shared across sources."""

    proxy_pool: ProxyPoolConfig = Field(default_factory=ProxyPoolConfig)
    user_agent_list: list[str] | Path | None = None
    default_delay_range: tuple[float, float] = (1.0, 3.0)
    enable_progress_bar: bool = True
    show_live_status: bool = False
    max_url_display_length: int = 80
    thread_pool_workers: int = 16
    history_dir: Path = Field(default=Path("data/history"))
    outputs_dir: Path = Field(default=Path("data/outputs"))
    sources_dir: Path = Field(default=Path("data/sources"))

    @field_validator("default_delay_range", mode="before")
    @classmethod
    def _coerce_default_delay(cls, value: Any) -> tuple[float, float]:
        if isinstance(value, (list, tuple)) and len(value) == 2:
            low, high = float(value[0]), float(value[1])
            if high < low:
                raise ValueError("default_delay_range upper bound must be >= lower bound")
            return (low, high)
        raise ValueError("default_delay_range expects two items [low, high]")

    @field_validator("history_dir", "outputs_dir", "sources_dir", mode="before")
    @classmethod
    def _coerce_dirs(cls, value: Any) -> Path:
        return Path(value)

    @model_validator(mode="after")
    def _apply_user_agents(self) -> "GlobalConfig":
        if isinstance(self.user_agent_list, Path):
            if not self.user_agent_list.exists():
                raise ValueError(f"UA file not found: {self.user_agent_list}")
            content = self.user_agent_list.read_text(encoding="utf-8").splitlines()
            self.user_agent_list = [line.strip() for line in content if line.strip()]
        return self


__all__ = [
    "AntiScrapingStrategies",
    "ApiFetchConfig",
    "DeduplicationConfig",
    "GlobalConfig",
    "LoginCredentials",
    "ProxyPoolConfig",
    "ScheduleConfig",
    "ScheduleType",
    "SiteType",
    "SourceConfig",
    "TimeRange",
]
