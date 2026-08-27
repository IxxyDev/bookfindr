from collections.abc import Callable

import httpx

Handler = Callable[[httpx.Request], httpx.Response]


def install_mock_transport(monkeypatch, handler: Handler) -> list[httpx.Request]:
    """Route every httpx.AsyncClient the code under test builds to ``handler``.

    Returns the list that collects each request sent, in order.
    """
    sent: list[httpx.Request] = []
    real_client = httpx.AsyncClient

    def recording_handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return handler(request)

    def client_factory(*args, **kwargs) -> httpx.AsyncClient:
        kwargs["transport"] = httpx.MockTransport(recording_handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", client_factory)
    return sent


def cap_results(monkeypatch, connector_module, limit: int) -> None:
    """Make ``connector_module`` see max_results_per_source = ``limit``."""
    from app.core.config import Settings

    monkeypatch.setattr(
        connector_module, "get_settings", lambda: Settings(max_results_per_source=limit)
    )
