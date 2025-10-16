#!/usr/bin/env python3
"""
测试从雪球主页点击7X24标签的流程
"""

import asyncio
from playwright.async_api import async_playwright
import re
from datetime import datetime


async def test_xueqiu_homepage():
    """测试从雪球主页点击7X24标签"""
    async with async_playwright() as p:
        # 启动浏览器
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )

        page = await context.new_page()

        try:
            print("正在访问雪球主页...")
            await page.goto("https://xueqiu.com/", wait_until="domcontentloaded", timeout=30000)

            # 等待页面加载
            await page.wait_for_timeout(3000)
            print(f"页面标题: {await page.title()}")

            # 等待7X24标签出现
            print("等待7X24标签出现...")
            try:
                tab_element = await page.wait_for_selector("text=7X24", timeout=15000)
                print("找到7X24标签")
            except Exception as e:
                print(f"未找到7X24标签: {e}")
                return

            # 点击7X24标签
            print("点击7X24标签...")
            try:
                await tab_element.click()
                await page.wait_for_timeout(3000)
                print("成功点击7X24标签")
            except Exception as e:
                print(f"点击7X24标签失败: {e}")
                return

            # 等待时间线容器加载
            print("等待时间线容器加载...")
            try:
                timeline = await page.wait_for_selector(".style_home__timeline_1Tz", timeout=15000)
                print("找到时间线容器")
            except Exception as e:
                print(f"未找到时间线容器: {e}")
                # 尝试其他可能的选择器
                alternative_selectors = [
                    '[class*="timeline"]',
                    ".timeline",
                    ".news-list",
                    ".feed-list",
                ]
                for selector in alternative_selectors:
                    try:
                        timeline = await page.wait_for_selector(selector, timeout=5000)
                        print(f"找到替代时间线容器: {selector}")
                        break
                    except:
                        continue
                else:
                    print("未找到任何时间线容器")
                    return

            # 获取时间线内容
            print("获取时间线内容...")
            timeline_text = await timeline.inner_text()
            print(f"时间线内容长度: {len(timeline_text)}")

            # 显示前500个字符
            print("时间线内容预览:")
            print(timeline_text[:500])
            print("...")

            # 按行分割内容并查找时间戳
            lines = timeline_text.split("\n")
            print(f"总行数: {len(lines)}")

            # 查找包含时间戳的行（格式：HH:MM）
            time_pattern = re.compile(r"^\d{2}:\d{2}$")
            time_lines = []

            for i, line in enumerate(lines):
                line = line.strip()
                if time_pattern.match(line):
                    time_lines.append((i, line))

            print(f"找到 {len(time_lines)} 个时间戳:")
            for i, (line_num, time_str) in enumerate(time_lines[:5]):
                print(f"  {i+1}. 行{line_num}: {time_str}")
                # 显示时间戳后的内容
                if line_num + 1 < len(lines):
                    next_line = lines[line_num + 1].strip()
                    print(f"     内容: {next_line[:100]}...")

            # 检查是否包含冒号（用于关键词过滤）
            colon_count = timeline_text.count(":")
            print(f"内容中包含冒号的数量: {colon_count}")

        except Exception as e:
            print(f"测试过程中出现错误: {e}")

        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(test_xueqiu_homepage())
