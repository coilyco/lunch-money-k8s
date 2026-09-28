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
