#!/usr/bin/env python3
"""
调试雪球7x24页面结构的脚本
检查当前页面的实际DOM结构，找到正确的选择器
"""

import asyncio
from playwright.async_api import async_playwright
import json

async def debug_xueqiu_structure():
    """调试雪球7x24页面结构"""
    async with async_playwright() as p:
        # 启动浏览器
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )
        
        page = await context.new_page()
        
        try:
            print("正在访问雪球7x24页面...")
            await page.goto('https://xueqiu.com/7X24', wait_until='domcontentloaded', timeout=30000)
            
            # 等待页面加载
            await page.wait_for_timeout(5000)
            
            print("页面标题:", await page.title())
            
            # 检查是否需要点击7x24标签
            print("\n检查7x24标签...")
            tab_selectors = [
                'text=7X24',
                'a[href*="7X24"]',
                '[data-tab="7X24"]',
                '.tab-item:has-text("7X24")',
                'li:has-text("7X24")',
                'div:has-text("7X24")'
            ]
            
            for selector in tab_selectors:
                try:
                    element = await page.query_selector(selector)
                    if element:
                        print(f"找到7x24标签: {selector}")
                        await element.click()
                        await page.wait_for_timeout(3000)
                        break
                except Exception as e:
                    continue
            
            # 检查时间线容器
            print("\n检查时间线容器...")
            timeline_selectors = [
                '.style_home__timeline_1Tz',
                '[class*="timeline"]',
                '.timeline',
                '.news-list',
                '.feed-list',
                '.content-list',
                'ul[class*="list"]',
                'div[class*="list"]'
            ]
            
            for selector in timeline_selectors:
                try:
                    elements = await page.query_selector_all(selector)
                    if elements:
                        print(f"找到时间线容器: {selector} (数量: {len(elements)})")
                        # 获取第一个元素的HTML结构
                        html = await elements[0].inner_html()
                        print(f"容器内容预览: {html[:200]}...")
                        break
                except Exception as e:
                    continue
            
            # 检查具体的新闻条目
            print("\n检查新闻条目...")
            item_selectors = [
                'li[class*="item"]',
                'div[class*="item"]',
                '.news-item',
                '.feed-item',
                '.timeline-item',
                'article',
                '[class*="card"]'
            ]
            
            for selector in item_selectors:
                try:
                    elements = await page.query_selector_all(selector)
                    if elements and len(elements) > 0:
                        print(f"找到新闻条目: {selector} (数量: {len(elements)})")
                        # 检查前几个条目的结构
                        for i, element in enumerate(elements[:3]):
                            text = await element.inner_text()
                            if text and len(text.strip()) > 10:
                                print(f"  条目 {i+1}: {text[:100]}...")
                        break
                except Exception as e:
                    continue
            
            # 检查时间戳元素
            print("\n检查时间戳元素...")
            time_selectors = [
                '[class*="time"]',
                '.timestamp',
                '.date',
                'time',
                'span:contains(":")',
                'div:contains(":")'
            ]
            
            for selector in time_selectors:
                try:
                    elements = await page.query_selector_all(selector)
                    if elements:
                        print(f"找到时间戳元素: {selector} (数量: {len(elements)})")
                        for i, element in enumerate(elements[:3]):
                            text = await element.inner_text()
                            if ':' in text:
                                print(f"  时间戳 {i+1}: {text}")
                        break
                except Exception as e:
                    continue
            
            # 获取页面的完整DOM结构（部分）
            print("\n获取页面主要结构...")
            body_html = await page.query_selector('body')
            if body_html:
                html_content = await body_html.inner_html()
                # 查找包含时间格式的内容
                lines = html_content.split('\n')
                time_lines = [line for line in lines if ':' in line and any(char.isdigit() for char in line)]
                print(f"包含时间格式的行数: {len(time_lines)}")
                for line in time_lines[:5]:
                    print(f"  {line.strip()[:100]}...")
            
        except Exception as e:
            print(f"调试过程中出现错误: {e}")
        
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(debug_xueqiu_structure())