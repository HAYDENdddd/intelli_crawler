#!/usr/bin/env python3
"""简单测试进度条显示"""

from intelli_crawler.ui.progress import ProgressReporter
import time

def test_progress_display():
    print("测试1: enabled=True (应该显示进度条)")
    reporter = ProgressReporter(enabled=True)
    reporter.start(total=5)
    
    for i in range(5):
        time.sleep(0.5)
        reporter.advance(success=True, current_url=f"https://example.com/{i}")
    
    reporter.close()
    print("测试1完成\n")
    
    print("测试2: enabled=False (不应该显示进度条)")
    reporter2 = ProgressReporter(enabled=False)
    reporter2.start(total=3)
    
    for i in range(3):
        time.sleep(0.3)
        reporter2.advance(success=True, current_url=f"https://test.com/{i}")
    
    reporter2.close()
    print("测试2完成")

if __name__ == "__main__":
    test_progress_display()
