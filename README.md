# Intelli-Crawler

命令行驱动的多源新闻/资讯爬虫框架。核心能力：
- 以 YAML/JSON 配置描述信息源，支持 Cron/Interval 调度与增量去重。
- httpx + Playwright 可选渲染链路，内置代理/UA/重试等反爬策略。
- CLI 覆盖源管理、批量运行、历史与日志查询，输出 JSON/CSV/TXT/SQLite/Mongo。
- Rich 进度与结构化日志，方便排查与自动化集成。

---

## 安装

建议仅选择以下两种安装路径之一（不要混用）：

1) 使用 Poetry（推荐）

```bash
git clone <repo>
cd intelli_crawler

# 安装 Poetry（推荐 pipx）
# macOS 可：brew install pipx && pipx ensurepath && pipx install poetry
# 或者：pip install --user poetry  （若未安装 pipx）
poetry --version                        # 验证安装成功

# 安装项目依赖（读取 pyproject.toml，无需 requirements.txt）
poetry install

# 如需浏览器渲染（Playwright）
poetry run playwright install chromium
```

- 注意：选择 Poetry 时，不需要也不应执行 `pip install -r requirements.txt`。
- 可选环境变量：

```bash
export INTELLI_CRAWLER_HOME=/path/to/project  # 指定自定义数据目录
```

2) 使用 pip + venv（备用方案，不使用 Poetry）

```bash
git clone <repo>
cd intelli_crawler

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 如需浏览器渲染（Playwright）
playwright install chromium
```

两种方案二选一：推荐 Poetry；若使用 pip 方案，请勿同时运行 `poetry install`。

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
poetry run intelli-crawler source reset "Foresight News"          # 清空指定源的历史记录
poetry run intelli-crawler source reset-all                      # 清空所有源的历史记录

# 日志查看
poetry run intelli-crawler log list                             # 列出所有可用的日志文件
poetry run intelli-crawler log show --source "Foresight News" --tail 200  # 查看指定源的最新日志
```

批量运行结果会在表格中展示「窗口过滤」计数，便于识别时间条件筛掉的记录。

---

## 快速开始顺序

1) 安装依赖：选择 Poetry（推荐）或 pip+venv（详见「安装」）。
2) 可选安装浏览器渲染：`playwright install chromium` 或 `poetry run playwright install chromium`。
3) 创建/编辑信息源：`poetry run intelli-crawler source add "My Source"` 或 `source edit`。
4) 运行单源：`poetry run intelli-crawler source run "My Source"`；批量：`source run-all`。
5) 查看日志：`poetry run intelli-crawler log list`、`log show --source "My Source" --tail 200`。
6) 查看输出：结果保存在 `data/outputs/`；增量历史在 `data/history/`。
7) 设置调度：在源配置 `schedule` 中设定 cron/interval；或使用 CLI 批量运行。

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


## 入口页动态交互（滚动/点击加载更多）

部分列表页内容通过前端动态渲染或滚动/点击「加载更多」后才出现。现在可以在源配置中直接声明入口交互，让爬虫在进入页面后自动完成等待、滚动或点击，并在入口页直接抽取记录。

关键字段（位于 `SourceConfig`）：
- `use_entry_content: true`：入口页直接抽取记录（不再逐条跳详情页）。
- `anti_scraping_strategies.use_headless_browser: true`：启用无头浏览器渲染链路。
- `entry_interactions.wait_selector`：进入页面后等待某个 CSS 选择器出现（确保列表渲染完成）。
- `entry_interactions.scroll_rounds` + `scroll_pause_ms`：下滚 N 次，每次停顿（毫秒），用于触发无限滚动加载。
- `entry_interactions.click_more_selector` + `click_more_times` + `click_wait_selector`：点击「加载更多」按钮若干次，并在每次点击后可选等待一个选择器。

选择器语法扩展：
- 普通文本：`div.item .title`（提取文本）
- 提取属性：`a.link::attr:href`（提取属性）
- 提取片段 HTML：`.content::html`（提取原始 HTML）

通用模板（入口交互注释版）：

```yaml
# 入口页交互的通用结构（根据站点选择滚动或点击）
anti_scraping_strategies:
  use_headless_browser: true                 # 使用浏览器渲染（交互必需）
use_entry_content: true                      # 入口页直接抽取记录（某些站点可改为 false）
entry_interactions:
  wait_selector: '...'                       # 首次加载后等待的选择器
  scroll_rounds: 0                           # 无限滚动次数，0 表示不滚动
  scroll_pause_ms: 300                       # 每次滚动后的停顿（毫秒）
  click_more_selector: '...'                 # 点击“查看更多”按钮的选择器
  click_more_times: 0                        # 点击次数，0 表示不点击
  click_wait_selector: '...'                 # 每次点击后等待的选择器（可选）
```

示例一（滚动加载，新浪 7x24）：

```yaml
source_name: sina
site_type: news
target_url: https://finance.sina.com.cn/7x24/
entry_pattern: 'div.bd_i'                    # 每条新闻块的包裹元素
detail_pattern:
  title: 'p.bd_i_txt_c'                      # 标题（文本）
  published_at: 'div.bd_i_time p.bd_i_time_c' # 发布时间（文本）
  content: 'p.bd_i_txt_c'                    # 内容（文本）
anti_scraping_strategies:
  use_headless_browser: true                 # 使用浏览器渲染
use_entry_content: true                      # 入口页直接抽取记录
entry_interactions:
  wait_selector: 'div.bd_i'                  # 等待列表块出现
  scroll_rounds: 4                           # 向下滚动 4 次加载更多
  scroll_pause_ms: 400                       # 每次滚动后等待 400ms
output_format: txt
```

（运行命令见「常用命令」章节）

示例二（点击加载更多，同花顺）：

```yaml
source_name: ths-newsflash
site_type: news
target_url: https://www.10jqka.com.cn/today/
entry_pattern: '.list-item'                  # 每条记录的包裹元素
detail_pattern:
  title: '.list-item .title'                 # 标题（文本）
  published_at: '.list-item .time'           # 发布时间（文本）
  content: '.list-item .content'             # 内容（文本）
anti_scraping_strategies:
  use_headless_browser: true
use_entry_content: true                      # 入口页直接抽取；若站点专用详情 JSON，可考虑改为 false
entry_interactions:
  click_more_selector: '.more-btn'           # 点击“加载更多”按钮
  click_more_times: 3                        # 连续点击 3 次
  click_wait_selector: '.list-item'          # 每次点击后等待列表项出现/更新
  wait_selector: '.list-item'                # 初始等待列表项就绪
output_format: txt
```

（日志查看命令见「常用命令」章节）

提示：
- 如果页面渲染较慢，可适当增大 `scroll_pause_ms` 或在 `click_wait_selector` 上使用更具体的选择器。
- 若条目结构存在变体，可在 `detail_pattern` 为同一字段提供多选择器列表作为回退。
- 某些站点（如 Odaily）详情数据内嵌在页面 JSON 中，`use_entry_content: true` 会走专用解析；若需点击“查看更多”后覆盖更多记录，可改用 `use_entry_content: false + entry_interactions` 再按普通详情页抓取。


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

---
