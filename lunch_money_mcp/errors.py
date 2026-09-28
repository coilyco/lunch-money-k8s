"""Crash reporting to Sentry, crashes only (teable:coilyco/deploy#8347).

Every integration stays on so a crash is fully annotated, and the keys that
hold financial data are scrubbed wherever they appear. Off unless SENTRY_DSN is set.
"""

from __future__ import annotations

import logging
import os
import time
from typing import TYPE_CHECKING, Any

import sentry_sdk
from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.integrations.starlette import StarletteIntegration
from sentry_sdk.scrubber import DEFAULT_DENYLIST, EventScrubber

if TYPE_CHECKING:
    from sentry_sdk.types import Event

SENTRY_EVENTS_PER_MINUTE = 20
# Frame locals and request bodies stay on, because they make a crash readable.
# These keys hold financial or account data and are scrubbed wherever they appear.
USER_DATA_KEYS = [
    "transactions",
    "transaction",
    "payee",
    "amount",
    "to_base",
    "price",
    "balance",
    "notes",
    "note",
    "account",
    "accounts",
    "plaid_accounts",
    "institution_name",
    "display_name",
    "name",
    "original_name",
    "description",
    "merchant",
    "category",
    "categories",
    "budget",
    "budgets",
    "splits",
    "payload",
    "fields",
    "body",
    # FastMCP's frames hold tool arguments as a model repr no key reaches inside.
    "arguments",
    "arguments_parsed_model",
    "arguments_parsed_dict",
    "arguments_to_validate",
    "arguments_to_pass_directly",
]
_SCRUBBED = {key.lower() for key in USER_DATA_KEYS}
_MCP_ARGUMENT = "mcp.request.argument."
_log = logging.getLogger(__name__)
_initialized = False
_active = False
_window: list[float] = []


def _within_budget(now: float) -> bool:
    """Cap events per process so one crash loop cannot spend the monthly quota."""
    cutoff = now - 60.0
    while _window and _window[0] < cutoff:
        _window.pop(0)
    if len(_window) >= SENTRY_EVENTS_PER_MINUTE:
        return False
    _window.append(now)
    return True


def _scrub_mcp_arguments(event: Event) -> None:
    """The MCP integration puts tool arguments on the trace context, which the
    EventScrubber never visits, so the user-data ones are filtered here."""
    data = event.get("contexts", {}).get("trace", {}).get("data")
    if not isinstance(data, dict):
        return
    for key in list(data):
        if key.startswith(_MCP_ARGUMENT) and key[len(_MCP_ARGUMENT) :].lower() in _SCRUBBED:
            data[key] = "[Filtered]"


def _before_send(event: Event, _hint: dict[str, Any]) -> Event | None:
    if not _within_budget(time.monotonic()):
        return None
    _scrub_mcp_arguments(event)
    return event


def init_error_tracking() -> bool:
    """Turn crash reporting on once, when SENTRY_DSN is set."""
    global _active, _initialized
    if _initialized:
        return _active
    _initialized = True
    dsn = os.environ.get("SENTRY_DSN", "").strip()
    if not dsn:
        return False
    try:
        sentry_sdk.init(
            dsn=dsn,
            traces_sample_rate=0.0,
            environment=os.environ.get("SENTRY_ENVIRONMENT", "homelab"),
            before_send=_before_send,
            send_default_pii=False,
            event_scrubber=EventScrubber(
                denylist=DEFAULT_DENYLIST + USER_DATA_KEYS, recursive=True
            ),
            integrations=[
                # Breadcrumbs only: an ERROR log is a handled error.
                LoggingIntegration(event_level=None),
                # Only uncaught exceptions, never a 5xx the app returned on purpose.
                StarletteIntegration(failed_request_status_codes=set()),
            ],
        )
    except Exception as exc:
        # The class only: a BadDsn message can carry the DSN itself.
        _log.warning("Sentry initialization failed (%s); continuing", type(exc).__name__)
        return False
    _active = True
    return True


def report_crash(exc: BaseException) -> None:
    """Send the exception that is about to end the process, and wait for it."""
    if init_error_tracking():
        sentry_sdk.capture_exception(exc)
        sentry_sdk.flush(timeout=2.0)
