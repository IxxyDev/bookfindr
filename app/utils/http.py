import asyncio
import logging
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import httpx

logger = logging.getLogger(__name__)

RETRYABLE_STATUS = {429, 500, 502, 503, 504}
# a server may ask for hours; waiting that long would hold the sync lock all day
MAX_RETRY_AFTER_SECONDS = 60.0


def _retry_delay(response: httpx.Response, attempt: int, backoff: float) -> float:
    retry_after = _retry_after_seconds(response.headers.get("Retry-After"))
    if retry_after is None:
        return backoff * (2**attempt)
    return min(max(retry_after, 0.0), MAX_RETRY_AFTER_SECONDS)


def _retry_after_seconds(value: str | None) -> float | None:
    """Retry-After as seconds: either delta-seconds or an HTTP-date."""
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        pass
    try:
        retry_at = parsedate_to_datetime(value)
    except TypeError, ValueError:
        return None
    return (retry_at - datetime.now(UTC)).total_seconds()


async def request_with_retries(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    retries: int = 3,
    backoff: float = 1.0,
    **kwargs,
) -> httpx.Response:
    """Perform a request, retrying transport errors and 429/5xx with backoff.

    Raises the last error (or calls raise_for_status) once retries are exhausted.
    """
    if retries < 0:
        raise ValueError(f"retries must be >= 0, got {retries}")
    last_response: httpx.Response | None = None
    for attempt in range(retries + 1):
        try:
            response = await client.request(method, url, **kwargs)
        except httpx.TransportError as exc:
            if attempt == retries:
                raise
            delay = backoff * (2**attempt)
            logger.warning("%s %s failed (%s), retry in %.1fs", method, url, exc, delay)
            await asyncio.sleep(delay)
            continue
        if response.status_code in RETRYABLE_STATUS:
            last_response = response
            if attempt == retries:
                break
            delay = _retry_delay(response, attempt, backoff)
            logger.warning("HTTP %s from %s, retry in %.1fs", response.status_code, url, delay)
            await asyncio.sleep(delay)
            continue
        response.raise_for_status()
        return response
    # the loop runs at least once and only falls through after a retryable response
    if last_response is None:
        raise RuntimeError(f"{method} {url}: no response after {retries + 1} attempts")
    last_response.raise_for_status()
    return last_response


async def get_with_retries(
    client: httpx.AsyncClient,
    url: str,
    *,
    retries: int = 3,
    backoff: float = 1.0,
    **kwargs,
) -> httpx.Response:
    return await request_with_retries(
        client, "GET", url, retries=retries, backoff=backoff, **kwargs
    )
