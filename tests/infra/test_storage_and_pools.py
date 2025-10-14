from __future__ import annotations

import random

from intelli_crawler.infra import ProxyPool, SQLiteManager, UserAgentPool


def test_sqlite_manager_initialises_schema(tmp_path) -> None:
    manager = SQLiteManager()
    path = tmp_path / "history.db"
    conn = manager.connect(path)
    columns = conn.execute("PRAGMA table_info(crawl_history)").fetchall()
    column_names = [row["name"] for row in columns]
    assert {"url", "content_hash", "timestamp", "source_name"}.issubset(column_names)


def test_sqlite_manager_reset(tmp_path) -> None:
    manager = SQLiteManager()
    path = tmp_path / "history.db"
    conn = manager.connect(path)
    conn.execute("INSERT OR IGNORE INTO crawl_history(url) VALUES ('https://example.com')")
    conn.commit()
    manager.reset(path)
    assert not path.exists()
    conn = manager.connect(path)
    rows = conn.execute("SELECT count(*) FROM crawl_history").fetchone()
    assert rows[0] == 0


def test_proxy_pool_rotation(monkeypatch, snapshot) -> None:
    monkeypatch.setattr(random, "shuffle", lambda seq: seq.reverse())
    pool = ProxyPool(proxies=["http://a", "http://b", "http://c"])
    cycle = [pool.get_proxy() for _ in range(4)]
    pool.refresh(["http://x", "http://y"])
    refreshed = [pool.get_proxy(), pool.get_proxy()]
    snapshot.assert_match({"cycle": cycle, "refreshed": refreshed}, key="proxy_pool_cycle")


def test_user_agent_pool(monkeypatch, snapshot) -> None:
    monkeypatch.setattr(random, "choice", lambda seq: seq[0])
    pool = UserAgentPool(user_agents=["UA1", "UA2"])
    first = pool.get()
    pool.refresh(["UA3", "UA4"])
    second = pool.get()
    snapshot.assert_match({"first": first, "second": second}, key="user_agent_pool")
