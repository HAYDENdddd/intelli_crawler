#!/usr/bin/env python3
"""
测试配置文件加载
"""

from intelli_crawler.config import ConfigRepository


def test_config_loading():
    """测试雪球配置文件加载"""
    repo = ConfigRepository()

    try:
        config = repo.load_source("xueqiu")
        print(f"配置文件加载成功:")
        print(f"  source_name: {config.source_name}")
        print(f"  target_url: {config.target_url}")
        print(f"  entry_pattern: {config.entry_pattern}")
        print(f"  keywords_filter: {config.keywords_filter}")
        print(f"  use_entry_content: {config.use_entry_content}")

        if hasattr(config, "entry_interactions") and config.entry_interactions:
            print(f"  entry_interactions:")
            print(f"    wait_selector: {config.entry_interactions.wait_selector}")
            print(f"    click_more_selector: {config.entry_interactions.click_more_selector}")
            print(f"    click_wait_selector: {config.entry_interactions.click_wait_selector}")

        return config
    except Exception as e:
        print(f"配置文件加载失败: {e}")
        return None


if __name__ == "__main__":
    test_config_loading()
