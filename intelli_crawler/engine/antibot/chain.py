"""Strategy chain orchestrating anti-bot adaptations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Protocol

import httpx

from ...config import GlobalConfig, SourceConfig


@dataclass
class RequestDirective:
    """Mutable set of options to apply to an outgoing request."""

    headers: dict[str, str] = field(default_factory=dict)
    timeout: float | None = None
    proxy: str | None = None
    delay: float | None = None
    use_browser: bool = False
    captcha_handler: str | None = None


@dataclass
class AntiBotContext:
    """Shared state for all strategies in the chain."""

    source: SourceConfig
    global_config: GlobalConfig
    attempt: int = 1
    max_attempts: int = 1
    last_response: httpx.Response | None = None
    last_exception: Exception | None = None


class Strategy(Protocol):
    """Strategy behaviour expected by the chain."""

    def before_request(self, context: AntiBotContext, directive: RequestDirective) -> None:
        """Mutate directive ahead of an HTTP request."""

    def after_success(self, context: AntiBotContext, response: httpx.Response) -> None:
        """Allow strategy to observe successful response."""

    def after_failure(
        self,
        context: AntiBotContext,
        response: httpx.Response | None,
        error: Exception | None,
    ) -> None:
        """Allow strategy to react when a request fails."""


class AntiBotChain:
    """Compose multiple strategies and expose a simple API for the fetcher."""

    def __init__(self, strategies: Optional[List[Strategy]] = None) -> None:
        self.strategies = strategies or []

    def add_strategy(self, strategy: Strategy) -> None:
        self.strategies.append(strategy)

    # ------------------------------------------------------------------
    def prepare(self, context: AntiBotContext) -> RequestDirective:
        directive = RequestDirective()
        for strategy in self.strategies:
            strategy.before_request(context, directive)
        return directive

    def notify_success(self, context: AntiBotContext, response: httpx.Response) -> None:
        context.last_response = response
        context.last_exception = None
        for strategy in self.strategies:
            strategy.after_success(context, response)

    def notify_failure(
        self,
        context: AntiBotContext,
        response: httpx.Response | None,
        error: Exception | None,
    ) -> None:
        context.last_response = response
        context.last_exception = error
        for strategy in self.strategies:
            strategy.after_failure(context, response, error)

    def should_retry(self, context: AntiBotContext) -> bool:
        return context.attempt <= context.max_attempts


__all__ = ["AntiBotChain", "AntiBotContext", "RequestDirective", "Strategy"]
