from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx
import pytest

from app.utils.http import MAX_RETRY_AFTER_SECONDS, _retry_delay, get_with_retries


async def test_retries_on_429_then_success():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, json={"ok": True})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        resp = await get_with_retries(client, "https://example.com/", retries=3, backoff=0)
    assert resp.status_code == 200
    assert calls["n"] == 3


async def test_retries_on_500_then_success():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503)
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        resp = await get_with_retries(client, "https://example.com/", retries=2, backoff=0)
    assert resp.status_code == 200
    assert calls["n"] == 2


async def test_gives_up_after_retries():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await get_with_retries(client, "https://example.com/", retries=2, backoff=0)


async def test_no_retry_on_client_error():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await get_with_retries(client, "https://example.com/", retries=3, backoff=0)
    assert calls["n"] == 1


async def test_retries_transport_error():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("boom", request=request)
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        resp = await get_with_retries(client, "https://example.com/", retries=2, backoff=0)
    assert resp.status_code == 200
    assert calls["n"] == 2


def _response_with_retry_after(value: str) -> httpx.Response:
    return httpx.Response(503, headers={"Retry-After": value})


def test_retry_after_seconds_are_capped():
    assert _retry_delay(_response_with_retry_after("86400"), 0, 1.0) == MAX_RETRY_AFTER_SECONDS
    assert _retry_delay(_response_with_retry_after("5"), 0, 1.0) == 5.0


def test_retry_after_http_date_is_parsed():
    soon = datetime.now(UTC) + timedelta(seconds=30)
    delay = _retry_delay(_response_with_retry_after(format_datetime(soon, usegmt=True)), 0, 1.0)
    assert 25 <= delay <= 30


def test_retry_after_http_date_in_the_past_means_now():
    past = "Wed, 21 Oct 2015 07:28:00 GMT"
    assert _retry_delay(_response_with_retry_after(past), 0, 1.0) == 0.0


def test_unparseable_retry_after_falls_back_to_backoff():
    assert _retry_delay(_response_with_retry_after("soon"), 2, 1.0) == 4.0


async def test_negative_retries_are_rejected():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200))
    ) as client:
        with pytest.raises(ValueError):
            await get_with_retries(client, "https://example.com/", retries=-1)
