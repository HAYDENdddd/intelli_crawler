#!/usr/bin/env python3
"""调试CLI参数传递"""

import sys
import os
sys.path.insert(0, os.path.abspath("."))

from intelli_crawler.config import ConfigRepository
from intelli_crawler.orchestrator import Orchestrator
from intelli_crawler.scheduler import APSchedulerAdapter
from intelli_crawler.engine import ThreadPoolManager
from intelli_crawler.infra import SQLiteManager

def debug_progress_params():
    """调试进度条参数传递"""
    repository = ConfigRepository()
    global_config = repository.load_global_config()
    scheduler = APSchedulerAdapter()
    thread_pool = ThreadPoolManager(global_config.thread_pool_workers)
    storage = SQLiteManager()

    orchestrator = Orchestrator(
        config_repository=repository,
        scheduler=scheduler,
        thread_pool=thread_pool,
        storage=storage,
    )

    print("进度条行为：现已统一开启，忽略全局配置与 CLI 关闭选项。")
    print("不带任何参数的 CLI 调用也会显示进度条。")

if __name__ == "__main__":
    debug_progress_params()
