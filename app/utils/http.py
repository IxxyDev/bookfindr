import asyncio
import logging

import httpx

logger = logging.getLogger(__name__)

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def _retry_delay(response: httpx.Response, attempt: int, backoff: float) -> float:
    retry_after = response.headers.get("Retry-After")
    if retry_after:
        try:
            return max(float(retry_after), 0.0)
        except ValueError:
            pass
    return backoff * (2**attempt)


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
    assert last_response is not None
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
