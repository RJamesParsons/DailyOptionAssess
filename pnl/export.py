"""CSV exports: trades, fills (audit), daily summary.

Format: UTF-8, comma-delimited, one header row, ISO dates, dollars as plain decimals (no symbols),
ratios as decimals (-0.0300 = -3.0%). Premium is split: premium_collected (credit spreads) and premium_paid
(debit spreads); the one that does not apply is 0.00. Text cells starting with = + - @ get a leading apostrophe so spreadsheets
cannot run them as formulas.
"""
from __future__ import annotations

import csv
import io
from decimal import ROUND_HALF_UP, Decimal

from .matching import Trade, daily_summary
from .parser import Fill

D = Decimal

TRADE_COLUMNS = [
    "trade_date", "underlying", "expiry", "strategy", "short_strike", "long_strike", "contracts",
    "entry_avg", "exit_avg", "premium_collected", "premium_paid", "gross_pnl", "fees", "net_pnl", "max_risk",
    "return_on_risk", "result", "fee_source", "market_condition", "learnings", "tags",
]
FILL_COLUMNS = [
    "trade_number", "trade_date", "exec_time_et", "symbol", "side", "open_close", "quantity",
    "price", "principal", "commission", "cat_fee", "regulatory_clearing_fee", "finra_fee",
    "sec_fee", "net_amount", "fee_source", "trade_id",
]
DAILY_COLUMNS = [
    "trade_date", "trades", "wins", "losses", "premium_collected", "premium_paid", "gross_pnl",
    "fees",
    "net_pnl", "return_on_risk",
]


def money(x: Decimal) -> str:
    return str(x.quantize(D("0.01"), rounding=ROUND_HALF_UP))


def ratio(x) -> str:
    return "" if x is None else str(x.quantize(D("0.0001"), rounding=ROUND_HALF_UP))


def avg(x: Decimal) -> str:
    """Per-contract average: at least 2 decimals, up to 4, no trailing noise."""
    s = str(x.quantize(D("0.0001"), rounding=ROUND_HALF_UP))
    while s.endswith("0") and len(s.split(".")[1]) > 2:
        s = s[:-1]
    return s


def strike(x: Decimal) -> str:
    """7800 -> '7800', 7800.5 -> '7800.5' (never scientific notation)."""
    return format(x.normalize(), "f")


def safe_text(s: str | None) -> str:
    s = s or ""
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def _write(columns: list[str], rows: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=columns, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def trades_csv(trades: list[Trade], notes: dict | None = None, fee_source: dict | None = None) -> str:
    """notes: {trade_id: {"market_condition": str, "learnings": str, "tags": [str]}}"""
    notes, fee_source = notes or {}, fee_source or {}
    rows = []
    for t in sorted((t for t in trades if t.status in ("closed", "settled", "expired")),
                    key=lambda t: (t.close_date, t.spread_fills[0].exec_time)):
        n = notes.get(t.id, {})
        rows.append({
            "trade_date": t.close_date.isoformat(), "underlying": t.underlying,
            "expiry": t.expiry.isoformat(), "strategy": t.strategy,
            "short_strike": strike(t.short_strike), "long_strike": strike(t.long_strike),
            "contracts": t.peak, "entry_avg": avg(t.entry_avg), "exit_avg": avg(t.exit_avg),
            "premium_collected": money(max(t.premium, D(0))),
            "premium_paid": money(max(-t.premium, D(0))), "gross_pnl": money(t.gross),
            "fees": money(t.fees), "net_pnl": money(t.net), "max_risk": money(t.max_risk),
            "return_on_risk": ratio(t.return_on_risk), "result": t.result,
            "fee_source": fee_source.get(t.id, "actual"),
            "market_condition": safe_text(n.get("market_condition")),
            "learnings": safe_text(n.get("learnings")),
            "tags": safe_text(";".join(n.get("tags", []))),
        })
    return _write(TRADE_COLUMNS, rows)


def fills_csv(fills: list[Fill], trades: list[Trade] | None = None, fee_source: str = "actual") -> str:
    owner = {f.trade_number: t.id for t in (trades or []) for f in t.fills}

    def fee(f: Fill, k: str) -> str:
        return money(f.fees[k]) if k in f.fees else ""

    rows = []
    for f in sorted(fills, key=lambda f: (f.trade_date, f.exec_time, f.trade_number)):
        rows.append({
            "trade_number": f.trade_number, "trade_date": f.trade_date.isoformat(),
            "exec_time_et": f.exec_time.strftime("%H:%M:%S"),
            "symbol": f"{f.underlying} {f.expiry:%y%m%d}{f.right}{strike(f.strike)}",
            "side": f.side.lower(),
            "open_close": "settle" if f.is_settlement else f.open_close.lower(),
            "quantity": f.quantity, "price": str(f.price), "principal": money(f.principal),
            "commission": fee(f, "commission"), "cat_fee": fee(f, "cat_fee"),
            "regulatory_clearing_fee": fee(f, "regulatory_clearing_fee"),
            "finra_fee": fee(f, "finra_fee"), "sec_fee": fee(f, "sec_fee"),
            "net_amount": money(f.net_amount), "fee_source": fee_source,
            "trade_id": owner.get(f.trade_number, ""),
        })
    return _write(FILL_COLUMNS, rows)


def daily_csv(trades: list[Trade]) -> str:
    rows = []
    for r in daily_summary(trades):
        rows.append({
            "trade_date": r["trade_date"].isoformat(), "trades": r["trades"], "wins": r["wins"],
            "losses": r["losses"], "premium_collected": money(r["premium_collected"]),
            "premium_paid": money(r["premium_paid"]),
            "gross_pnl": money(r["gross_pnl"]), "fees": money(r["fees"]),
            "net_pnl": money(r["net_pnl"]), "return_on_risk": ratio(r["return_on_risk"]),
        })
    return _write(DAILY_COLUMNS, rows)
