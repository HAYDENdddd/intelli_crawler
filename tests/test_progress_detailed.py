#!/usr/bin/env python3
"""详细测试进度条显示问题"""

import sys
import os
import time
sys.path.insert(0, os.path.abspath("."))

from intelli_crawler.ui.progress import ProgressReporter

def test_progress_with_delay():
    """测试带延迟的进度条"""
    print("开始测试进度条显示...")
    print("=" * 50)
    
    # 测试1: 快速进度条（可能看不到）
    print("\n测试1: 快速进度条（10个项目，每个0.1秒）")
    reporter1 = ProgressReporter(enabled=True)
    reporter1.start(total=10)
    
    for i in range(10):
        time.sleep(0.1)
        reporter1.advance(success=True, current_url=f"https://fast.example.com/{i}")
    
    reporter1.close()
    print("测试1完成")
    
    # 测试2: 慢速进度条（应该能看到）
    print("\n测试2: 慢速进度条（5个项目，每个1秒）")
    reporter2 = ProgressReporter(enabled=True)
    reporter2.start(total=5)
    
    for i in range(5):
        print(f"处理第 {i+1} 个项目...")
        time.sleep(1.0)
        reporter2.advance(success=True, current_url=f"https://slow.example.com/{i}")
    
    reporter2.close()
    print("测试2完成")
    
    # 测试3: 禁用进度条
    print("\n测试3: 禁用进度条（3个项目，每个0.5秒）")
    reporter3 = ProgressReporter(enabled=False)
    reporter3.start(total=3)
    
    for i in range(3):
        time.sleep(0.5)
        reporter3.advance(success=True, current_url=f"https://disabled.example.com/{i}")
    
    reporter3.close()
    print("测试3完成")
    
    print("\n" + "=" * 50)
    print("所有测试完成")

if __name__ == "__main__":
    test_progress_with_delay()