#!/usr/bin/env python3
"""重置历史记录脚本"""

import sys
import os

sys.path.insert(0, os.path.abspath("."))

from intelli_crawler.infra import SQLiteManager


def reset_history(source_name: str):
    """重置指定源的历史记录"""
    storage = SQLiteManager()
    
    # 删除URL历史记录
    storage.execute("DELETE FROM url_history WHERE source = ?", (source_name,))
    
    # 删除内容去重记录
    storage.execute("DELETE FROM content_dedup WHERE source = ?", (source_name,))
    
    print(f"已重置 {source_name} 的历史记录")


if __name__ == "__main__":
    reset_history("Odaily Newsflash")