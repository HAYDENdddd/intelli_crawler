"""Typer CLI entrypoint for Intelli-Crawler."""

from __future__ import annotations

import json
import re
from contextlib import nullcontext
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, time as dt_time, timedelta, timezone
from pathlib import Path
from typing import Annotated, Iterable, Optional, Sequence

import typer
from typer import BadParameter
import typer.core as _typer_core
import typer.main as _typer_main

_OriginalTyperOption = _typer_core.TyperOption


class _ValueAwareTyperOption(_OriginalTyperOption):
    """Ensure non-boolean options always accept explicit values.

    Typer defaults certain optional declarations to flag-style options when
    no explicit flag value is provided. For our timestamp fields we always
    expect a value, so we coerce ``is_flag`` to ``False`` in that scenario.
    """

    def __init__(self, *, is_flag=None, flag_value=None, **kwargs):
        if is_flag is None and flag_value is None:
            is_flag = False
        super().__init__(is_flag=is_flag, flag_value=flag_value, **kwargs)


_typer_core.TyperOption = _ValueAwareTyperOption
_typer_main.TyperOption = _ValueAwareTyperOption
import yaml
from rich import box
from rich.console import Console
from rich.table import Table

from .config import ConfigRepository, ScheduleConfig, ScheduleType, SourceConfig
from .engine import ThreadPoolManager
from .infra import ProxyPool, SQLiteManager, UserAgentPool
from .logging_conf import available_source_logs, configure_logging, tail_log
from .orchestrator import CrawlWindow, Orchestrator
from .scheduler import APSchedulerAdapter
from .ui import ConfigWizard, MultiSourceProgress

app = typer.Typer(
    help="Intelli-Crawler 命令行工具",
    no_args_is_help=True,
    rich_markup_mode=None,
)
source_app = typer.Typer(
    name="source",
    help="信息源管理命令",
    no_args_is_help=True,
    rich_markup_mode=None,
)
log_app = typer.Typer(
    name="log",
    help="日志查看命令",
    no_args_is_help=True,
    rich_markup_mode=None,
)

console = Console()


@dataclass
class AppState:
    repository: ConfigRepository
    scheduler: APSchedulerAdapter
    orchestrator: Orchestrator
    wizard: ConfigWizard
    storage: SQLiteManager


_DURATION_PATTERN = re.compile(r"(?P<value>\d+)(?P<unit>[smhd])", re.IGNORECASE)


def _parse_datetime_option(value: str, option_name: str) -> datetime:
    text = value.strip()
    if not text:
        raise BadParameter(f"{option_name} 不能为空。")
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        candidate = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise BadParameter(
            f"{option_name} 需使用 ISO8601 时间，例如 2024-10-14T08:00+08:00。"
        ) from exc
    if candidate.tzinfo is None:
        candidate = candidate.replace(tzinfo=timezone.utc)
    else:
        candidate = candidate.astimezone(timezone.utc)
    return candidate


def _parse_time_option(value: str, option_name: str) -> dt_time:
    text = value.strip()
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            continue
    raise BadParameter(f"{option_name} 格式应为 HH:MM 或 HH:MM:SS。")


def _parse_duration_option(value: Optional[str], option_name: str) -> timedelta:
    if value is None:
        return timedelta(hours=24)
    spec = value.strip().lower()
    if not spec:
        raise BadParameter(f"{option_name} 不能为空。")
    if spec.isdigit():
        hours = int(spec)
        if hours <= 0:
            raise BadParameter(f"{option_name} 必须大于 0。")
        return timedelta(hours=hours)
    total = timedelta()
    index = 0
    for match in _DURATION_PATTERN.finditer(spec):
        if match.start() != index:
            raise BadParameter(f"{option_name} 不支持的时间跨度格式：{value}")
        magnitude = int(match.group("value"))
        unit = match.group("unit").lower()
        if magnitude <= 0:
            raise BadParameter(f"{option_name} 需大于 0。")
        if unit == "s":
            delta = timedelta(seconds=magnitude)
        elif unit == "m":
            delta = timedelta(minutes=magnitude)
        elif unit == "h":
            delta = timedelta(hours=magnitude)
        elif unit == "d":
            delta = timedelta(days=magnitude)
        else:  # pragma: no cover - 正则已限定
            raise BadParameter(f"{option_name} 不支持的单位：{unit}")
        total += delta
        index = match.end()
    if index != len(spec) or total <= timedelta():
        raise BadParameter(f"{option_name} 不支持的时间跨度格式：{value}")
    return total


def _resolve_window_options(
    since: Optional[str],
    until: Optional[str],
    window_start: Optional[str],
    window_duration: Optional[str],
) -> CrawlWindow | None:
    if not any((since, until, window_start, window_duration)):
        return None
    if window_start:
        if since or until:
            raise BadParameter("不能同时指定 --window-start 与 --since/--until。")
        start_time = _parse_time_option(window_start, "--window-start")
        duration = _parse_duration_option(window_duration, "--window-duration")
        reference_local = datetime.now().astimezone()
        anchor = datetime.combine(reference_local.date(), start_time, tzinfo=reference_local.tzinfo)
        if anchor > reference_local:
            anchor -= timedelta(days=1)
        end_local = anchor + duration
        return CrawlWindow(
            start=anchor.astimezone(timezone.utc),
            end=end_local.astimezone(timezone.utc),
        )
    if window_duration and not (since or until):
        raise BadParameter("--window-duration 需配合 --since/--until 或 --window-start 使用。")
    start_dt = _parse_datetime_option(since, "--since") if since else None
    end_dt = _parse_datetime_option(until, "--until") if until else None
    if start_dt is None and end_dt is None:
        raise BadParameter("请提供 --since、--until 或 --window-start。")
    if start_dt is None:
        fallback_end = end_dt or datetime.now(timezone.utc)
        duration = _parse_duration_option(window_duration, "--window-duration")
        start_dt = fallback_end - duration
    if end_dt is None:
        if window_duration:
            duration = _parse_duration_option(window_duration, "--window-duration")
            end_dt = start_dt + duration
        else:
            end_dt = datetime.now(timezone.utc)
    if end_dt <= start_dt:
        raise BadParameter("--until 必须晚于 --since。")
    return CrawlWindow(start=start_dt, end=end_dt)


def _render_window_summary(window: CrawlWindow) -> Table:
    local_now = datetime.now().astimezone()
    local_start = window.start.astimezone(local_now.tzinfo)
    local_end = window.end.astimezone(local_now.tzinfo)
    table = Table(
        title="时间过滤窗口",
        box=box.MINIMAL_DOUBLE_HEAD,
        show_header=False,
        pad_edge=False,
    )
    table.add_column("时区", style="dim")
    table.add_column("范围", style="cyan")
    table.add_row("UTC", f"{window.start.isoformat()} → {window.end.isoformat()}")
    tz_label = local_start.tzname() or "Local"
    table.add_row(
        tz_label,
        f"{local_start.strftime('%Y-%m-%d %H:%M')} → {local_end.strftime('%Y-%m-%d %H:%M')}",
    )
    return table


def build_state(verbose: bool) -> AppState:
    repository = ConfigRepository()
    global_config = repository.load_global_config()
    scheduler = APSchedulerAdapter()
    thread_pool = ThreadPoolManager(global_config.thread_pool_workers)
    storage = SQLiteManager()

    proxy_pool = None
    if global_config.proxy_pool.enabled:
        proxy_source = global_config.proxy_pool.source
        proxy_pool = ProxyPool(file_path=Path(proxy_source)) if proxy_source else ProxyPool()

    ua_pool = None
    if global_config.user_agent_list:
        if isinstance(global_config.user_agent_list, list):
            ua_pool = UserAgentPool(global_config.user_agent_list)
        else:
            ua_pool = UserAgentPool(file_path=Path(global_config.user_agent_list))

    orchestrator = Orchestrator(
        config_repository=repository,
        scheduler=scheduler,
        thread_pool=thread_pool,
        storage=storage,
        proxy_pool=proxy_pool,
        ua_pool=ua_pool,
    )
    wizard = ConfigWizard(repository)
    configure_logging(verbose=verbose)
    return AppState(
        repository=repository,
        scheduler=scheduler,
        orchestrator=orchestrator,
        wizard=wizard,
        storage=storage,
    )


def _get_state(ctx: typer.Context) -> AppState:
    state = ctx.obj
    if state is None:
        state = build_state(verbose=False)
        ctx.obj = state
    return state


def _format_schedule(schedule: ScheduleConfig) -> str:
    data = schedule.value
    label = schedule.type.value
    if data in (None, "", [], {}):
        return label
    if schedule.type is ScheduleType.CRON:
        return f"cron ({data})"
    if schedule.type is ScheduleType.INTERVAL:
        return f"interval ({data})"
    return f"{label} ({data})"


def _render_sources_table(sources: Sequence[SourceConfig]) -> Table:
    table = Table(
        title=f"信息源总览 · 共 {len(sources)} 个",
        box=box.SIMPLE_HEAD,
        show_lines=False,
    )
    table.add_column("名称", style="cyan", no_wrap=True)
    table.add_column("类型", style="magenta")
    table.add_column("输出", style="green")
    table.add_column("调度策略", style="yellow", overflow="fold")
    for source in sources:
        table.add_row(
            source.source_name,
            source.site_type.value,
            source.output_format,
            _format_schedule(source.schedule),
        )
    return table


def _render_jobs_table(jobs: Iterable[dict[str, str]]) -> Table:
    table = Table(title="调度队列", box=box.SIMPLE_HEAD)
    table.add_column("任务 ID", style="cyan", no_wrap=True)
    table.add_column("下次执行", style="green")
    table.add_column("触发器", style="magenta", overflow="fold")
    for job in jobs:
        table.add_row(
            str(job.get("id", "-")),
            str(job.get("next_run_time", "-")),
            str(job.get("trigger", "-")),
        )
    return table


def _prompt_existing_source_name(state: AppState, provided: Optional[str], action: str) -> str:
    if provided:
        return provided
    sources = state.repository.list_sources()
    if not sources:
        console.print("暂无信息源配置，先使用 `intelli-crawler source add` 创建。", style="yellow")
        raise typer.Exit(code=1)
    console.print(
        "可用信息源：" + ", ".join(sorted(source.source_name for source in sources)),
        style="dim",
    )
    return typer.prompt(f"请输入要{action}的信息源名称")


# 进度条策略：默认在交互式终端显示，非TTY自动降级为静默
def _progress_default_enabled() -> bool:
    try:
        import sys as _sys
        return bool(getattr(_sys.stdout, "isatty", lambda: False)())
    except Exception:
        return False


app.add_typer(source_app, name="source", help="管理信息源（list/add/edit/run/delete 等）")
app.add_typer(log_app, name="log", help="查看或跟踪日志文件")


@app.callback()
def main(
    ctx: typer.Context, verbose: bool = typer.Option(False, "--verbose", help="开启调试日志", is_flag=True)
) -> None:
    ctx.obj = build_state(verbose)


@source_app.command("list", help="查看信息源清单与调度队列。")
def source_list(
    ctx: typer.Context,
    show_schedule: bool = typer.Option(
        True,
        "--show-schedule",
        help="显示调度队列信息（默认开启）。",
        is_flag=True,
    ),
    hide_schedule: bool = typer.Option(
        False,
        "--hide-schedule",
        help="隐藏调度队列信息。",
        is_flag=True,
    ),
) -> None:
    state = _get_state(ctx)
    if hide_schedule:
        show_schedule = False
    sources = state.repository.list_sources()
    if not sources:
        console.print("暂无信息源配置，使用 `intelli-crawler source add` 创建新信息源。", style="yellow")
        raise typer.Exit(code=0)
    console.print(_render_sources_table(sources))
    if show_schedule:
        jobs = list(state.scheduler.list_jobs())
        if jobs:
            console.print(_render_jobs_table(jobs))
        else:
            console.print("当前没有排定的调度任务。", style="dim")


@source_app.command("add", help="创建新的信息源配置。")
def source_add(
    ctx: typer.Context,
    name: Optional[str] = typer.Argument(None, help="信息源名称（留空时将提示输入）。"),
    template: str = typer.Option(
        "source_template.yaml",
        "--template",
        help="使用指定模板文件。",
    ),
    blank: bool = typer.Option(
        False,
        "--blank",
        help="使用空白模板快速起步。",
        is_flag=True,
    ),
    quiet: bool = typer.Option(
        False,
        "--quiet",
        help="跳过创建后的小贴士提醒。",
        is_flag=True,
    ),
) -> None:
    state = _get_state(ctx)
    name = (name or typer.prompt("请输入要创建的信息源名称")).strip()
    if not name:
        console.print("名称不能为空，请重新执行命令。", style="red")
        raise typer.Exit(code=1)
    if not blank:
        template_path = state.repository.ensure_template(template)
        content = template_path.read_text(encoding="utf-8").replace("Example Source", name)
    else:
        content = yaml.safe_dump(
            {
                "source_name": name,
                "site_type": "news",
                "target_url": "",
                "entry_pattern": "ul.list li a",
                "detail_pattern": {"title": "h1", "content": "article"},
            },
            allow_unicode=True,
            sort_keys=False,
        )
    edited = typer.edit(text=content)
    if edited is None:
        console.print("未创建信息源（编辑器未保存或取消）。", style="yellow")
        raise typer.Exit(code=0)
    payload = yaml.safe_load(edited)
    if not isinstance(payload, dict):
        console.print("配置内容解析失败，请检查格式。", style="red")
        raise typer.Exit(code=1)
    payload["source_name"] = name
    config = state.wizard.from_payload(payload)
    console.print(
        f"信息源 `{config.source_name}` 已创建，配置文件位于 {state.repository.source_path(config.source_name)}。",
        style="green",
    )
    if not quiet:
        console.print(
            f"下一步可执行 `intelli-crawler source run {config.source_name}` 立即测试。",
            style="dim",
        )


@source_app.command("edit", help="编辑现有信息源配置。")
def source_edit(
    ctx: typer.Context,
    name: Optional[str] = typer.Argument(None, help="信息源名称（留空时将列出候选）。"),
) -> None:
    state = _get_state(ctx)
    name = _prompt_existing_source_name(state, name, "编辑")
    try:
        config = state.repository.load_source(name)
    except FileNotFoundError:
        console.print(f"未找到信息源 `{name}`，请确认名称是否正确。", style="red")
        raise typer.Exit(code=1)
    content = yaml.safe_dump(
        json.loads(config.model_dump_json()),
        allow_unicode=True,
        sort_keys=False,
    )
    edited = typer.edit(text=content)
    if edited is None:
        console.print("未更新配置（可能未保存或取消编辑）。", style="yellow")
        raise typer.Exit(code=0)
    payload = yaml.safe_load(edited)
    if not isinstance(payload, dict):
        console.print("配置内容解析失败，请检查格式。", style="red")
        raise typer.Exit(code=1)
    payload["source_name"] = config.source_name
    state.wizard.from_payload(payload)
    console.print("配置已更新完成。", style="green")


@source_app.command("remove", help="删除信息源并清空历史记录。")
def source_remove(
    ctx: typer.Context,
    name: Optional[str] = typer.Argument(None, help="要删除的信息源名称。"),
    yes: bool = typer.Option(
        False,
        "--yes",
        help="跳过删除确认提示。",
        is_flag=True,
    ),
) -> None:
    state = _get_state(ctx)
    name = _prompt_existing_source_name(state, name, "删除")
    # Fallback: some environments may not set Typer flag options correctly.
    # Respect raw argv to detect '--yes'.
    try:
        import sys as _sys
        if "--yes" in (_sys.argv or []):
            yes = True
    except Exception:
        pass
    if not yes:
        confirm = typer.confirm(f"确认删除 `{name}` 并清空历史记录？", default=False)
        if not confirm:
            console.print("已取消删除操作。", style="yellow")
            raise typer.Exit(code=0)
    # 尝试清理历史记录（如果信息源不存在，则忽略该步骤的错误）
    try:
        state.orchestrator.reset_history(name)
    except FileNotFoundError:
        pass

    # 无论历史是否存在，始终尝试删除配置文件；删除后再根据文件是否仍存在决定退出码
    source_path = state.repository.source_path(name)
    try:
        state.repository.delete_source(name)
    except FileNotFoundError:
        # delete_source 本身已做存在性判断，一般不会抛异常；留作防御
        pass

    if source_path.exists():
        console.print(f"未找到信息源 `{name}`。", style="red")
        raise typer.Exit(code=1)

    console.print(f"信息源 `{name}` 已删除。", style="green")


@source_app.command("run", help="立即执行指定信息源。")
def source_run(
    ctx: typer.Context,
    name: Optional[str] = typer.Argument(None, help="要运行的信息源名称。"),
    quiet: bool = typer.Option(False, "--quiet", help="只输出精简结果。", is_flag=True),
    since: Annotated[
        Optional[str],
        typer.Option(
            "--since",
            help="仅抓取不早于该时间的内容（ISO8601，如 2024-10-14T08:00+08:00）。",
            rich_help_panel="时间过滤",
            metavar="TIMESTAMP",
            show_default=False,
        ),
    ] = None,
    until: Annotated[
        Optional[str],
        typer.Option(
            "--until",
            help="仅抓取早于该时间的内容（ISO8601，默认当前时间）。",
            rich_help_panel="时间过滤",
            metavar="TIMESTAMP",
            show_default=False,
        ),
    ] = None,
    window_start: Annotated[
        Optional[str],
        typer.Option(
            "--window-start",
            help="按每日时间窗口过滤，例如 08:00。",
            rich_help_panel="时间过滤",
            metavar="HH:MM",
            show_default=False,
        ),
    ] = None,
    window_duration: Annotated[
        Optional[str],
        typer.Option(
            "--window-duration",
            help="窗口跨度（默认 24h，可写 90m、36h、1d6h）。",
            rich_help_panel="时间过滤",
            metavar="SPAN",
            show_default=False,
        ),
    ] = None,
) -> None:
    state = _get_state(ctx)
    name = _prompt_existing_source_name(state, name, "运行")
    # Fallback: respect '--quiet' in raw argv when Typer flags misbehave
    try:
        import sys as _sys
        if "--quiet" in (_sys.argv or []):
            quiet = True
    except Exception:
        pass
    
    # 修复 quiet 参数类型问题：确保 quiet 是布尔值
    if isinstance(quiet, str):
        quiet = quiet.lower() in ('true', '1', 'yes', 'on')

    window = _resolve_window_options(since, until, window_start, window_duration)
    if window:
        if quiet:
            console.print(
                f"[dim]时间窗口 (UTC)：{window.start.isoformat()} → {window.end.isoformat()}[/dim]"
            )
        else:
            console.print(_render_window_summary(window))
    
    # 在TTY显示进度；quiet 模式强制关闭进度
    progress_flag = _progress_default_enabled() and (not quiet)
    summary = state.orchestrator.run_source(
        name,
        progress_enabled=progress_flag,
        window=window,
    )
    success = summary.get("success", 0)
    failed = summary.get("failed", 0)
    skipped = summary.get("skipped", 0)
    window_filtered = summary.get("window_filtered", 0)
    if quiet:
        message = f"运行完成：成功 {success}，失败 {failed}，跳过 {skipped}"
        if window_filtered:
            message += f"，窗口过滤 {window_filtered}"
        console.print(message)
        return
    result_table = Table(title=f"{name} 运行结果", box=box.SIMPLE_HEAD)
    result_table.add_column("指标", style="cyan")
    result_table.add_column("数量", style="green", justify="right")
    result_table.add_row("成功", str(success))
    result_table.add_row("失败", str(failed))
    result_table.add_row("跳过", str(skipped))
    if window_filtered:
        result_table.add_row("窗口过滤", str(window_filtered))
    console.print(result_table)


@source_app.command("run-all", help="智能并发执行全部信息源，自动优化资源分配")
def source_run_all(
    ctx: typer.Context,
    quiet: bool = typer.Option(False, "--quiet", help="静默模式，不显示进度条", is_flag=True),
    since: Annotated[
        Optional[str],
        typer.Option(
            "--since",
            help="仅抓取不早于该时间的内容（ISO8601，如 2024-10-14T08:00+08:00）。",
            rich_help_panel="时间过滤",
            metavar="TIMESTAMP",
            show_default=False,
        ),
    ] = None,
    until: Annotated[
        Optional[str],
        typer.Option(
            "--until",
            help="仅抓取早于该时间的内容（ISO8601，默认当前时间）。",
            rich_help_panel="时间过滤",
            metavar="TIMESTAMP",
            show_default=False,
        ),
    ] = None,
    window_start: Annotated[
        Optional[str],
        typer.Option(
            "--window-start",
            help="按每日时间窗口过滤，例如 08:00。",
            rich_help_panel="时间过滤",
            metavar="HH:MM",
            show_default=False,
        ),
    ] = None,
    window_duration: Annotated[
        Optional[str],
        typer.Option(
            "--window-duration",
            help="窗口跨度（默认 24h，可写 90m、36h、1d6h）。",
            rich_help_panel="时间过滤",
            metavar="SPAN",
            show_default=False,
        ),
    ] = None,
) -> None:
    """
    智能并发执行全部信息源的爬取任务，自动优化资源分配
    
    Args:
        quiet: 是否启用静默模式，不显示进度条
    """
    import os
    try:
        import psutil
    except ImportError:
        psutil = None
    
    state = _get_state(ctx)
    sources = state.repository.list_sources()
    if not sources:
        console.print("暂无信息源配置，使用 `intelli-crawler source add` 创建新信息源。", style="yellow")
        raise typer.Exit(code=0)

    # Fallback: respect '--quiet' in raw argv when Typer flags misbehave
    try:
        import sys as _sys
        if "--quiet" in (_sys.argv or []):
            quiet = True
    except Exception:
        pass
    
    # 修复 quiet 参数类型问题：确保是布尔值
    if isinstance(quiet, str):
        quiet = quiet.lower() in ('true', '1', 'yes', 'on')

    window = _resolve_window_options(since, until, window_start, window_duration)
    if window:
        if quiet:
            console.print(
                f"[dim]时间窗口 (UTC)：{window.start.isoformat()} → {window.end.isoformat()}[/dim]"
            )
        else:
            console.print(_render_window_summary(window))
    
    # 智能并发数计算：根据系统资源和信息源数量自动调整
    cpu_count = os.cpu_count() or 4
    source_count = len(sources)
    
    # 智能并发策略：
    # 1. 基础并发数 = min(CPU核心数, 信息源数量)
    # 2. 内存充足时(>8GB)可适当增加并发
    # 3. 最大不超过信息源数量的2倍，避免资源浪费
    base_concurrency = min(cpu_count, source_count)
    if psutil:
        try:
            memory_gb = psutil.virtual_memory().total / (1024**3)
            if memory_gb > 8:
                optimal_concurrency = min(base_concurrency * 2, source_count * 2, cpu_count * 2)
            else:
                optimal_concurrency = base_concurrency
        except Exception:
            optimal_concurrency = base_concurrency
    else:
        optimal_concurrency = base_concurrency
    
    concurrency = max(1, optimal_concurrency)
    
    # 默认显示进度（Rich 动画进度条），quiet 模式下关闭
    progress_enabled = not quiet

    results_map: dict[str, tuple[dict[str, int], str]] = {}
    total_success = total_failed = total_skipped = 0
    total_window_filtered = 0
    has_errors = False

    # 使用优化的Rich进度条，确保固定位置更新
    progress_ctx = MultiSourceProgress(enabled=progress_enabled)
    reporter_factory = progress_ctx.create_reporter
    progress_manager = progress_ctx

    with progress_manager:
        # 智能并发执行，使用线程池进行高效的任务调度
        import threading
        import time
        from concurrent.futures import ThreadPoolExecutor, as_completed
        
        # 使用ThreadPoolExecutor来安全地处理并发执行和结果收集
        # 采用线程安全的结果收集机制
        results_lock = threading.Lock()
        
        def _run_source_with_error_handling(source_name: str) -> tuple[str, dict[str, int], str]:
            """
            线程安全的信息源执行函数，包含完整的错误处理
            
            Args:
                source_name: 信息源名称
                
            Returns:
                包含源名称、统计信息和状态的元组
            """
            try:
                summary = state.orchestrator.run_source(
                    source_name,
                    progress_enabled=progress_enabled,
                    progress_factory=reporter_factory,
                    window=window,
                )
                status = "成功"
                return source_name, summary, status
            except Exception as exc:  # pragma: no cover - defensive
                summary = {"success": 0, "failed": 0, "skipped": 0, "window_filtered": 0}
                status = f"失败: {exc}"
                return source_name, summary, status
        
        with ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="SourceRunner") as executor:
            # 提交所有任务，使用智能任务调度
            future_to_source = {}
            for i, source in enumerate(sources):
                future = executor.submit(_run_source_with_error_handling, source.source_name)
                future_to_source[future] = source.source_name
                # 错开任务提交时间，避免同时启动造成的资源竞争
                if i < len(sources) - 1:  # 最后一个任务不需要延迟
                    time.sleep(0.01)  # 减少延迟时间，提高启动速度
            
            # 使用 as_completed 收集结果，提供更好的响应性
            for future in as_completed(future_to_source):
                source_name, summary, status = future.result()
                
                # 线程安全地更新结果
                with results_lock:
                    results_map[source_name] = (summary, status)
                    if status != "成功":
                        has_errors = True

    results: list[tuple[str, dict[str, int], str]] = []
    for source in sources:
        summary, status = results_map.get(
            source.source_name,
            ({"success": 0, "failed": 0, "skipped": 0, "window_filtered": 0}, "失败: 未返回结果"),
        )
        total_success += int(summary.get("success", 0))
        total_failed += int(summary.get("failed", 0))
        total_skipped += int(summary.get("skipped", 0))
        total_window_filtered += int(summary.get("window_filtered", 0))
        if status != "成功":
            has_errors = True
        results.append((source.source_name, summary, status))

    if quiet:
        for name, summary, status in results:
            window_filtered = summary.get("window_filtered", 0)
            message = (
                f"{name} -> 成功 {summary.get('success', 0)}，失败 {summary.get('failed', 0)}，"
                f"跳过 {summary.get('skipped', 0)}"
            )
            if window_filtered:
                message += f"，窗口过滤 {window_filtered}"
            message += f"（{status}）"
            console.print(message)
        aggregate_msg = (
            f"合计 -> 成功 {total_success}，失败 {total_failed}，跳过 {total_skipped}"
        )
        if total_window_filtered:
            aggregate_msg += f"，窗口过滤 {total_window_filtered}"
        console.print(aggregate_msg)
    else:
        table = Table(title=f"批量运行结果 · {len(results)} 个信息源 · 并发数: {concurrency}", box=box.SIMPLE_HEAD)
        table.add_column("信息源", style="cyan", no_wrap=True)
        table.add_column("成功", style="green", justify="right")
        table.add_column("失败", style="red", justify="right")
        table.add_column("跳过", style="yellow", justify="right")
        table.add_column("窗口过滤", style="magenta", justify="right")
        table.add_column("状态", style="magenta")
        for name, summary, status in results:
            table.add_row(
                name,
                str(summary.get("success", 0)),
                str(summary.get("failed", 0)),
                str(summary.get("skipped", 0)),
                str(summary.get("window_filtered", 0)),
                status,
            )
        table.add_row(
            "合计",
            str(total_success),
            str(total_failed),
            str(total_skipped),
            str(total_window_filtered),
            "存在错误" if has_errors else "全部完成",
        )
        console.print(table)

    if has_errors:
        raise typer.Exit(code=1)


@source_app.command("history", help="查看信息源最近的抓取历史。")
def source_history(
    ctx: typer.Context,
    name: Optional[str] = typer.Argument(None, help="信息源名称。"),
    limit_arg: Optional[int] = typer.Argument(None, help="显示记录数量（位置参数）。"),
    limit: Optional[int] = typer.Option(None, "--limit", help="显示记录数量（选项参数）。"),
) -> None:
    state = _get_state(ctx)
    name = _prompt_existing_source_name(state, name, "查看历史")
    effective_limit = limit if isinstance(limit, int) else (limit_arg if isinstance(limit_arg, int) else 20)
    rows = state.orchestrator.view_history(name, limit=effective_limit)
    if not rows:
        console.print("没有历史记录。", style="dim")
        return
    table = Table(title=f"{name} 最近 {len(rows)} 条历史", box=box.SIMPLE_HEAD)
    table.add_column("抓取时间", style="green")
    table.add_column("URL", overflow="fold")
    for url, ts in rows:
        table.add_row(str(ts), str(url))
    console.print(table)


@source_app.command("reset", help="清空指定信息源的历史记录。")
def source_reset(
    ctx: typer.Context,
    name: Optional[str] = typer.Argument(None, help="信息源名称。"),
    yes: bool = typer.Option(False, "--yes", help="跳过确认提示。", is_flag=True),
) -> None:
    state = _get_state(ctx)
    name = _prompt_existing_source_name(state, name, "清空历史")
    # Fallback: respect '--yes' in raw argv when Typer flags misbehave
    try:
        import sys as _sys
        if "--yes" in (_sys.argv or []):
            yes = True
    except Exception:
        pass
    if not yes:
        confirm = typer.confirm(f"确定要清空 `{name}` 的历史记录？", default=False)
        if not confirm:
            console.print("已取消操作。", style="yellow")
            raise typer.Exit(code=0)
    state.orchestrator.reset_history(name)
    console.print(f"信息源 `{name}` 的历史记录已清空。", style="green")


@source_app.command("reset-all", help="清空所有信息源的历史记录。")
def source_reset_all(ctx: typer.Context) -> None:
    """无确认交互，一次性清空所有信息源的去重历史。"""
    state = _get_state(ctx)
    sources = state.repository.list_sources()
    if not sources:
        console.print("暂无信息源配置，使用 `intelli-crawler source add` 创建新信息源。", style="yellow")
        raise typer.Exit(code=0)
    errors: list[str] = []
    for src in sources:
        try:
            state.orchestrator.reset_history(src.source_name)
        except Exception as exc:  # pragma: no cover - 防御性处理
            errors.append(f"{src.source_name}: {exc}")

    # 绑定输出清理：删除 data/outputs 下的所有文件/子目录
    outputs_dir = state.repository.locator.outputs_dir
    removed = 0
    try:
        if outputs_dir.exists():
            for path in outputs_dir.iterdir():
                try:
                    if path.is_file():
                        path.unlink()
                        removed += 1
                    elif path.is_dir():
                        import shutil as _shutil
                        _shutil.rmtree(path)
                        removed += 1
                except Exception as exc:
                    errors.append(f"outputs/{path.name}: {exc}")
    except Exception as exc:  # pragma: no cover - 顶层防御
        errors.append(f"outputs_dir: {exc}")

    if errors:
        console.print("部分操作失败：", style="red")
        for msg in errors:
            console.print(f"- {msg}", style="red")
    console.print(
        f"已清空 {len(sources)} 个信息源的历史记录，并删除 outputs 中 {removed} 个项。",
        style="green",
    )


@log_app.command("list", help="列出可用的日志文件。")
def log_list() -> None:
    logs = list(available_source_logs())
    console.print("日志文件：", style="cyan")
    if not logs:
        console.print("暂未生成任何信息源日志。", style="dim")
        return
    table = Table(box=box.SIMPLE_HEAD)
    table.add_column("文件名", style="green")
    for path in logs:
        table.add_row(path.name)
    console.print(table)


@log_app.command("show", help="查看指定日志的最近内容。")
def log_show(
    name: Optional[str] = typer.Option(
        None,
        "--source",
        help="信息源名称（为空则展示全局日志）。",
    ),
    tail: Optional[int] = typer.Option(100, "--tail", help="显示最近 N 行内容。"),
    name_arg: Optional[str] = typer.Argument(None, help="信息源名称（位置参数备选）。"),
    tail_arg: Optional[int] = typer.Argument(None, help="显示最近 N 行（位置参数备选）。"),
) -> None:
    base_dir = Path(__file__).resolve().parents[1] / "logs"
    effective_name = name if isinstance(name, str) and name else (name_arg if isinstance(name_arg, str) else None)
    effective_tail = tail if isinstance(tail, int) else (tail_arg if isinstance(tail_arg, int) else 100)
    if effective_name:
        path = base_dir / "sources" / f"{effective_name}.log"
    else:
        path = base_dir / "crawler.log"
    lines = tail_log(path, effective_tail)
    if not lines:
        console.print("暂无日志信息，请稍后再试。", style="dim")
        return
    header = f"{'源日志' if effective_name else '全局日志'} · 最近 {len(lines)} 行"
    console.print(header, style="cyan")
    console.print("".join(lines))


@app.command("list-sources", hidden=True)
def legacy_list_sources(ctx: typer.Context) -> None:
    console.print("[dim]提示：推荐使用 `intelli-crawler source list`。[/dim]")
    source_list(ctx)


@app.command("add-source", hidden=True)
def legacy_add_source(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="信息源名称"),
    blank: bool = typer.Option(False, "--blank", help="使用空白模板创建配置", is_flag=True),
) -> None:
    console.print("[dim]提示：推荐使用 `intelli-crawler source add`。[/dim]")
    source_add(ctx, name=name, template="source_template.yaml", blank=blank, quiet=True)


@app.command("edit-source", hidden=True)
def legacy_edit_source(ctx: typer.Context, name: str = typer.Argument(...)) -> None:
    console.print("[dim]提示：推荐使用 `intelli-crawler source edit`。[/dim]")
    source_edit(ctx, name=name)


@app.command("delete-source", hidden=True)
def legacy_delete_source(ctx: typer.Context, name: str = typer.Argument(...)) -> None:
    console.print("[dim]提示：推荐使用 `intelli-crawler source remove`。[/dim]")
    source_remove(ctx, name=name, yes=True)


@app.command("run-now", hidden=True)
def legacy_run_now(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="信息源名称"),
) -> None:
    console.print("[dim]提示：推荐使用 `intelli-crawler source run`。[/dim]")
    # 统一启用进度条
    source_run(ctx, name=name, quiet=False)


@app.command("view-logs", hidden=True)
def legacy_view_logs(
    ctx: typer.Context,
    name: Optional[str] = typer.Option(None, "--source", help="信息源名称（为空则展示全局日志）"),
    tail: Optional[int] = typer.Option(100, "--tail", help="查看最近 N 行"),
    name_arg: Optional[str] = typer.Argument(None, help="信息源名称（位置参数备选）"),
    tail_arg: Optional[int] = typer.Argument(None, help="查看最近 N 行（位置参数备选）"),
) -> None:
    console.print("[dim]提示：推荐使用 `intelli-crawler log show`。[/dim]")
    eff_name = name if isinstance(name, str) and name else (name_arg if isinstance(name_arg, str) else None)
    eff_tail = tail if isinstance(tail, int) else (tail_arg if isinstance(tail_arg, int) else 100)
    log_show(name=eff_name, tail=eff_tail)


@app.command("reset-history", hidden=True)
def legacy_reset_history(ctx: typer.Context, name: str = typer.Argument(...)) -> None:
    console.print("[dim]提示：推荐使用 `intelli-crawler source reset`。[/dim]")
    source_reset(ctx, name=name, yes=True)


@app.command("view-history", hidden=True)
def legacy_view_history(
    ctx: typer.Context,
    name: str = typer.Argument(...),
    limit: Optional[int] = typer.Option(20, "--limit"),
    limit_arg: Optional[int] = typer.Argument(None),
) -> None:
    console.print("[dim]提示：推荐使用 `intelli-crawler source history`。[/dim]")
    source_history(ctx, name=name, limit=limit, limit_arg=limit_arg)


@app.command("list-logs", hidden=True)
def legacy_list_logs() -> None:
    console.print("[dim]提示：推荐使用 `intelli-crawler log list`。[/dim]")
    log_list()


def cli() -> None:
    # Disable Typer Rich help rendering to avoid Click signature mismatches
    try:
        # Older Typer versions gate rich help on a module-level `rich` import
        import typer.core as _typer_core
        _typer_core.rich = None  # force fallback to Click formatter
    except Exception:
        pass
    try:
        # Also guard newer Typer variants that use USE_RICH flags
        import typer.core as _typer_core
        import typer.rich_utils as _typer_rich
        _typer_core.USE_RICH = False  # type: ignore[attr-defined]
        _typer_rich.USE_RICH = False  # type: ignore[attr-defined]
    except Exception:
        pass

    # Compatibility patch: align Typer's make_metavar signatures with Click expectations
    # Some Typer versions define TyperArgument/TyperOption.make_metavar(self) while
    # newer Click expects make_metavar(self, ctx). We shim an adapter to accept the
    # ctx argument and delegate to the original implementation.
    try:
        import typer.core as _typer_core

        if hasattr(_typer_core, "TyperArgument"):
            _TyArg = _typer_core.TyperArgument
            # Hard override: provide a Click-compatible implementation
            def _make_metavar_arg(self, ctx=None):
                try:
                    return self.type.get_metavar(ctx)
                except Exception:
                    try:
                        return getattr(self, "metavar", None) or getattr(self, "name", "ARG").upper()
                    except Exception:
                        return "ARG"

            _TyArg.make_metavar = _make_metavar_arg  # type: ignore[assignment]

        if hasattr(_typer_core, "TyperOption"):
            _TyOpt = _typer_core.TyperOption
            def _make_metavar_opt(self, ctx=None):
                try:
                    return self.type.get_metavar(ctx)
                except Exception:
                    try:
                        return getattr(self, "metavar", None) or getattr(self, "name", "OPTION").upper()
                    except Exception:
                        return "OPTION"

            _TyOpt.make_metavar = _make_metavar_opt  # type: ignore[assignment]
    except Exception:
        # If anything goes wrong, proceed without the shim.
        pass
    app()


if __name__ == "__main__":  # pragma: no cover
    cli()
