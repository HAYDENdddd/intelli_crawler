#!/usr/bin/env python3
"""
手动测试雪球7x24内容抓取的脚本
模拟爬虫的完整流程来调试问题
"""

import asyncio
from playwright.async_api import async_playwright
import re
from datetime import datetime


async def test_xueqiu_manual():
    """手动测试雪球7x24内容抓取"""
    async with async_playwright() as p:
        # 启动浏览器
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )

        page = await context.new_page()

        try:
            print("正在访问雪球7x24页面...")
            await page.goto("https://xueqiu.com/7X24", wait_until="domcontentloaded", timeout=30000)

            # 等待页面加载
            await page.wait_for_timeout(3000)

            # 点击7x24标签
            print("点击7x24标签...")
            try:
                tab_element = await page.wait_for_selector("text=7X24", timeout=10000)
                await tab_element.click()
                await page.wait_for_timeout(3000)
                print("成功点击7x24标签")
            except Exception as e:
                print(f"点击7x24标签失败: {e}")

            # 等待时间线容器加载
            print("等待时间线容器加载...")
            try:
                timeline = await page.wait_for_selector(".style_home__timeline_1Tz", timeout=15000)
                print("找到时间线容器")
            except Exception as e:
                print(f"未找到时间线容器: {e}")
                return

            # 获取时间线内容
            print("获取时间线内容...")
            timeline_text = await timeline.inner_text()
            print(f"时间线内容长度: {len(timeline_text)}")

            # 按行分割内容
            lines = timeline_text.split("\n")
            print(f"总行数: {len(lines)}")

            # 查找包含时间戳的行（格式：HH:MM）
            time_pattern = re.compile(r"^\d{2}:\d{2}$")
            news_items = []
            current_item = {}

            for i, line in enumerate(lines):
                line = line.strip()
                if not line:
                    continue

                # 检查是否是时间戳
                if time_pattern.match(line):
                    # 保存前一个条目
                    if current_item and "content" in current_item:
                        news_items.append(current_item)

                    # 开始新条目
                    current_item = {"published_at": line, "content": "", "title": ""}
                elif current_item and "published_at" in current_item:
                    # 这是新闻内容
                    if not current_item["title"]:
                        current_item["title"] = line
                    current_item["content"] += line + " "

            # 添加最后一个条目
            if current_item and "content" in current_item:
                news_items.append(current_item)

            print(f"\n找到 {len(news_items)} 条新闻:")
            for i, item in enumerate(news_items[:5]):  # 只显示前5条
                print(f"\n--- 新闻 {i+1} ---")
                print(f"时间: {item['published_at']}")
                print(f"标题: {item['title'][:100]}...")
                print(f"内容: {item['content'][:200]}...")

                # 检查是否包含冒号（用于关键词过滤）
                if ":" in item["content"]:
                    print("✓ 包含冒号，符合过滤条件")
                else:
                    print("✗ 不包含冒号，不符合过滤条件")

            # 生成输出文件内容
            print("\n生成输出文件内容...")
            output_content = ""
            for i, item in enumerate(news_items):
                if ":" in item["content"]:  # 应用关键词过滤
                    output_content += f"{i+1}. {item['title']}\n"
                    output_content += f"发布时间：{item['published_at']}\n"
                    output_content += f"抓取时间：{datetime.now().strftime('%Y-%m-%dT%H:%M:%SZ')}\n"
                    output_content += f"{item['content'].strip()}\n"
                    output_content += f"链接：https://xueqiu.com/7X24\n\n"

            print(f"过滤后的内容长度: {len(output_content)}")
            if output_content:
                print("输出内容预览:")
                print(output_content[:500] + "...")
            else:
                print("没有符合过滤条件的内容")

        except Exception as e:
            print(f"测试过程中出现错误: {e}")

        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(test_xueqiu_manual())
