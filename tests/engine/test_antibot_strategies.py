from __future__ import annotations

import random

from intelli_crawler.config import AntiScrapingStrategies
from intelli_crawler.engine.antibot import strategies
from intelli_crawler.engine.antibot.chain import AntiBotContext, RequestDirective
from intelli_crawler.infra import ProxyPool, UserAgentPool


def build_context(sample_source_config, sample_global_config, **overrides) -> AntiBotContext:
    source = sample_source_config(
        anti_scraping_strategies=AntiScrapingStrategies(**overrides)
    )
    return AntiBotContext(source=source, global_config=sample_global_config)


def test_proxy_strategy_rotates(sample_source_config, sample_global_config) -> None:
    pool = ProxyPool(proxies=["http://a", "http://b"])
    context = build_context(sample_source_config, sample_global_config, proxy_pool=True)
    directive = RequestDirective()
    strategies.ProxyStrategy(pool).before_request(context, directive)
    assert directive.proxy in {"http://a", "http://b"}


def test_user_agent_strategy_uses_pool(sample_source_config, sample_global_config) -> None:
    pool = UserAgentPool(user_agents=["UA1"])
    context = build_context(
        sample_source_config,
        sample_global_config,
        user_agent_rotation=True,
    )
    directive = RequestDirective()
    strategies.UserAgentStrategy(pool).before_request(context, directive)
    assert directive.headers["User-Agent"] == "UA1"


def test_delay_strategy_defaults_to_global(sample_source_config, sample_global_config, monkeypatch) -> None:
    context = build_context(sample_source_config, sample_global_config, delay_range=(0.0, 0.0))
    monkeypatch.setattr(random, "uniform", lambda _a, _b: 1.25)
    directive = RequestDirective()
    strategies.DelayStrategy().before_request(context, directive)
    assert directive.delay == 1.25


def test_retry_strategy_controls_attempts(sample_source_config, sample_global_config) -> None:
    context = build_context(sample_source_config, sample_global_config, retry_on_fail=2)
    directive = RequestDirective()
    retry = strategies.RetryStrategy()
    retry.before_request(context, directive)
    assert context.max_attempts == 3
    retry.after_failure(context, None, None)
    assert context.attempt == 2
    retry.after_success(context, None)
    assert context.attempt == 1


def test_headless_browser_strategy_flag(sample_source_config, sample_global_config) -> None:
    context = build_context(sample_source_config, sample_global_config, use_headless_browser=True)
    directive = RequestDirective()
    strategies.HeadlessBrowserStrategy().before_request(context, directive)
    assert directive.use_browser is True


def test_captcha_strategy_assigns_handler(sample_source_config, sample_global_config) -> None:
    context = build_context(sample_source_config, sample_global_config, captcha_solver=True)
    directive = RequestDirective()
    strategies.CaptchaStrategy("solver").before_request(context, directive)
    assert directive.captcha_handler == "solver"
