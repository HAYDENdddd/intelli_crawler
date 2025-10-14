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
        self._client = httpx.Client(follow_redirects=True, timeout=15)
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
            proxies = {"http": directive.proxy, "https": directive.proxy} if directive.proxy else None

            if directive.delay:
                time.sleep(min(directive.delay, 5.0))

            try:
                if directive.use_browser:
                    response = self._fetch_via_browser(request, req_headers, timeout)
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

        raise RuntimeError(f"Fetch failed after {context.max_attempts} attempts: {request.url}") from last_error

    # ------------------------------------------------------------------
    def _build_chain(self, source: SourceConfig) -> tuple[AntiBotContext, AntiBotChain]:
        return strategies.build_chain(source, self.global_config, self.proxy_pool, self.ua_pool)

    def _fetch_via_browser(
        self, request: FetchRequest, headers: dict[str, str], timeout: float
    ) -> "BrowserResponse":
        """Use Playwright to retrieve dynamic pages when configured."""

        session = self._ensure_browser_session(headers)
        return session.fetch(request.url, headers, timeout)

    def _ensure_browser_session(self, headers: dict[str, str]) -> "_PlaywrightSession":
        thread_id = get_ident()
        with self._browser_lock:
            session = self._browser_sessions.get(thread_id)
            if session is None:
                session = _PlaywrightSession(headers.get("User-Agent"))
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
    def __init__(self, user_agent: str | None) -> None:
        self._user_agent = user_agent
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
            raise RuntimeError("Playwright support requires installing the 'playwright' package.") from exc
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=True)
        self._context = self._browser.new_context(user_agent=self._user_agent)
        self._page = self._context.new_page()

    def fetch(self, url: str, headers: dict[str, str], timeout: float) -> BrowserResponse:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

        timeout_ms = int(max(timeout, 30.0) * 1000)
        with self._lock:
            self._ensure_started()
            self._context.set_extra_http_headers(headers or {})
            response = None
            try:
                response = self._page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            except PlaywrightTimeoutError as exc:
                raise RuntimeError(f"Playwright timeout: {exc}") from exc
            self._page.wait_for_timeout(250)
            content = self._page.content()
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
