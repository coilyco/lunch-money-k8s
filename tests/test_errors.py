"""Sentry receives crashes only (teable:coilyco/deploy#8347)."""

from __future__ import annotations

import logging

import pytest
import sentry_sdk
from sentry_sdk.transport import Transport
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

import lunch_money_mcp.errors as errors
import lunch_money_mcp.server as server

DSN = "https://public@example.invalid/1"


class _Capture(Transport):
    def __init__(self) -> None:
        super().__init__()
        self.events: list[dict] = []

    def capture_envelope(self, envelope) -> None:  # type: ignore[no-untyped-def]
        event = envelope.get_event()
        if event is not None:
            self.events.append(event)


def _reset(monkeypatch) -> None:
    monkeypatch.setattr(errors, "_initialized", False)
    monkeypatch.setattr(errors, "_active", False)
    monkeypatch.setattr(errors, "_window", [])


@pytest.fixture
def captured(monkeypatch):
    transport = _Capture()
    real_init = sentry_sdk.init
    monkeypatch.setattr(
        errors.sentry_sdk, "init", lambda **kwargs: real_init(transport=transport, **kwargs)
    )
    _reset(monkeypatch)
    monkeypatch.setenv("SENTRY_DSN", DSN)
    yield transport
    real_init()


def _values(transport: _Capture) -> list[str]:
    return [e["exception"]["values"][-1]["value"] for e in transport.events]


def _app() -> Starlette:
    async def crash(_request):
        raise RuntimeError("route crashed")

    async def handled(_request):
        logging.getLogger("lunch_money_mcp.test").error("upstream 502, answered with an error")
        return PlainTextResponse("ok")

    async def refused(_request):
        raise HTTPException(status_code=503, detail="deliberate")

    return Starlette(
        routes=[Route("/crash", crash), Route("/handled", handled), Route("/refused", refused)]
    )


def test_no_dsn_leaves_sentry_off(monkeypatch):
    _reset(monkeypatch)
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    assert errors.init_error_tracking() is False


def test_an_uncaught_route_exception_reaches_sentry(captured):
    assert errors.init_error_tracking() is True
    client = TestClient(_app(), raise_server_exceptions=False)
    assert client.get("/crash").status_code == 500
    sentry_sdk.flush()
    assert _values(captured) == ["route crashed"]


def test_handled_errors_stay_out_of_sentry(captured):
    errors.init_error_tracking()
    client = TestClient(_app(), raise_server_exceptions=False)
    assert client.get("/handled").status_code == 200
    assert client.get("/refused").status_code == 503
    sentry_sdk.flush()
    assert captured.events == []


def test_main_reports_a_crash_and_still_raises(captured, monkeypatch):
    def die(*_args, **_kwargs):
        raise RuntimeError("server died")

    monkeypatch.setattr(server.mcp, "run", die)
    with pytest.raises(RuntimeError, match="server died"):
        server.main()
    assert _values(captured) == ["server died"]


def test_budget_caps_events_per_process_minute(monkeypatch):
    monkeypatch.setattr(errors, "_window", [])
    allowed = [errors._within_budget(100.0) for _ in range(errors.SENTRY_EVENTS_PER_MINUTE + 1)]
    assert allowed.count(True) == errors.SENTRY_EVENTS_PER_MINUTE
    assert allowed[-1] is False
    assert errors._within_budget(161.0) is True


def test_init_failure_logs_the_class_and_never_the_dsn(monkeypatch, caplog):
    def refuse(**_kwargs):
        raise ValueError("https://secret-key@o0.ingest.example/1")

    _reset(monkeypatch)
    monkeypatch.setattr(errors.sentry_sdk, "init", refuse)
    monkeypatch.setenv("SENTRY_DSN", "https://secret-key@o0.ingest.example/1")
    with caplog.at_level(logging.WARNING, logger="lunch_money_mcp.errors"):
        assert errors.init_error_tracking() is False
    assert "ValueError" in caplog.text
    assert "secret-key" not in caplog.text


# Built at runtime, so source context around a raise cannot hold it.
SECRET = "-".join(["ACCOUNT", "BALANCE", "4242"])


def _leaks(events: list[dict]) -> list[str]:
    """Every frame var or payload path still holding the secret, for a clear failure."""
    import json

    found = []
    for event in events:
        for exc in event.get("exception", {}).get("values", []):
            for frame in exc.get("stacktrace", {}).get("frames", []):
                for name, value in (frame.get("vars") or {}).items():
                    if SECRET in json.dumps(value):
                        found.append(f"{frame.get('function')}:{name}")
        for key in ("request", "breadcrumbs", "extra", "contexts"):
            if SECRET in json.dumps(event.get(key)):
                found.append(key)
    return found


def test_a_crash_keeps_harmless_locals_and_scrubs_financial_data(captured):
    from starlette.requests import Request

    async def crash(request: Request):
        record = await request.json()
        payee = record["payee"]  # noqa: F841
        transaction_id = record["transaction_id"]  # noqa: F841
        logging.getLogger("lunch_money_mcp.test").warning("looking up transaction")
        raise RuntimeError("route crashed")

    errors.init_error_tracking()
    app = Starlette(routes=[Route("/crash", crash, methods=["POST"])])
    client = TestClient(app, raise_server_exceptions=False)
    body = {"payee": SECRET, "transaction_id": 7711}
    assert client.post("/crash", json=body).status_code == 500
    sentry_sdk.flush()
    (event,) = captured.events
    assert _leaks(captured.events) == []
    frame_vars = event["exception"]["values"][-1]["stacktrace"]["frames"][-1]["vars"]
    # Locals are what make the trace useful, so a harmless one stays readable.
    assert "7711" in frame_vars["transaction_id"]
    crumbs = [crumb.get("message") for crumb in event["breadcrumbs"]["values"]]
    assert "looking up transaction" in crumbs
    assert event["request"]["method"] == "POST"
    assert event["request"]["url"].endswith("/crash")


def test_a_raising_mcp_tool_is_reported_with_its_arguments_scrubbed(captured):
    import anyio
    from mcp.server.fastmcp import FastMCP
    from mcp.shared.memory import create_connected_server_and_client_session

    errors.init_error_tracking()
    app = FastMCP("crash-test")

    @app.tool()
    def broken(payee: str) -> str:
        raise ValueError("upstream rejected the payee")

    async def call() -> bool:
        async with create_connected_server_and_client_session(app._mcp_server) as session:
            result = await session.call_tool("broken", {"payee": SECRET})
            return result.isError

    assert anyio.run(call) is True
    sentry_sdk.flush()
    assert len(captured.events) >= 1
    assert _leaks(captured.events) == []


def test_the_mcp_integration_is_on_and_pii_is_off(captured):
    errors.init_error_tracking()
    client = sentry_sdk.get_client()
    assert client.get_integration("mcp") is not None
    # The MCP integration records tool arguments and results only with PII on.
    assert client.options["send_default_pii"] is False
