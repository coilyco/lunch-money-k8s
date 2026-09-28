"""FastMCP server exposing the Lunch Money API."""

import os
from collections import defaultdict
from datetime import date, timedelta

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.server import TransportSecuritySettings

from lunch_money_mcp.client import LunchMoney
from lunch_money_mcp.errors import init_error_tracking, report_crash

DEFAULT_ALLOWED_HOSTS = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
DEFAULT_ALLOWED_ORIGINS = ["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"]


def _parse_csv_env(name: str) -> list[str]:
    raw = os.environ.get(name, "")
    return [value.strip() for value in raw.split(",") if value.strip()]


def _transport_security() -> TransportSecuritySettings:
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=DEFAULT_ALLOWED_HOSTS + _parse_csv_env("LUNCH_MONEY_MCP_ALLOWED_HOSTS"),
        allowed_origins=DEFAULT_ALLOWED_ORIGINS + _parse_csv_env("LUNCH_MONEY_MCP_ALLOWED_ORIGINS"),
    )


def _build_mcp() -> FastMCP:
    return FastMCP(
        "lunch-money",
        host=os.environ.get("LUNCH_MONEY_MCP_HOST", "0.0.0.0"),
        port=int(os.environ.get("LUNCH_MONEY_MCP_PORT", "8080")),
        transport_security=_transport_security(),
    )


mcp = _build_mcp()

# Lazily constructed so the server imports without a token present.
_client: LunchMoney | None = None


def _api() -> LunchMoney:
    global _client
    if _client is None:
        _client = LunchMoney()
    return _client


def _default_range(start_date: str | None, end_date: str | None) -> tuple[str, str]:
    """Default to the trailing 30 days when a range is omitted."""
    end = date.fromisoformat(end_date) if end_date else date.today()
    start = date.fromisoformat(start_date) if start_date else end - timedelta(days=30)
    return start.isoformat(), end.isoformat()


# --- user ---


@mcp.tool()
def get_user_profile() -> dict:
    """Current Lunch Money user: name, email, account id, primary currency."""
    return _api().me()


@mcp.tool()
def api_version() -> dict:
    """Which Lunch Money API version this server talks to (v1 default, v2 opt-in)."""
    return {"version": _api().version}


# --- transactions ---


@mcp.tool()
def list_transactions(
    start_date: str | None = None,
    end_date: str | None = None,
    uncategorized_only: bool = False,
    category_id: int | None = None,
    tag_id: int | None = None,
    asset_id: int | None = None,
    status: str | None = None,
    limit: int | None = None,
    offset: int | None = None,
) -> list[dict]:
    """List transactions in a date range (YYYY-MM-DD). Defaults to the last 30 days.

    uncategorized_only surfaces just transactions still needing a category. The
    category_id, tag_id, asset_id, and status filters narrow server-side; limit
    and offset paginate.
    """
    start, end = _default_range(start_date, end_date)
    txns = _api().transactions(
        start,
        end,
        category_id=category_id,
        tag_id=tag_id,
        asset_id=asset_id,
        status=status,
        limit=limit,
        offset=offset,
    )
    if uncategorized_only:
        txns = [t for t in txns if not t.get("category_id")]
    return [
        {
            "id": t["id"],
            "date": t["date"],
            "payee": t.get("payee"),
            "amount": t.get("amount"),
            "currency": t.get("currency"),
            "category_id": t.get("category_id"),
            "category_name": t.get("category_name"),
            "status": t.get("status"),
            "notes": t.get("notes"),
        }
        for t in txns
    ]


@mcp.tool()
def get_transaction(transaction_id: int) -> dict:
    """Full detail for one transaction."""
    return _api().transaction(transaction_id)


@mcp.tool()
def insert_transaction(
    transaction_date: str,
    payee: str,
    amount: float,
    category_id: int | None = None,
    apply_rules: bool = False,
    skip_duplicates: bool = True,
    check_for_recurring: bool = False,
) -> dict:
    """Insert one transaction. transaction_date is YYYY-MM-DD, amount positive for spend.

    apply_rules runs the account's rules over it, skip_duplicates drops a likely
    duplicate, check_for_recurring flags it against recurring detection.
    """
    txn = {"date": transaction_date, "payee": payee, "amount": amount}
    if category_id is not None:
        txn["category_id"] = category_id
    return _api().insert_transactions(
        [txn],
        apply_rules=apply_rules,
        skip_duplicates=skip_duplicates,
        check_for_recurring=check_for_recurring,
    )


@mcp.tool()
def split_transaction(transaction_id: int, splits: list[dict]) -> dict:
    """Split a transaction into children. Each split is {amount, category_id?, notes?}."""
    return _api().split_transaction(transaction_id, splits)


@mcp.tool()
def unsplit_transactions(parent_ids: list[int]) -> dict:
    """Undo a split, restoring the original parent transactions."""
    return _api().unsplit_transactions(parent_ids)


@mcp.tool()
def update_transaction(
    transaction_id: int,
    payee: str | None = None,
    notes: str | None = None,
    category_id: int | None = None,
    status: str | None = None,
) -> dict:
    """Update fields on a transaction. Only the arguments you pass are changed."""
    fields = {
        k: v
        for k, v in {
            "payee": payee,
            "notes": notes,
            "category_id": category_id,
            "status": status,
        }.items()
        if v is not None
    }
    _api().update_transaction(transaction_id, fields)
    return {"transaction_id": transaction_id, "updated": sorted(fields)}


@mcp.tool()
def categorize_transaction(transaction_id: int, category_id: int) -> dict:
    """Assign a category to a transaction. Use list_categories to find a category id."""
    _api().set_category(transaction_id, category_id)
    return {"transaction_id": transaction_id, "category_id": category_id, "updated": True}


@mcp.tool()
def get_transaction_group(transaction_id: int) -> dict:
    """The parent and child transactions of a transaction group."""
    return _api().transaction_group(transaction_id)


@mcp.tool()
def create_transaction_group(transaction_date: str, payee: str, transaction_ids: list[int]) -> dict:
    """Group existing transactions under a new parent transaction."""
    return _api().create_transaction_group(
        {"date": transaction_date, "payee": payee, "transactions": transaction_ids}
    )


@mcp.tool()
def delete_transaction_group(transaction_id: int) -> dict:
    """Ungroup a transaction group. The child transactions are kept."""
    return _api().delete_transaction_group(transaction_id)


# --- categories ---


@mcp.tool()
def list_categories() -> list[dict]:
    """List all spending categories with their ids."""
    return [
        {"id": c["id"], "name": c["name"], "is_income": c.get("is_income", False)}
        for c in _api().categories()
    ]


@mcp.tool()
def get_category(category_id: int) -> dict:
    """Full detail for one category."""
    return _api().category(category_id)


@mcp.tool()
def create_category(name: str, is_income: bool = False, exclude_from_totals: bool = False) -> dict:
    """Create a category. Set exclude_from_totals for transfer-like categories."""
    result = _api().create_category(name, is_income, exclude_from_totals)
    return {"name": name, "category_id": result.get("category_id") or result.get("id")}


@mcp.tool()
def create_category_group(name: str, category_ids: list[int]) -> dict:
    """Create a category group containing the given category ids."""
    return _api().create_category_group(name, category_ids)


@mcp.tool()
def add_to_category_group(group_id: int, category_ids: list[int]) -> dict:
    """Add existing categories to an existing category group."""
    return _api().add_to_category_group(group_id, category_ids)


@mcp.tool()
def update_category(
    category_id: int, name: str | None = None, exclude_from_totals: bool | None = None
) -> dict:
    """Update a category. Only the arguments you pass are changed."""
    fields = {
        k: v
        for k, v in {"name": name, "exclude_from_totals": exclude_from_totals}.items()
        if v is not None
    }
    _api().update_category(category_id, fields)
    return {"category_id": category_id, "updated": sorted(fields)}


@mcp.tool()
def delete_category(category_id: int, force: bool = False) -> dict:
    """Delete a category. force also disassociates its transactions and budgets."""
    _api().delete_category(category_id, force)
    return {"category_id": category_id, "deleted": True, "forced": force}


# --- tags ---


@mcp.tool()
def list_tags() -> list[dict]:
    """List all tags on the account."""
    return _api().tags()


# --- recurring ---


@mcp.tool()
def list_recurring_items(start_date: str | None = None, end_date: str | None = None) -> list:
    """Recurring items with their occurrences over a date range. Defaults to 30 days."""
    start, end = _default_range(start_date, end_date)
    return _api().recurring_items(start, end)


# --- budgets ---


@mcp.tool()
def list_budgets(start_date: str | None = None, end_date: str | None = None) -> list:
    """Budget detail per category over a date range. Defaults to the last 30 days."""
    start, end = _default_range(start_date, end_date)
    return _api().budgets(start, end)


@mcp.tool()
def upsert_budget(category_id: int, amount: float, month: str, currency: str = "usd") -> dict:
    """Set the budget for a category in a month. month is the first day, YYYY-MM-01."""
    _api().upsert_budget(month, category_id, amount, currency)
    return {"category_id": category_id, "month": month, "amount": amount}


@mcp.tool()
def remove_budget(category_id: int, month: str) -> dict:
    """Remove the budget for a category in a month. month is the first day, YYYY-MM-01."""
    _api().remove_budget(month, category_id)
    return {"category_id": category_id, "month": month, "removed": True}


# --- assets, plaid, crypto ---


@mcp.tool()
def list_assets() -> list[dict]:
    """List manually-managed assets (accounts not linked through Plaid)."""
    return _api().assets()


@mcp.tool()
def create_asset(name: str, type_name: str, balance: float, currency: str = "usd") -> dict:
    """Create a manual asset. type_name is e.g. cash, credit, investment, real estate."""
    return _api().create_asset(
        {"name": name, "type_name": type_name, "balance": balance, "currency": currency}
    )


@mcp.tool()
def update_asset(asset_id: int, balance: float | None = None, name: str | None = None) -> dict:
    """Update a manual asset's balance or name."""
    fields = {k: v for k, v in {"balance": balance, "name": name}.items() if v is not None}
    _api().update_asset(asset_id, fields)
    return {"asset_id": asset_id, "updated": sorted(fields)}


@mcp.tool()
def list_plaid_accounts() -> list[dict]:
    """List bank accounts linked through Plaid."""
    return _api().plaid_accounts()


@mcp.tool()
def trigger_plaid_fetch() -> dict:
    """Trigger a transaction fetch from Plaid for all linked accounts (experimental)."""
    return _api().trigger_plaid_fetch()


@mcp.tool()
def list_crypto() -> list[dict]:
    """List crypto holdings, both synced and manual."""
    return _api().crypto()


@mcp.tool()
def update_crypto(crypto_id: int, balance: float | None = None, name: str | None = None) -> dict:
    """Update a manually-tracked crypto holding's balance or name."""
    fields = {k: v for k, v in {"balance": balance, "name": name}.items() if v is not None}
    _api().update_crypto(crypto_id, fields)
    return {"crypto_id": crypto_id, "updated": sorted(fields)}


# --- derived ---


@mcp.tool()
def spending_summary(start_date: str | None = None, end_date: str | None = None) -> dict:
    """Total spend per category over a date range. Defaults to the last 30 days."""
    start, end = _default_range(start_date, end_date)
    by_category: dict[str, float] = defaultdict(float)
    for t in _api().transactions(start, end):
        name = t.get("category_name") or "Uncategorized"
        by_category[name] += float(t.get("amount") or 0)
    ranked = sorted(by_category.items(), key=lambda kv: kv[1], reverse=True)
    return {
        "start_date": start,
        "end_date": end,
        "total": round(sum(by_category.values()), 2),
        "by_category": [{"category": n, "amount": round(v, 2)} for n, v in ranked],
    }


def main() -> None:
    """Run over stdio, or streamable HTTP when LUNCH_MONEY_MCP_TRANSPORT=http."""
    init_error_tracking()
    transport = os.environ.get("LUNCH_MONEY_MCP_TRANSPORT", "stdio")
    try:
        if transport in ("http", "streamable-http"):
            mcp.run(transport="streamable-http")
        else:
            mcp.run()
    except Exception as exc:
        report_crash(exc)
        raise


if __name__ == "__main__":
    main()
