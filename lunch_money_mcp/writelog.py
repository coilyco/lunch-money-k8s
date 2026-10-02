"""Write log: one JSON line per ledger write, kept at the tool boundary.

Every caller reaches the ledger through this server, so the log holds for any
harness and needs no client hook. A write that names transactions is read before
and after, and refused when the before-read fails, so a logged write always has
its prior state beside it. Lines go to stderr because the stdio transport owns
stdout. They carry ledger fields, so they stay in the cluster log store.
"""

from __future__ import annotations

import functools
import inspect
import json
import logging
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

LOGGER = logging.getLogger("lunch_money_mcp.writes")
ERROR_CHARS = 200

Snapshot = Callable[[dict[str, Any]], Any]


class WriteRefused(RuntimeError):
    """The prior state could not be read, so the write was not made."""


def configure() -> None:
    """Send the write log to stderr as bare JSON lines, once."""
    if LOGGER.handlers:
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(message)s"))
    LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.INFO)
    LOGGER.propagate = False


def _emit(event: dict[str, Any]) -> None:
    LOGGER.info(json.dumps(event, default=str, sort_keys=True))


def _read(snapshot: Snapshot | None, arguments: dict[str, Any]) -> tuple[Any, str | None]:
    if snapshot is None:
        return None, None
    try:
        return snapshot(arguments), None
    except Exception as exc:
        return None, f"{type(exc).__name__}: {str(exc)[:ERROR_CHARS]}"


def logged_write(snapshot: Snapshot | None = None) -> Callable[..., Any]:
    """Log a mutating tool with its arguments, result, and snapshot before and after."""

    def wrap(tool: Callable[..., Any]) -> Callable[..., Any]:
        signature = inspect.signature(tool)

        @functools.wraps(tool)
        def run(*args: Any, **kwargs: Any) -> Any:
            bound = signature.bind(*args, **kwargs)
            bound.apply_defaults()
            arguments = dict(bound.arguments)
            event: dict[str, Any] = {
                "event": "ledger_write",
                "ts": datetime.now(UTC).isoformat(timespec="seconds"),
                "tool": tool.__name__,
                "input": arguments,
            }
            before, failure = _read(snapshot, arguments)
            if failure:
                _emit({**event, "outcome": "refused", "before_error": failure})
                raise WriteRefused(f"{tool.__name__} not made, the row could not be read first")
            event["before"] = before
            try:
                result = tool(*args, **kwargs)
            except Exception as exc:
                _emit(
                    {
                        **event,
                        "outcome": "error",
                        "error": f"{type(exc).__name__}: {str(exc)[:ERROR_CHARS]}",
                    }
                )
                raise
            after, failure = _read(snapshot, arguments)
            event.update(outcome="ok", result=result, after=after)
            if failure:
                event["after_error"] = failure
            _emit(event)
            return result

        return run

    return wrap
