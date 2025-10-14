from __future__ import annotations

from types import SimpleNamespace

from typer.testing import CliRunner

from intelli_crawler.app import AppState, app


class StubOrchestrator:
    def __init__(self, summary: dict[str, int]) -> None:
        self.summary = summary
        self.calls: list[tuple[str, bool, object]] = []
        self.thread_pool = SimpleNamespace(default_workers=4)

    def run_source(
        self,
        name: str,
        progress_enabled: bool | None = None,
        progress_factory=None,
        window=None,
    ) -> dict[str, int]:
        self.calls.append((name, bool(progress_enabled), window))
        return self.summary

    def reset_history(self, name: str) -> None:
        self.calls.append((f"reset:{name}", True))


def make_state(sources, scheduler_jobs, summary) -> AppState:
    orchestrator = StubOrchestrator(summary)
    repository = SimpleNamespace(
        list_sources=lambda: sources,
        delete_source=lambda name: None,
        source_path=lambda name: SimpleNamespace(),
    )
    scheduler = SimpleNamespace(list_jobs=lambda: scheduler_jobs)
    wizard = SimpleNamespace()
    storage = SimpleNamespace()
    return AppState(
        repository=repository,
        scheduler=scheduler,
        orchestrator=orchestrator,
        wizard=wizard,
        storage=storage,
    )


def test_cli_list_sources(monkeypatch, sample_source_config) -> None:
    source = sample_source_config()
    jobs = [{"id": "source::Example", "next_run_time": "soon", "trigger": "cron[*/5 * * * *]"}]
    state = make_state([source], jobs, {"success": 1, "failed": 0, "skipped": 0})
    monkeypatch.setattr("intelli_crawler.app.build_state", lambda verbose: state)

    runner = CliRunner()
    result = runner.invoke(app, ["source", "list"])
    assert result.exit_code == 0, result.stdout
    output = result.stdout
    assert "信息源总览" in output
    assert "Example" in output


def test_cli_run_now(monkeypatch, sample_source_config) -> None:
    source = sample_source_config()
    state = make_state([source], [], {"success": 2, "failed": 1, "skipped": 0})
    monkeypatch.setattr("intelli_crawler.app.build_state", lambda verbose: state)
    runner = CliRunner()
    result = runner.invoke(app, ["source", "run", source.source_name])
    assert result.exit_code == 0, result.stdout
    assert state.orchestrator.calls
    assert state.orchestrator.calls[0][0] == source.source_name
    output = result.stdout
    assert "运行结果" in output
    assert "成功" in output
    assert "失败" in output
    assert "跳过" in output


def test_cli_run_all(monkeypatch, sample_source_config) -> None:
    sources = [
        sample_source_config(),
        sample_source_config(source_name="Another"),
    ]
    state = make_state(sources, [], {"success": 2, "failed": 1, "skipped": 0})
    monkeypatch.setattr("intelli_crawler.app.build_state", lambda verbose: state)
    runner = CliRunner()
    result = runner.invoke(app, ["source", "run-all"])
    assert result.exit_code == 0, result.stdout
    assert len(state.orchestrator.calls) == len(sources)
    output = result.stdout
    assert "批量运行结果" in output
    assert "窗口过滤" in output
    assert "Example" in output and "Another" in output
    assert "合计" in output
