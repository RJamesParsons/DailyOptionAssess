"""Effective-dated fee estimator, used only when no confirmation PDF has been uploaded for a day.

Rates were fitted to the six real 2026 confirmations (see tests/test_fees.py). Dates are the day a
rate was first *observed*; the true change-over date lies somewhere between that day and the
previous sample, so treat estimates for dates far from a sample as approximate. Uploading the real
PDF always replaces an estimate. Fee lines the broker may add (SEC fee currently prints $0.00) are
estimated as $0.00 and picked up automatically once a PDF is imported.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

D = Decimal
CENT = D("0.01")


def _r(x: Decimal) -> Decimal:
    return x.quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class FeeSchedule:
    name: str
    effective_from: date
    commission_per_contract: Decimal
    cat_per_fill: Decimal
    reg_clearing_per_contract: Decimal
    reg_clearing_min: Decimal
    finra_per_contract_sold: Decimal


SCHEDULES = [
    FeeSchedule("Early 2026 (Feb 19 sample)", date(2026, 1, 1), D("0.50"), D("0"), D("0.02"), D("0.02"), D("0")),
    FeeSchedule("Mid 2026 (Jun 17 sample)", date(2026, 6, 17), D("0.75"), D("0.01"), D("0.0125"), D("0.02"), D("0.0033")),
    FeeSchedule("Oct 1 2026 sample", date(2026, 10, 1), D("0.75"), D("0.01"), D("0.0375"), D("0"), D("0")),
    FeeSchedule("Oct 8 2026 onward", date(2026, 10, 8), D("0.75"), D("0.01"), D("0.0365"), D("0"), D("0")),
]


def schedule_for(d: date) -> FeeSchedule:
    applicable = [s for s in SCHEDULES if s.effective_from <= d]
    if not applicable:
        raise ValueError(f"No fee schedule on or before {d}")
    return max(applicable, key=lambda s: s.effective_from)


def estimate_fill_fees(trade_date: date, side: str, quantity: int, is_settlement: bool = False) -> dict:
    """Itemized fee estimate for one fill, using the same keys as the parser."""
    s = schedule_for(trade_date)
    q = D(quantity)
    fees = {}
    fees["commission"] = D("0.00") if is_settlement else _r(s.commission_per_contract * q)
    if s.cat_per_fill and not is_settlement:
        fees["cat_fee"] = s.cat_per_fill
    reg = _r(s.reg_clearing_per_contract * q)
    fees["regulatory_clearing_fee"] = max(reg, s.reg_clearing_min)
    if side == "Sold":
        finra = _r(s.finra_per_contract_sold * q)
        if finra > 0:
            fees["finra_fee"] = finra
        fees["sec_fee"] = D("0.00")
    return fees


def estimate_total(trade_date: date, side: str, quantity: int, is_settlement: bool = False) -> Decimal:
    return sum(estimate_fill_fees(trade_date, side, quantity, is_settlement).values(), D("0"))
