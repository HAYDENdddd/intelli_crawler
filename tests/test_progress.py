#!/usr/bin/env python3
"""测试进度条功能的简单脚本"""

import sys
import os

sys.path.insert(0, os.path.abspath("."))

from intelli_crawler.config import ConfigRepository
from intelli_crawler.orchestrator import Orchestrator
from intelli_crawler.scheduler import APSchedulerAdapter
from intelli_crawler.engine import ThreadPoolManager
from intelli_crawler.infra import SQLiteManager
from intelli_crawler.logging_conf import configure_logging


def test_progress_bar():
    """测试进度条功能"""
    # 初始化组件
    repository = ConfigRepository()
    global_config = repository.load_global_config()
    scheduler = APSchedulerAdapter()
    thread_pool = ThreadPoolManager(global_config.thread_pool_workers)
    storage = SQLiteManager()

    # 创建orchestrator
    orchestrator = Orchestrator(
        config_repository=repository,
        scheduler=scheduler,
        thread_pool=thread_pool,
        storage=storage,
        proxy_pool=None,
        ua_pool=None,
    )

    # 配置日志
    configure_logging(verbose=True)

    try:
        # 运行爬虫，启用进度条
        print("开始运行爬虫，进度条应该显示...")
        summary = orchestrator.run_source("Odaily Newsflash", progress_enabled=True)
        print(
            f"完成：成功 {summary.get('success', 0)}，失败 {summary.get('failed', 0)}，跳过 {summary.get('skipped', 0)}"
        )
    except Exception as e:
        print(f"运行出错: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    test_progress_bar()
