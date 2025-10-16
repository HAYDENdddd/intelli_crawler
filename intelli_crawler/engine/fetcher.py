"""HTTP fetching with anti-bot strategy integration."""

from __future__ import annotations

import time
import re
from dataclasses import dataclass, field
from threading import Lock, get_ident
from typing import Any, Dict
from urllib.parse import urlparse

import httpx
import structlog

from ..config import GlobalConfig, SourceConfig
from ..infra import ProxyPool, UserAgentPool
from .antibot import strategies
from .antibot.chain import AntiBotContext, AntiBotChain, RequestDirective


@dataclass(slots=True)
class FetchRequest:
    """Input for the fetcher."""

    url: str
    method: str = "GET"
    params: dict[str, Any] | None = None
    data: dict[str, Any] | None = None
    headers: dict[str, str] | None = None
    cookies: dict[str, str] | None = None
    timeout: float | None = None
    force_browser: bool = False
    # When using headless browser, optionally wait for a CSS selector to appear
    wait_selector: str | None = None
    # Scroll the page bottom N rounds to trigger lazy loading
    scroll_rounds: int = 0
    scroll_pause_ms: int = 300
    # Click a "load more" button selector N times
    click_more_selector: str | None = None
    click_more_times: int = 0
    click_wait_selector: str | None = None
    # Auto interactions: intelligently decide between scroll and click
    auto_interactions: bool = False
    auto_max_rounds: int = 0
    auto_stall_rounds: int = 0
    prefer_scroll_first: bool = True


@dataclass(slots=True)
class FetchResponse:
    """Standardised response wrapper."""

    url: str
    status_code: int
    text: str
    headers: Dict[str, str]
    raw: httpx.Response | None = field(repr=False, default=None)


class Fetcher:
    """Coordinate request execution and anti-bot strategy chain."""

    def __init__(
        self,
        global_config: GlobalConfig,
        proxy_pool: ProxyPool | None,
        ua_pool: UserAgentPool | None,
        logger: structlog.BoundLogger | None = None,
    ) -> None:
        self.global_config = global_config
        self.proxy_pool = proxy_pool
        self.ua_pool = ua_pool
        self.logger = logger or structlog.get_logger("intelli_crawler.fetcher")
        # 在未启用 UA 轮换时为 HTTPX 设置一个更“像浏览器”的默认 UA，降低 403/反爬概率。
        # 若配置中提供了 UA 列表，则优先选择 Windows UA；否则使用列表首项。
        default_ua: str | None = None
        try:
            ua_list = self.global_config.user_agent_list
            if isinstance(ua_list, list) and ua_list:
                default_ua = next((ua for ua in ua_list if "Windows NT" in ua), ua_list[0])
        except Exception:
            default_ua = None
        self._client = httpx.Client(
            follow_redirects=True,
            timeout=15,
            headers={"User-Agent": default_ua} if default_ua else None,
        )
        self._browser_sessions: dict[int, _PlaywrightSession] = {}
        self._browser_lock = Lock()

    def close(self) -> None:
        self._client.close()
        with self._browser_lock:
            for session in self._browser_sessions.values():
                try:
                    session.close()
                except Exception:  # noqa: BLE001
                    continue
            self._browser_sessions.clear()

    def fetch(self, source: SourceConfig, request: FetchRequest) -> FetchResponse:
        context, chain = self._build_chain(source)
        last_error: Exception | None = None
        while True:
            directive = chain.prepare(context)
            req_headers = dict(request.headers or {})
            if directive.headers:
                req_headers.update(directive.headers)
            if request.force_browser:
                directive.use_browser = True
            timeout = request.timeout or directive.timeout or 20
            proxies = (
                {"http": directive.proxy, "https": directive.proxy} if directive.proxy else None
            )

            if directive.delay:
                time.sleep(min(directive.delay, 5.0))

            try:
                if directive.use_browser:
                    response = self._fetch_via_browser(request, req_headers, timeout, source)
                else:
                    request_kwargs: dict[str, Any] = {
                        "method": request.method,
                        "url": request.url,
                        "params": request.params,
                        "data": request.data,
                        "headers": req_headers,
                        "cookies": request.cookies,
                        "timeout": timeout,
                    }
                    if proxies:
                        request_kwargs["proxies"] = proxies
                    response = self._client.request(**request_kwargs)
                    adjusted = self._maybe_solve_aliyun_waf(response, request, req_headers)
                    if adjusted is not None:
                        response = adjusted
                if self._is_failure(response):
                    chain.notify_failure(context, response, None)
                    last_error = RuntimeError(f"Unexpected status {response.status_code}")
                else:
                    chain.notify_success(context, response)
                    return FetchResponse(
                        url=str(response.url),
                        status_code=response.status_code,
                        text=response.text,
                        headers=dict(response.headers),
                        raw=response if isinstance(response, httpx.Response) else None,
                    )
            except Exception as exc:  # noqa: BLE001
                self.logger.warning(
                    "fetch_error",
                    url=request.url,
                    attempt=context.attempt,
                    error=str(exc),
                )
                chain.notify_failure(context, None, exc)
                last_error = exc

            if not chain.should_retry(context):
                break

        raise RuntimeError(
            f"Fetch failed after {context.max_attempts} attempts: {request.url}"
        ) from last_error

    # ------------------------------------------------------------------
    def _build_chain(self, source: SourceConfig) -> tuple[AntiBotContext, AntiBotChain]:
        return strategies.build_chain(source, self.global_config, self.proxy_pool, self.ua_pool)

    def _fetch_via_browser(
        self, request: FetchRequest, headers: dict[str, str], timeout: float, source: "SourceConfig"
    ) -> "BrowserResponse":
        """Use Playwright to retrieve dynamic pages when configured."""

        session = self._ensure_browser_session(headers, source)
        return session.fetch(
            request.url,
            headers,
            timeout,
            wait_selector=request.wait_selector,
            scroll_rounds=request.scroll_rounds,
            scroll_pause_ms=request.scroll_pause_ms,
            click_more_selector=request.click_more_selector,
            click_more_times=request.click_more_times,
            click_wait_selector=request.click_wait_selector,
            auto_interactions=request.auto_interactions,
            auto_max_rounds=request.auto_max_rounds,
            auto_stall_rounds=request.auto_stall_rounds,
            prefer_scroll_first=request.prefer_scroll_first,
        )

    def _ensure_browser_session(
        self, headers: dict[str, str], source: "SourceConfig"
    ) -> "_PlaywrightSession":
        thread_id = get_ident()
        with self._browser_lock:
            session = self._browser_sessions.get(thread_id)
            if session is None:
                session = _PlaywrightSession(headers.get("User-Agent"), source)
                self._browser_sessions[thread_id] = session
            return session

    def _maybe_solve_aliyun_waf(
        self, response: Any, request: FetchRequest, headers: dict[str, str]
    ) -> httpx.Response | None:
        if not isinstance(response, httpx.Response):
            return None
        text = response.text
        if "acw_sc__v2" not in text and "var arg1" not in text:
            return None
        match = re.search(r"var\\s+arg1='([0-9a-fA-F]+)'", text)
        if not match:
            return None
        arg1 = match.group(1)
        if len(arg1) < 60:
            return None
        cookie_value = arg1[10:60]
        url = urlparse(request.url)
        domain = url.hostname or ""
        self._client.cookies.set("acw_sc__v2", cookie_value, domain=domain, path="/")
        request_kwargs: dict[str, Any] = {
            "method": request.method,
            "url": request.url,
            "params": request.params,
            "data": request.data,
            "headers": headers,
            "cookies": request.cookies,
            "timeout": request.timeout or 20,
            "follow_redirects": True,
        }
        retry_response = self._client.request(**request_kwargs)
        return retry_response

    @staticmethod
    def _is_failure(response: Any) -> bool:
        status_code = getattr(response, "status_code", 0)
        if status_code >= 500:
            return True
        if status_code in {401, 403, 429}:
            return True
        return False


@dataclass
class BrowserResponse:
    url: str
    status_code: int
    text: str
    headers: Dict[str, str]


class _PlaywrightSession:
    def __init__(self, user_agent: str | None, source_config: "SourceConfig | None" = None) -> None:
        self._user_agent = user_agent
        self._source_config = source_config
        self._lock = Lock()
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    def _ensure_started(self) -> None:
        if self._playwright is not None:
            return
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "Playwright support requires installing the 'playwright' package."
            ) from exc

        # 获取反爬虫策略配置
        anti_scraping = (
            self._source_config.anti_scraping_strategies if self._source_config else None
        )

        # 检查是否启用无头模式，默认为True
        headless_mode = True
        if anti_scraping and hasattr(anti_scraping, "headless_mode"):
            headless_mode = anti_scraping.headless_mode

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless=headless_mode,
            args=[
                "--ignore-ssl-errors=yes",
                "--ignore-certificate-errors",
                "--ignore-certificate-errors-spki-list",
                "--disable-web-security",
                "--allow-running-insecure-content",
            ],
        )

        # 设置视窗大小
        viewport_size = (1920, 1080)  # 默认值
        if anti_scraping and hasattr(anti_scraping, "viewport_size"):
            viewport_size = anti_scraping.viewport_size

        # 为中文站点在 Windows 上提升兼容性：设置中文语言与时区，减少因语言/地区导致的重定向或内容缺失。
        try:
            self._context = self._browser.new_context(
                user_agent=self._user_agent,
                locale="zh-CN",
                timezone_id="Asia/Shanghai",
                viewport={"width": viewport_size[0], "height": viewport_size[1]},
                ignore_https_errors=True,  # 忽略SSL错误
            )
        except TypeError:
            # 某些老版本 Playwright 不支持上述参数，回退到最小上下文。
            self._context = self._browser.new_context(
                user_agent=self._user_agent,
                ignore_https_errors=True,  # 忽略SSL错误
            )

        # 设置额外的HTTP头部
        if (
            anti_scraping
            and hasattr(anti_scraping, "extra_headers")
            and anti_scraping.extra_headers
        ):
            self._context.set_extra_http_headers(anti_scraping.extra_headers)

        # 注入stealth.js脚本以绕过浏览器自动化检测
        if anti_scraping and getattr(anti_scraping, "use_stealth_js", False):
            try:
                import os

                stealth_js_path = os.path.join(
                    os.path.dirname(__file__), "..", "..", "stealth.min.js"
                )
                if os.path.exists(stealth_js_path):
                    with open(stealth_js_path, "r", encoding="utf-8") as f:
                        stealth_js = f.read()
                    self._context.add_init_script(stealth_js)
            except Exception:
                # 如果stealth.js加载失败，继续执行但不注入脚本
                pass

        self._page = self._context.new_page()

    def fetch(
        self,
        url: str,
        headers: dict[str, str],
        timeout: float,
        *,
        wait_selector: str | None = None,
        scroll_rounds: int = 0,
        scroll_pause_ms: int = 300,
        click_more_selector: str | None = None,
        click_more_times: int = 0,
        click_wait_selector: str | None = None,
        auto_interactions: bool = False,
        auto_max_rounds: int = 0,
        auto_stall_rounds: int = 0,
        prefer_scroll_first: bool = True,
    ) -> BrowserResponse:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

        timeout_ms = int(max(timeout, 30.0) * 1000)
        with self._lock:
            self._ensure_started()
            self._context.set_extra_http_headers(headers or {})
            response = None
            aggregated_parts: list[str] = []
            seen_urls: set[str] = set()
            try:
                response = self._page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            except PlaywrightTimeoutError as exc:
                raise RuntimeError(f"Playwright timeout: {exc}") from exc
            # If caller provided a selector, wait for it to appear to ensure dynamic content is ready
            if wait_selector:
                try:
                    self._page.wait_for_selector(wait_selector, timeout=timeout_ms)
                except PlaywrightTimeoutError as exc:
                    raise RuntimeError(
                        f"Playwright selector wait timeout for '{wait_selector}': {exc}"
                    ) from exc
            # Auto interactions: intelligently mix scroll and click
            if auto_interactions and auto_max_rounds > 0:
                item_selector = wait_selector or click_wait_selector
                items_count = 0
                stable_rounds = 0
                for _ in range(int(auto_max_rounds)):
                    # Scroll first if preferred
                    if prefer_scroll_first:
                        try:
                            self._page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                        except Exception:
                            pass
                        self._page.wait_for_timeout(max(0, int(scroll_pause_ms)))
                    # Try clicking load-more regardless of visibility to avoid false negatives.
                    # Do not break the loop on timeout; the button may appear in subsequent rounds.
                    if click_more_selector:
                        try:
                            locator = self._page.locator(click_more_selector)
                            # If the element exists in DOM, attempt to click the first match.
                            if locator.count() > 0:
                                try:
                                    locator.first.click(timeout=min(timeout_ms, 3000))
                                except PlaywrightTimeoutError:
                                    # Keep looping; the page may not be ready yet.
                                    pass
                                if click_wait_selector:
                                    try:
                                        self._page.wait_for_selector(
                                            click_wait_selector, timeout=timeout_ms
                                        )
                                    except PlaywrightTimeoutError:
                                        pass
                                self._page.wait_for_timeout(max(0, int(scroll_pause_ms)))
                        except Exception:
                            # Any locator/query issues should not stop the auto loop.
                            pass
                    # Count items to detect progress
                    new_count = items_count
                    if item_selector:
                        try:
                            new_count = self._page.locator(item_selector).count()
                        except Exception:
                            new_count = items_count
                        # Opportunistically aggregate new items' HTML by unique link to avoid virtualization limits
                        try:
                            locator = self._page.locator(item_selector)
                            count = locator.count()
                            for i in range(count):
                                try:
                                    item = locator.nth(i)
                                    # Use first link href inside the item as unique key
                                    href = None
                                    try:
                                        link = item.locator("a[href]").first
                                        href = link.get_attribute("href")
                                    except Exception:
                                        href = None
                                    if not href or href in seen_urls:
                                        continue
                                    seen_urls.add(href)
                                    try:
                                        html_piece = item.evaluate("el => el.outerHTML")
                                    except Exception:
                                        try:
                                            html_piece = item.inner_html()
                                        except Exception:
                                            html_piece = ""
                                    if html_piece:
                                        aggregated_parts.append(str(html_piece))
                                except Exception:
                                    continue
                        except Exception:
                            pass
                    if new_count <= items_count:
                        stable_rounds += 1
                    else:
                        stable_rounds = 0
                        items_count = new_count
                    if stable_rounds >= max(1, int(auto_stall_rounds)):
                        break
            else:
                # Manual interactions: scroll then click
                if scroll_rounds and scroll_rounds > 0:
                    for _ in range(int(scroll_rounds)):
                        try:
                            self._page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                        except Exception:
                            pass
                        self._page.wait_for_timeout(max(0, int(scroll_pause_ms)))
                if click_more_selector and click_more_times > 0:
                    for _ in range(int(click_more_times)):
                        try:
                            self._page.click(click_more_selector, timeout=timeout_ms)
                        except PlaywrightTimeoutError:
                            break
                        if click_wait_selector:
                            try:
                                self._page.wait_for_selector(
                                    click_wait_selector, timeout=timeout_ms
                                )
                            except PlaywrightTimeoutError:
                                pass
                        self._page.wait_for_timeout(max(0, int(scroll_pause_ms)))
            self._page.wait_for_timeout(250)
            content = self._page.content()
            # Append aggregated item HTML parts collected during auto interactions
            if aggregated_parts:
                try:
                    content = content + "\n" + "\n".join(aggregated_parts)
                except Exception:
                    pass
            final_url = self._page.url
            status_code = response.status if response else 200
            response_headers = dict(response.headers) if response else {}
            return BrowserResponse(
                url=final_url,
                status_code=status_code,
                text=content,
                headers=response_headers,
            )

    def close(self) -> None:
        with self._lock:
            if self._page is not None:
                self._page.close()
                self._page = None
            if self._context is not None:
                self._context.close()
                self._context = None
            if self._browser is not None:
                self._browser.close()
                self._browser = None
            if self._playwright is not None:
                self._playwright.stop()
                self._playwright = None


__all__ = ["Fetcher", "FetchRequest", "FetchResponse", "BrowserResponse"]
