#!/usr/bin/env python3
"""
最终测试雪球7x24抓取流程
"""

import asyncio
from playwright.async_api import async_playwright
import re
from datetime import datetime

async def test_xueqiu_final():
    """最终测试雪球7x24抓取流程"""
    async with async_playwright() as p:
        # 启动浏览器
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )
        
        page = await context.new_page()
        
        try:
            print("正在访问雪球主页...")
            await page.goto('https://xueqiu.com/', wait_until='domcontentloaded', timeout=30000)
            
            # 等待页面加载
            await page.wait_for_timeout(3000)
            print(f"页面标题: {await page.title()}")
            
            # 等待并点击7X24标签
            print("等待7X24标签出现...")
            try:
                tab_element = await page.wait_for_selector('text=7X24', timeout=15000)
                print("找到7X24标签，点击...")
                await tab_element.click()
                await page.wait_for_timeout(3000)
                print("成功点击7X24标签")
            except Exception as e:
                print(f"点击7X24标签失败: {e}")
                return
            
            # 等待时间线容器加载
            print("等待时间线容器加载...")
            try:
                timeline = await page.wait_for_selector('.style_home__timeline_1Tz', timeout=15000)
                print("找到时间线容器")
            except Exception as e:
                print(f"未找到时间线容器: {e}")
                return
            
            # 滚动加载更多内容
            print("开始滚动加载更多内容...")
            for i in range(5):
                print(f"第 {i+1} 次滚动...")
                # 滚动到页面底部
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(2000)  # 等待2秒让内容加载
                
                # 尝试点击"更多"按钮（如果存在）
                try:
                    more_button = await page.query_selector('text=更多')
                    if more_button:
                        print("找到'更多'按钮，点击...")
                        await more_button.click()
                        await page.wait_for_timeout(2000)
                        print("成功点击'更多'按钮")
                    else:
                        print("未找到'更多'按钮")
                except Exception as e:
                    print(f"点击'更多'按钮时出错: {e}")
            
            print("滚动加载完成")
            
            # 获取时间线内容
            print("获取时间线内容...")
            timeline_text = await timeline.inner_text()
            
            # 按行分割内容
            lines = timeline_text.split('\n')
            
            # 查找包含时间戳的行（格式：HH:MM）
            time_pattern = re.compile(r'^\d{2}:\d{2}$')
            news_items = []
            
            i = 0
            while i < len(lines):
                line = lines[i].strip()
                if time_pattern.match(line):
                    # 找到时间戳，获取后续内容
                    time_str = line
                    content_lines = []
                    
                    # 收集时间戳后的内容行，直到下一个时间戳或结束
                    j = i + 1
                    while j < len(lines):
                        next_line = lines[j].strip()
                        if time_pattern.match(next_line):
                            break
                        if next_line:  # 非空行
                            content_lines.append(next_line)
                        j += 1
                    
                    if content_lines:
                        content = ' '.join(content_lines)
                        # 应用关键词过滤（包含冒号）
                        if ':' in content or ':' in time_str:
                            news_items.append({
                                'time': time_str,
                                'content': content,
                                'title': content[:50] + '...' if len(content) > 50 else content
                            })
                    
                    i = j
                else:
                    i += 1
            
            print(f"\n找到 {len(news_items)} 条符合条件的新闻:")
            for idx, item in enumerate(news_items[:5], 1):
                print(f"\n{idx}. 时间: {item['time']}")
                print(f"   标题: {item['title']}")
                print(f"   内容: {item['content'][:100]}...")
            
            # 生成输出内容
            if news_items:
                timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                output_content = f"# 雪球7x24资讯 - {timestamp}\n\n"
                
                for item in news_items:
                    output_content += f"## {item['time']}\n"
                    output_content += f"**标题:** {item['title']}\n\n"
                    output_content += f"**内容:** {item['content']}\n\n"
                    output_content += "---\n\n"
                
                # 保存到文件
                output_file = f"data/outputs/xueqiu-{timestamp}.txt"
                with open(output_file, 'w', encoding='utf-8') as f:
                    f.write(output_content)
                
                print(f"\n成功生成输出文件: {output_file}")
                print(f"共抓取 {len(news_items)} 条新闻")
            else:
                print("\n未找到符合条件的新闻内容")
            
        except Exception as e:
            print(f"测试过程中出现错误: {e}")
        
        finally:
            await browser.close()

if __name__ == "__main__":
    asyncio.run(test_xueqiu_final())