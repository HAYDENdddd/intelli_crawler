from __future__ import annotations

from intelli_crawler.engine import ThreadPoolManager


def test_thread_pool_manager_isolates_executors() -> None:
    manager = ThreadPoolManager(default_workers=2)
    default_a = manager.get()
    default_b = manager.get()
    assert default_a is default_b

    pool_alpha = manager.get("alpha", max_workers=1)
    pool_alpha_again = manager.get("alpha")
    assert pool_alpha is pool_alpha_again

    pool_beta = manager.get("beta")
    assert pool_beta is not pool_alpha

    manager.shutdown()
