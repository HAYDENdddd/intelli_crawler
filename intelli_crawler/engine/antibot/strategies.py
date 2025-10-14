"""Concrete anti-bot strategies used by the chain."""

from __future__ import annotations

import random
from typing import Optional

import httpx

from ...config import GlobalConfig, SourceConfig
from ...infra import ProxyPool, UserAgentPool
from .chain import AntiBotContext, RequestDirective, Strategy


class ProxyStrategy(Strategy):
    """Rotate proxies from the pool when enabled."""

    def __init__(self, pool: ProxyPool | None) -> None:
        self.pool = pool

    def before_request(self, context: AntiBotContext, directive: RequestDirective) -> None:
        if context.source.anti_scraping_strategies.proxy_pool and self.pool and not self.pool.empty:
            directive.proxy = self.pool.get_proxy()

    def after_success(self, context: AntiBotContext, response: httpx.Response) -> None:  # noqa: D401
        # Successful request: nothing special, but hook maintained for completeness.
        return

    def after_failure(self, context: AntiBotContext, response: httpx.Response | None, error: Exception | None) -> None:
        # Force next request to move to another proxy
        if self.pool and not self.pool.empty:
            self.pool.get_proxy()


class UserAgentStrategy(Strategy):
    """Assign or rotate user agents as needed."""

    def __init__(self, pool: UserAgentPool | None) -> None:
        self.pool = pool

    def before_request(self, context: AntiBotContext, directive: RequestDirective) -> None:
        if not context.source.anti_scraping_strategies.user_agent_rotation:
            return
        if self.pool:
            ua = self.pool.get()
        else:
            ua = None
        if ua:
            directive.headers.setdefault("User-Agent", ua)

    def after_success(self, context: AntiBotContext, response: httpx.Response) -> None:
        return

    def after_failure(self, context: AntiBotContext, response: httpx.Response | None, error: Exception | None) -> None:
        return


class DelayStrategy(Strategy):
    """Apply randomized delay to smooth out request cadence."""

    def before_request(self, context: AntiBotContext, directive: RequestDirective) -> None:
        low, high = context.source.anti_scraping_strategies.delay_range
        if low == 0 and high == 0:
            low, high = context.global_config.default_delay_range
        if high <= 0:
            return
        delay = random.uniform(low, high)
        directive.delay = delay

    def after_success(self, context: AntiBotContext, response: httpx.Response) -> None:
        return

    def after_failure(self, context: AntiBotContext, response: httpx.Response | None, error: Exception | None) -> None:
        return


class RetryStrategy(Strategy):
    """Expose retry count from config to the fetch loop."""

    def before_request(self, context: AntiBotContext, directive: RequestDirective) -> None:
        retries = context.source.anti_scraping_strategies.retry_on_fail
        context.max_attempts = max(1, retries + 1)

    def after_success(self, context: AntiBotContext, response: httpx.Response) -> None:
        context.attempt = 1

    def after_failure(self, context: AntiBotContext, response: httpx.Response | None, error: Exception | None) -> None:
        context.attempt += 1


class HeadlessBrowserStrategy(Strategy):
    """Flag usage of Playwright for JS heavy pages."""

    def before_request(self, context: AntiBotContext, directive: RequestDirective) -> None:
        if context.source.anti_scraping_strategies.use_headless_browser:
            directive.use_browser = True

    def after_success(self, context: AntiBotContext, response: httpx.Response) -> None:
        return

    def after_failure(self, context: AntiBotContext, response: httpx.Response | None, error: Exception | None) -> None:
        return


class CaptchaStrategy(Strategy):
    """Placeholder integrating with captcha solver services."""

    def __init__(self, solver_name: Optional[str] = None) -> None:
        self.solver_name = solver_name or "manual"

    def before_request(self, context: AntiBotContext, directive: RequestDirective) -> None:
        if context.source.anti_scraping_strategies.captcha_solver:
            directive.captcha_handler = self.solver_name

    def after_success(self, context: AntiBotContext, response: httpx.Response) -> None:
        return

    def after_failure(self, context: AntiBotContext, response: httpx.Response | None, error: Exception | None) -> None:
        return


def build_chain(
    source: SourceConfig,
    global_config: GlobalConfig,
    proxy_pool: ProxyPool | None,
    ua_pool: UserAgentPool | None,
) -> tuple[AntiBotContext, "AntiBotChain"]:
    """Utility to build a ready-to-use chain from config."""

    from .chain import AntiBotChain

    context = AntiBotContext(source=source, global_config=global_config)
    strategies: list[Strategy] = [
        RetryStrategy(),
        ProxyStrategy(proxy_pool),
        UserAgentStrategy(ua_pool),
        DelayStrategy(),
        HeadlessBrowserStrategy(),
        CaptchaStrategy(),
    ]
    chain = AntiBotChain(strategies)
    return context, chain


__all__ = [
    "ProxyStrategy",
    "UserAgentStrategy",
    "DelayStrategy",
    "RetryStrategy",
    "HeadlessBrowserStrategy",
    "CaptchaStrategy",
    "build_chain",
]
