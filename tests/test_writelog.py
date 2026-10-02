"""The write log records each ledger write with its row before and after, or refuses it."""

import json
import logging

import pytest

from lunch_money_mcp.writelog import LOGGER, WriteRefused, logged_write


@pytest.fixture
def lines(caplog):
    caplog.set_level(logging.INFO, logger=LOGGER.name)
    LOGGER.propagate = True
    return lambda: [json.loads(r.message) for r in caplog.records if r.name == LOGGER.name]


def test_a_write_is_logged_with_input_result_before_and_after(lines):
    rows = {7: {"id": 7, "category_id": 1}}

    @logged_write(lambda args: dict(rows[args["transaction_id"]]))
    def categorize(transaction_id: int, category_id: int = 2) -> dict:
        rows[transaction_id]["category_id"] = category_id
        return {"updated": True}

    assert categorize(7) == {"updated": True}
    (event,) = lines()
    assert event["tool"] == "categorize"
    assert event["input"] == {"transaction_id": 7, "category_id": 2}
    assert event["before"]["category_id"] == 1
    assert event["after"]["category_id"] == 2
    assert event["outcome"] == "ok"


def test_an_unreadable_row_refuses_the_write_and_changes_nothing(lines):
    called = []

    def missing(args):
        raise LookupError("no such row")

    @logged_write(missing)
    def update(transaction_id: int) -> dict:
        called.append(transaction_id)
        return {}

    with pytest.raises(WriteRefused):
        update(9)
    assert called == []
    (event,) = lines()
    assert event["outcome"] == "refused"
    assert "LookupError" in event["before_error"]


def test_a_failing_write_is_logged_and_still_raises(lines):
    @logged_write()
    def insert_transaction(payee: str) -> dict:
        raise RuntimeError("api down")

    with pytest.raises(RuntimeError):
        insert_transaction("x")
    (event,) = lines()
    assert event["outcome"] == "error" and "api down" in event["error"]


def test_a_write_without_a_snapshot_logs_no_rows(lines):
    @logged_write()
    def create_category(name: str) -> dict:
        return {"id": 3}

    create_category("Rent")
    (event,) = lines()
    assert event["before"] is None and event["after"] is None


def test_an_unreadable_after_row_is_flagged_not_swallowed(lines):
    reads = iter([{"id": 1}])

    def once(args):
        return next(reads)

    @logged_write(once)
    def update_transaction(transaction_id: int) -> dict:
        return {"ok": True}

    update_transaction(1)
    (event,) = lines()
    assert event["outcome"] == "ok" and "after_error" in event
