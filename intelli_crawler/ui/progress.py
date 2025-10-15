"""Terminal progress helpers with modern Rich-based rendering."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from rich.console import Console
from rich.errors import LiveError
from rich.status import Status
from rich.progress import (
    BarColumn,
    Progress,
    ProgressColumn,
    Task,
    TaskID,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    SpinnerColumn,
    filesize,
)
from rich.text import Text


@dataclass
class ProgressState:
    total: int
    success: int = 0
    failed: int = 0
    skipped: int = 0
    current_url: str | None = None


class RateColumn(ProgressColumn):
    """
    显示爬取速率的自定义列
    
    渲染每秒处理的URL数量，格式为 "X.X url/s"
    """

    def render(self, task: Task) -> Text:
        """
        渲染速率信息
        
        Args:
            task: Rich Progress任务对象
            
        Returns:
            包含速率信息的Text对象
        """
        speed = task.finished_speed or task.speed
        if speed is None:
            return Text("", style="progress.percentage")
        
        # 使用filesize工具来格式化数字，但单位改为url/s
        if speed < 1000:
            return Text(f"{speed:.1f} url/s", style="progress.percentage")
        else:
            unit, suffix = filesize.pick_unit_and_suffix(
                int(speed),
                ["", "K", "M", "G", "T"],
                1000,
            )
            data_speed = speed / unit
            return Text(f"{data_speed:.1f}{suffix} url/s", style="progress.percentage")


class ProgressReporter:
    """Render progress and maintain counters for CLI feedback."""

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self._console: Console | None = None
        self._progress: Progress | None = None
        self._task_id: TaskID | None = None
        self.state: ProgressState | None = None
        self._label: str = "采集任务"

    def set_label(self, label: str) -> None:
        """Update the display label for the progress row."""
        self._label = label
        if self._progress is not None and self._task_id is not None:
            try:
                self._progress.update(self._task_id, source=label)
            except Exception:
                pass

    def start(self, total: int) -> None:
        self.state = ProgressState(total=total)
        if not self.enabled:
            return
        if self._console is None:
            self._console = Console()
            if not self._console.is_terminal:
                # 非交互环境回退为静默模式，避免重复打印
                self._console = None
                self.enabled = False
                return
        self._progress = Progress(
            SpinnerColumn(style="cyan"),
            TextColumn("[bold blue]{task.fields[source]:<18}", justify="left"),
            BarColumn(bar_width=None, complete_style="green", finished_style="green", pulse_style="cyan"),
            TaskProgressColumn(show_speed=False),
            TimeElapsedColumn(),
            RateColumn(),
            TextColumn("[green]✓{task.fields[success]:>3}", justify="right"),
            TextColumn("[red]✗{task.fields[failed]:>3}", justify="right"),
            TextColumn("[yellow]↺{task.fields[skipped]:>3}", justify="right"),
            TextColumn("[dim]{task.fields[current_url]}", justify="left"),
            refresh_per_second=12,
            expand=True,
            transient=True,
            console=self._console,
            auto_refresh=True,
            disable=not self.enabled,
        )
        try:
            self._progress.__enter__()
        except LiveError:
            # 同一控制台已存在活动进度条，退化为静默模式
            self.enabled = False
            self._progress = None
            self._console = None
            return
        self._task_id = self._progress.add_task(
            "crawl",
            total=total,
            source=self._label,
            success=0,
            failed=0,
            skipped=0,
            current_url="等待中…",
        )

    def advance(
        self,
        success: bool = False,
        failed: bool = False,
        skipped: bool = False,
        current_url: str | None = None,
    ) -> None:
        if not self.state:
            raise RuntimeError("ProgressReporter.start must be called before advance")
        if current_url:
            self.state.current_url = current_url
        if success:
            self.state.success += 1
        if failed:
            self.state.failed += 1
        if skipped:
            self.state.skipped += 1
        if self._progress is not None and self._task_id is not None:
            display_url = self.state.current_url or ""
            if len(display_url) > 60:
                display_url = display_url[:57] + "..."
            metrics = {
                "success": self.state.success,
                "failed": self.state.failed,
                "skipped": self.state.skipped,
                "current_url": display_url,
            }
            try:
                self._progress.update(self._task_id, advance=1, **metrics)
            except Exception:
                pass

    def close(self) -> None:
        if self._progress is not None and self._task_id is not None and self.state is not None:
            final_completed = self.state.success + self.state.failed + self.state.skipped
            try:
                self._progress.update(
                    self._task_id,
                    completed=final_completed,
                    current_url="已完成",
                    success=self.state.success,
                    failed=self.state.failed,
                    skipped=self.state.skipped,
                )
            except Exception:
                pass
        # 确保停止并退出 Rich Live，避免终端残留状态
        if self._progress is not None:
            try:
                try:
                    self._progress.stop()
                except Exception:
                    pass
                self._progress.__exit__(None, None, None)
            except Exception:
                pass
            self._progress = None
        self._task_id = None

    def summary(self) -> dict[str, int]:
        if not self.state:
            return {"success": 0, "failed": 0, "skipped": 0}
        return {
            "success": self.state.success,
            "failed": self.state.failed,
            "skipped": self.state.skipped,
        }


class MultiSourceProgress:
    """
    管理多个进度条的 Rich 显示器，支持并发安全的进度更新
    
    采用网上高手推荐的最佳实践：
    1. 线程安全的进度更新机制
    2. 优化的刷新频率和显示配置
    3. 更好的终端兼容性
    """

    def __init__(self, enabled: bool = True, console: Console | None = None) -> None:
        self.enabled = enabled
        # 优化终端配置，确保进度条正确显示
        self.console = console or Console()
        if enabled and not self.console.is_terminal:
            # 非TTY 环境下退化为静默模式，避免重复打印
            self.enabled = False
        
        # 优化的进度条配置，确保固定位置更新而不重复打印
        self._progress = Progress(
            SpinnerColumn(style="cyan"),
            TextColumn("[bold blue]{task.fields[source]:<18}", justify="left"),
            BarColumn(bar_width=None, complete_style="green", finished_style="green", pulse_style="cyan"),
            TaskProgressColumn(show_speed=False),
            TimeElapsedColumn(),
            RateColumn(),
            TextColumn("[green]✓{task.fields[success]:>3}", justify="right"),
            TextColumn("[red]✗{task.fields[failed]:>3}", justify="right"),
            TextColumn("[yellow]↺{task.fields[skipped]:>3}", justify="right"),
            TextColumn("[dim]{task.fields[current_url]}", justify="left"),
            console=self.console,
            transient=True,
            refresh_per_second=12,
            expand=True,
            disable=not self.enabled,
            auto_refresh=True,
        )
        self._lock = Lock()
        self._entered = False
        self._task_count = 0

    def __enter__(self) -> "MultiSourceProgress":
        if self.enabled and not self._entered:
            try:
                self._progress.__enter__()
                self._entered = True
            except LiveError:
                # 若已有其它 Live 控制器占用同一控制台，则直接退化为静默模式
                self.enabled = False
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.enabled and self._entered:
            # 确保所有任务都完成后再退出
            try:
                self._progress.stop()
            except Exception:
                pass
            self._progress.__exit__(exc_type, exc, tb)
            self._entered = False

    def create_reporter(self, source_name: str) -> "MultiSourceProgressReporter":
        """
        创建指定信息源的进度报告器
        
        Args:
            source_name: 信息源名称
            
        Returns:
            MultiSourceProgressReporter 实例
        """
        return MultiSourceProgressReporter(self, source_name)

    def add_task(self, source_name: str, total: int | None) -> TaskID:
        """
        线程安全地添加新的进度任务
        
        Args:
            source_name: 信息源名称
            total: 总任务数，None 表示不确定数量
            
        Returns:
            任务ID
        """
        with self._lock:
            self._task_count += 1
            return self._progress.add_task(
                f"Task-{self._task_count}", 
                total=total, 
                source=source_name, 
                success=0,
                failed=0,
                skipped=0,
                current_url="等待中…",
            )

    def advance_task(
        self,
        task_id: TaskID,
        state: ProgressState,
        current_url: str | None,
    ) -> None:
        """
        线程安全地更新任务进度
        
        Args:
            task_id: 任务ID
            state: 当前进度状态
            current_url: 当前处理的URL
        """
        if not self.enabled:
            return
        
        # 截断URL显示，避免布局问题
        display_url = ""
        if current_url:
            display_url = current_url[:50] + "..." if len(current_url) > 50 else current_url
            
        with self._lock:
            try:
                self._progress.update(
                    task_id,
                    advance=1,
                    success=state.success,
                    failed=state.failed,
                    skipped=state.skipped,
                    current_url=display_url,
                )
            except Exception:
                # 防御性编程：如果更新失败，不影响主流程
                pass

    def finish_task(self, task_id: TaskID, state: ProgressState | None) -> None:
        """
        完成指定任务，更新最终状态
        
        Args:
            task_id: 任务ID
            state: 最终状态
        """
        if not self.enabled:
            return
        
        completed = 0
        if state:
            completed = state.success + state.failed + state.skipped
            
        with self._lock:
            try:
                self._progress.update(
                    task_id, 
                    completed=completed,
                    current_url="[dim]已完成[/dim]",
                    success=state.success if state else 0,
                    failed=state.failed if state else 0,
                    skipped=state.skipped if state else 0,
                )
            except Exception:
                pass

    def stop(self) -> None:
        """停止进度显示"""
        if self.enabled and self._entered:
            try:
                self._progress.stop()
            except Exception:
                pass


class MultiSourceProgressReporter:
    """
    多源进度报告器适配器，提供类似 ProgressReporter 的 API
    
    支持线程安全的进度更新和状态管理
    """

    def __init__(self, manager: MultiSourceProgress, source_name: str) -> None:
        self.manager = manager
        self.source_name = source_name
        self.enabled = manager.enabled
        self.state: ProgressState | None = None
        self._task_id: TaskID | None = None

    def start(self, total: int) -> None:
        """
        开始进度跟踪，设置总任务数
        
        Args:
            total: 总任务数
        """
        self.state = ProgressState(total=total)
        if self.enabled:
            self._task_id = self.manager.add_task(self.source_name, total)

    def start_indeterminate(self) -> None:
        """开始不确定数量的进度跟踪"""
        self.state = ProgressState(total=0)
        if self.enabled:
            self._task_id = self.manager.add_task(self.source_name, None)

    def set_total(self, total: int) -> None:
        """
        动态设置总任务数（用于不确定数量的情况）
        
        Args:
            total: 总任务数
        """
        if self.state:
            self.state.total = total
        if self._task_id is not None:
            with self.manager._lock:
                try:
                    self.manager._progress.update(self._task_id, total=total)
                except Exception:
                    pass

    def advance(
        self,
        success: bool = False,
        failed: bool = False,
        skipped: bool = False,
        current_url: str | None = None,
    ) -> None:
        """
        推进进度，更新统计信息
        
        Args:
            success: 是否成功处理一个项目
            failed: 是否失败处理一个项目
            skipped: 是否跳过一个项目
            current_url: 当前处理的URL
        """
        if not self.state:
            raise RuntimeError("ProgressReporter.start must be called before advance")
        
        if current_url:
            self.state.current_url = current_url
        if success:
            self.state.success += 1
        if failed:
            self.state.failed += 1
        if skipped:
            self.state.skipped += 1
            
        if self._task_id is not None:
            self.manager.advance_task(self._task_id, self.state, self.state.current_url)

    def close(self) -> None:
        """关闭进度报告器，完成进度显示"""
        if self._task_id is not None:
            self.manager.finish_task(self._task_id, self.state)

    def summary(self) -> dict[str, int]:
        """
        获取当前统计摘要
        
        Returns:
            包含成功、失败、跳过数量的字典
        """
        if not self.state:
            return {"success": 0, "failed": 0, "skipped": 0}
        return {
            "success": self.state.success,
            "failed": self.state.failed,
            "skipped": self.state.skipped,
        }


class ProgressActivity:
    """Indeterminate activity indicator using Rich Status spinner."""

    def __init__(self, enabled: bool = True, console: Console | None = None) -> None:
        self.enabled = enabled
        # 使用默认 Console 配置，避免强制修改终端交互/渲染模式
        # 这样可以减少异常终端状态（如箭头键失效、回显异常）残留的可能性
        self.console = console or Console()
        self._status: Status | None = None

    def start(self, message: str) -> None:
        """
        启动进度活动指示器
        
        Args:
            message: 要显示的状态消息
        """
        if not self.enabled or self._status is not None:
            return
        self._status = self.console.status(message)
        self._status.start()

    def update(self, message: str) -> None:
        """
        更新进度活动指示器的消息
        
        Args:
            message: 新的状态消息
        """
        if self._status is not None:
            self._status.update(message)

    def close(self) -> None:
        """关闭进度活动指示器"""
        if self._status is not None:
            self._status.stop()
            self._status = None


__all__ = [
    "ProgressReporter",
    "ProgressState",
    "MultiSourceProgress",
    "MultiSourceProgressReporter",
    "ProgressActivity",
]
