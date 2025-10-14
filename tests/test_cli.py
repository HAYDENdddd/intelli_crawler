from pathlib import Path

import yaml
from typer.testing import CliRunner

from intelli_crawler.app import app


def test_cli_add_list_delete(tmp_path, monkeypatch):
    monkeypatch.setenv("INTELLI_CRAWLER_HOME", str(tmp_path))
    runner = CliRunner()

    # Mock editor to accept default content
    monkeypatch.setattr("typer.edit", lambda text=None: text)

    result = runner.invoke(app, ["source", "add", "demo", "--blank"])
    assert result.exit_code == 0, result.stdout
    assert "信息源 `demo` 已创建" in result.stdout

    result = runner.invoke(app, ["source", "list"])
    assert "demo" in result.stdout

    # Ensure configuration file exists
    config_path = Path(tmp_path) / "data" / "sources" / "demo.yaml"
    assert config_path.exists()
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert payload["source_name"] == "demo"

    result = runner.invoke(app, ["source", "remove", "demo", "--yes"])
    assert result.exit_code == 0
    assert "已删除" in result.stdout
    assert not config_path.exists()
