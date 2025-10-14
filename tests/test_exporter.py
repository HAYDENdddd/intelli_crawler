import json

from intelli_crawler.engine.exporter import FileExporter, SQLiteExporter


def test_file_exporter_json(tmp_path):
    exporter = FileExporter(tmp_path, "demo", "json", run_tag="test")
    exporter.export({"title": "hello"})
    exporter.flush()
    exporter.close()
    path = tmp_path / "demo-test.jsonl"
    data = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert data[0]["title"] == "hello"


def test_file_exporter_csv(tmp_path):
    exporter = FileExporter(tmp_path, "demo", "csv", run_tag="test")
    exporter.export({"a": 1, "b": 2})
    exporter.export({"a": 3, "b": 4})
    exporter.flush()
    exporter.close()
    path = tmp_path / "demo-test.csv"
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "a,b"
    assert lines[1] == "1,2"


def test_file_exporter_txt(tmp_path):
    exporter = FileExporter(tmp_path, "demo", "txt", run_tag="test")
    exporter.export(
        {
            "title": "hello",
            "summary": "world",
            "url": "https://example.com",
            "source_name": "Demo",
        }
    )
    exporter.export(
        {
            "title": "second",
            "summary": "entry",
            "url": "https://example.com/2",
            "source_name": "Demo",
        }
    )
    exporter.flush()
    exporter.close()
    path = tmp_path / "demo-test.txt"
    content = path.read_text(encoding="utf-8")
    assert "1. hello" in content
    assert "2. second" in content


def test_sqlite_exporter(tmp_path):
    exporter = SQLiteExporter(tmp_path / "demo.db")
    exporter.export({"title": "hello"})
    exporter.flush()
    exporter.close()
    import sqlite3

    conn = sqlite3.connect(tmp_path / "demo.db")
    row = conn.execute("SELECT payload FROM records").fetchone()
    conn.close()
    assert row is not None
    payload = json.loads(row[0])
    assert payload["title"] == "hello"
