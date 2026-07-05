"""Robustness layer: retry/backoff schedule, Retry-After, circuit breaker, cache, logging."""

import pytest
import respx
from httpx import Response

from layoverlab.connectors import http as http_mod
from layoverlab.connectors.base import ConnectorError

URL = "https://api.example.com/data"


@pytest.fixture()
def sleep_recorder(monkeypatch):
    delays: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        delays.append(seconds)

    monkeypatch.setattr(http_mod.asyncio, "sleep", fake_sleep)
    return delays


@respx.mock
async def test_retries_on_5xx_then_succeeds(polite_client, sleep_recorder):
    route = respx.get(URL).mock(
        side_effect=[Response(503), Response(503), Response(200, json={"ok": True})]
    )
    body = await polite_client.get_json(URL)
    assert body == {"ok": True}
    assert route.call_count == 3


@respx.mock
async def test_backoff_schedule_is_exponential(polite_client, sleep_recorder):
    respx.get(URL).mock(return_value=Response(500))
    with pytest.raises(ConnectorError):
        await polite_client.get_json(URL)
    backoffs = [d for d in sleep_recorder if d >= 1.0]  # skip politeness-interval jitter sleeps
    assert len(backoffs) == 2  # 3 tries -> 2 waits
    assert 2.0 <= backoffs[0] <= 3.0
    assert 4.0 <= backoffs[1] <= 5.0


@respx.mock
async def test_honors_retry_after_header(polite_client, sleep_recorder):
    respx.get(URL).mock(
        side_effect=[
            Response(429, headers={"Retry-After": "7"}),
            Response(200, json={"ok": True}),
        ]
    )
    body = await polite_client.get_json(URL)
    assert body == {"ok": True}
    assert 7.0 in sleep_recorder


@respx.mock
async def test_no_retry_on_4xx(polite_client, sleep_recorder):
    route = respx.get(URL).mock(return_value=Response(404))
    with pytest.raises(ConnectorError):
        await polite_client.get_json(URL)
    assert route.call_count == 1


@respx.mock
async def test_breaker_opens_after_consecutive_failures(polite_client, sleep_recorder):
    respx.get(URL).mock(return_value=Response(500))
    with pytest.raises(ConnectorError):
        await polite_client.get_json(URL)  # 3 failures
    with pytest.raises(ConnectorError):
        await polite_client.get_json(URL)  # 2 more -> breaker opens at 5
    assert http_mod._breaker.is_open("api.example.com")
    with pytest.raises(ConnectorError, match="circuit breaker open"):
        await polite_client.get_json(URL)


@respx.mock
async def test_breaker_half_open_probe_recovers(polite_client, sleep_recorder, monkeypatch):
    respx.get(URL).mock(return_value=Response(500))
    for _ in range(2):
        with pytest.raises(ConnectorError):
            await polite_client.get_json(URL)
    assert http_mod._breaker.is_open("api.example.com")

    # cooldown elapsed -> half-open probe allowed; a success closes the breaker
    http_mod._breaker.opened_at["api.example.com"] -= polite_client.settings.crawl_breaker_cooldown_s + 1
    respx.get(URL).mock(return_value=Response(200, json={"ok": 1}))
    body = await polite_client.get_json(URL)
    assert body == {"ok": 1}
    assert not http_mod._breaker.is_open("api.example.com")


@respx.mock
async def test_cache_still_works_and_skips_breaker(polite_client, sleep_recorder):
    route = respx.get(URL).mock(return_value=Response(200, json={"v": 1}))
    assert await polite_client.get_json(URL) == {"v": 1}
    assert await polite_client.get_json(URL) == {"v": 1}
    assert route.call_count == 1

    # even with the breaker open, cached responses are served
    http_mod._breaker.opened_at["api.example.com"] = 10**12
    assert await polite_client.get_json(URL) == {"v": 1}


@respx.mock
async def test_structured_log_line_per_request(polite_client, sleep_recorder, caplog):
    respx.get(URL).mock(return_value=Response(200, json={"v": 1}))
    with caplog.at_level("INFO", logger="layoverlab.connectors.http"):
        await polite_client.get_json(URL)
        await polite_client.get_json(URL)  # cache hit
    lines = [r.message for r in caplog.records if "http_request" in r.message]
    assert any("domain=api.example.com" in ln and "status=200" in ln and "cache_hit=false" in ln
               for ln in lines)
    assert any("cache_hit=true" in ln for ln in lines)


@respx.mock
async def test_post_json_with_cache(polite_client, sleep_recorder):
    url = "https://api.example.com/search"
    route = respx.post(url).mock(return_value=Response(200, json={"result": 42}))
    body1 = await polite_client.post_json(url, json_body={"q": 1})
    body2 = await polite_client.post_json(url, json_body={"q": 1})
    assert body1 == body2 == {"result": 42}
    assert route.call_count == 1
    await polite_client.post_json(url, json_body={"q": 1}, cache=False)
    assert route.call_count == 2
