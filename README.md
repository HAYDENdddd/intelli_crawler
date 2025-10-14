# Intelli-Crawler

命令行驱动的多源新闻/资讯爬虫框架。核心能力：
- 以 YAML/JSON 配置描述信息源，支持 Cron/Interval 调度与增量去重。
- httpx + Playwright 可选渲染链路，内置代理/UA/重试等反爬策略。
- CLI 覆盖源管理、批量运行、历史与日志查询，输出 JSON/CSV/TXT/SQLite/Mongo。
- Rich 进度与结构化日志，方便排查与自动化集成。

---

## 安装

```bash
git clone <repo>
cd intelli_crawler

# 推荐：使用 Poetry 管理依赖
pip install poetry
poetry install

# 需要浏览器渲染时额外安装
poetry run playwright install chromium
```

可选环境变量：

```bash
export INTELLI_CRAWLER_HOME=/path/to/project  # 指定自定义数据目录
```

---

## 常用命令

```bash
# 查看 CLI 总览 / 子命令帮助
poetry run intelli-crawler --help                               # 显示主命令帮助信息
poetry run intelli-crawler source --help                        # 显示信息源子命令帮助

# 信息源管理
poetry run intelli-crawler source list                          # 列出所有配置的信息源
poetry run intelli-crawler source add "My Source"               # 创建新的信息源配置
poetry run intelli-crawler source edit "My Source"              # 编辑现有信息源配置
poetry run intelli-crawler source remove "My Source" --yes      # 删除信息源并清空历史记录

# 运行
poetry run intelli-crawler source run "Foresight News"          # 立即执行指定信息源
poetry run intelli-crawler source run-all                       # 智能并发执行全部信息源
poetry run intelli-crawler source run "Foresight News" --quiet  # 静默模式，仅输出统计结果

# 时间窗口（ISO8601 或每日窗口）
poetry run intelli-crawler source run "Foresight News" \        # 指定绝对时间范围执行
  --since 2025-10-15T02:00+08:00 --until 2025-10-15T05:00+08:00
poetry run intelli-crawler source run-all \                     # 指定每日时间窗口批量执行
  --window-start 08:00 --window-duration 24h

# 历史管理
poetry run intelli-crawler source history "Foresight News" --limit 10  # 查看信息源抓取历史记录
poetry run intelli-crawler source reset "Foresight News" --yes         # 清空指定源的历史记录
poetry run intelli-crawler source reset-all --yes                      # 清空所有源的历史记录

# 日志查看
poetry run intelli-crawler log list                             # 列出所有可用的日志文件
poetry run intelli-crawler log show --source "Foresight News" --tail 200  # 查看指定源的最新日志
```

批量运行结果会在表格中展示「窗口过滤」计数，便于识别时间条件筛掉的记录。

---

## 配置速览

信息源位于 `data/sources/*.yaml`，示例：

```yaml
source_name: Foresight News                    # 信息源名称，用于CLI命令中的标识
site_type: news                               # 站点类型：news/blog/forum等
target_url: https://foresightnews.pro/news    # 目标页面URL，爬虫的入口地址
entry_pattern: div.list_body a.news_body_title # CSS选择器，用于提取文章链接
detail_pattern:                               # 详情页面的内容提取规则
  title: div.list_body .topic                 # 文章标题的CSS选择器
  published_at: div.list_body .topic-time     # 发布时间的CSS选择器
  content: div.detail-body                    # 文章正文的CSS选择器
schedule:                                     # 调度配置
  type: cron          # cron / interval / once # 调度类型：定时/间隔/一次性
  value: "0 8 * * *"  # 每天 08:00            # Cron表达式或间隔时间
time_range:                                   # 时间范围过滤
  relative: last_24_hours                     # 相对时间：抓取最近24小时的内容
output_format: txt    # json / csv / txt / mongodb / sqlite # 输出格式选择
anti_scraping_strategies:                     # 反爬虫策略配置
  user_agent_rotation: true                   # 启用User-Agent轮换
  retry_on_fail: 2                           # 失败重试次数
  use_headless_browser: false                # 是否使用无头浏览器渲染
enable_incremental: true                      # 启用增量抓取，避免重复内容
```

全局设置 (`data/global_config.yaml`) 控制线程池大小、默认延迟、目录位置以及代理/UA 列表。

---

## 开发与测试

```bash
# 单元测试
poetry run pytest
poetry run pytest tests/app/test_cli_commands.py -q

# 代码风格（可选）
poetry install --with dev
poetry run ruff check .
poetry run black .
```

CLI 运行时默认显示 Rich 进度条；如果终端或其它任务已占用 live display，会自动退回静默模式，执行仍然继续。日志写入 `logs/`，爬取结果保存在 `data/outputs/`。

---

## 常见问题

- **Playwright 未安装**：报错 `No module named 'playwright'`，按「安装」章节补齐依赖即可。
- **想要仅抓最近 N 小时内容**：运行时加 `--since/--until` 或 `--window-start + --window-duration`，窗口筛选会基于 `published_at` / `timestamp` 字段自动匹配。
- **已有旧 CLI 脚本**：历史命令（如 `run-now`, `list-sources`）仍保留为隐藏入口，会提示迁移到新语法。

Enjoy crawling! 🚀
