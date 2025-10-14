from __future__ import annotations

import httpx
import pytest

from intelli_crawler.engine.antibot.chain import AntiBotContext, RequestDirective
from intelli_crawler.engine.fetcher import BrowserResponse, FetchRequest, Fetcher


def test_fetcher_applies_strategy_headers(monkeypatch: pytest.MonkeyPatch, sample_global_config, sample_source_config, snapshot) -> None:
    source = sample_source_config()
    fetcher = Fetcher(sample_global_config, proxy_pool=None, ua_pool=None)

    context = AntiBotContext(source=source, global_config=sample_global_config)

    class DummyChain:
        def prepare(self, _context):
            directive = RequestDirective()
            directive.headers["X-Strategy"] = "enabled"
            directive.timeout = 12
            return directive

        def notify_success(self, *_args, **_kwargs):
            return

        def notify_failure(self, *_args, **_kwargs):
            return

        def should_retry(self, _context):
            return False

    dummy_chain = DummyChain()
    monkeypatch.setattr(fetcher, "_build_chain", lambda _: (context, dummy_chain))
    captured: dict = {}

    def fake_request(**kwargs):
        captured.update(kwargs)
        request = httpx.Request(kwargs["method"], kwargs["url"])
        return httpx.Response(200, request=request, text="payload", headers={"Server": "mock"})

    monkeypatch.setattr(fetcher._client, "request", fake_request)

    response = fetcher.fetch(source, FetchRequest(url="https://example.com/api"))
    fetcher.close()

    snapshot.assert_match(
        {
            "request_headers": captured["headers"],
            "timeout": captured["timeout"],
            "response": {
                "url": response.url,
                "status": response.status_code,
                "text": response.text,
            },
        },
        key="strategy_headers",
    )


def test_fetcher_handles_browser_requests(monkeypatch: pytest.MonkeyPatch, sample_global_config, sample_source_config, snapshot) -> None:
    source = sample_source_config()
    fetcher = Fetcher(sample_global_config, proxy_pool=None, ua_pool=None)
    context = AntiBotContext(source=source, global_config=sample_global_config)

    class BrowserChain:
        def prepare(self, _context):
            directive = RequestDirective()
            directive.use_browser = True
            return directive

        def notify_success(self, *_args, **_kwargs):
            return

        def notify_failure(self, *_args, **_kwargs):
            return

        def should_retry(self, _context):
            return False

    monkeypatch.setattr(fetcher, "_build_chain", lambda _: (context, BrowserChain()))

    def fake_browser(request, headers, timeout):  # noqa: ARG001
        return BrowserResponse(
            url=request.url,
            status_code=200,
            text="<html>ok</html>",
            headers={"Content-Type": "text/html"},
        )

    monkeypatch.setattr(fetcher, "_fetch_via_browser", fake_browser)
    result = fetcher.fetch(source, FetchRequest(url="https://example.com/detail"))
    fetcher.close()

    snapshot.assert_match(
        {
            "url": result.url,
            "status": result.status_code,
            "raw_attached": result.raw is not None,
            "text": result.text,
        },
        key="browser_fetch",
    )


def test_fetcher_retry_on_failure(monkeypatch: pytest.MonkeyPatch, sample_global_config, sample_source_config, snapshot) -> None:
    source = sample_source_config()
    fetcher = Fetcher(sample_global_config, proxy_pool=None, ua_pool=None)
    context = AntiBotContext(source=source, global_config=sample_global_config)

    class RetryChain:
        def prepare(self, _context):
            return RequestDirective()

        def notify_success(self, *_args, **_kwargs):
            return

        def notify_failure(self, context, _response, _error):
            context.attempt += 1
            context.max_attempts = 2

        def should_retry(self, context):
            return context.attempt <= context.max_attempts

    monkeypatch.setattr(fetcher, "_build_chain", lambda _: (context, RetryChain()))

    call_count = {"count": 0}

    def flaky_request(**kwargs):
        call_count["count"] += 1
        if call_count["count"] == 1:
            raise httpx.TimeoutException("boom")
        request = httpx.Request(kwargs["method"], kwargs["url"])
        return httpx.Response(200, request=request, text="recovered")

    monkeypatch.setattr(fetcher._client, "request", flaky_request)
    result = fetcher.fetch(source, FetchRequest(url="https://example.com/flaky"))
    fetcher.close()
    snapshot.assert_match(
        {"attempts": call_count["count"], "status": result.status_code, "text": result.text},
        key="retry_success",
    )


def test_fetcher_waf_cookie_flow(monkeypatch: pytest.MonkeyPatch, sample_global_config, sample_source_config) -> None:
    source = sample_source_config()
    fetcher = Fetcher(sample_global_config, proxy_pool=None, ua_pool=None)

    request = FetchRequest(url="https://example.com/protected")
    script_payload = (
        "<script>var\\ssarg1='1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef';</script><div>acw_sc__v2</div>"
    )
    initial = httpx.Response(
        200,
        request=httpx.Request("GET", request.url),
        text=script_payload,
    )

    def follow_up(**kwargs):
        return httpx.Response(200, request=httpx.Request("GET", kwargs["url"]), text="passed")

    monkeypatch.setattr(fetcher._client, "request", follow_up)
    retry = fetcher._maybe_solve_aliyun_waf(initial, request, {"User-Agent": "UA"})
    cookie = fetcher._client.cookies.get("acw_sc__v2", domain="example.com")
    fetcher.close()
    assert retry is not None
    assert retry.text == "passed"
    assert cookie is not None


def test_fetcher_failure_classification() -> None:
    class Dummy:
        def __init__(self, status_code):
            self.status_code = status_code

    assert Fetcher._is_failure(Dummy(500))
    assert Fetcher._is_failure(Dummy(401))
    assert not Fetcher._is_failure(Dummy(200))
