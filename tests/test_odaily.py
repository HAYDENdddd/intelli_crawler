#!/usr/bin/env python3
"""临时测试脚本，用于验证Odaily Newsflash的多选择器配置"""

import sys
from pathlib import Path

# 添加项目路径到sys.path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from intelli_crawler.config import ConfigRepository
from intelli_crawler.orchestrator import Orchestrator
from intelli_crawler.scheduler import APSchedulerAdapter
from intelli_crawler.engine import ThreadPoolManager
from intelli_crawler.infra import SQLiteManager
from intelli_crawler.ui import ConfigWizard


def test_odaily():
    """测试Odaily Newsflash爬虫"""
    # 初始化组件
    repository = ConfigRepository()
    scheduler = APSchedulerAdapter()
    thread_pool = ThreadPoolManager()
    storage = SQLiteManager()
    wizard = ConfigWizard(repository)

    orchestrator = Orchestrator(
        config_repository=repository, scheduler=scheduler, thread_pool=thread_pool, storage=storage
    )

    # 加载配置并运行
    try:
        source_config = repository.load_source("Odaily Newsflash")
        print(f"加载配置: {source_config.source_name}")
        print(f"目标URL: {source_config.target_url}")
        print(f"详情模式配置: {source_config.detail_pattern}")

        # 运行爬虫
        result = orchestrator.run_source(source_config.source_name, progress_enabled=False)
        print(f"爬虫运行完成: {result}")

    except Exception as e:
        print(f"运行出错: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    test_odaily()
