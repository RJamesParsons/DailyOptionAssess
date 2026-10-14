"""Group fills into vertical-spread trades and compute metrics.

Rules (see the spec):
  3. Pair two fills with the same time, expiry, right, quantity and action into one spread fill.
  4. A trade is every spread fill on one expiry/right/strike pair, from the first entry until the
     position is flat again. Reopening the same strikes after going flat starts a new trade.
  5. Entries and exits are averaged by quantity.
  6. A leg still open at expiry is closed by its assignment/exercise fill if there is one, otherwise
     it expired worthless and is closed at $0 (only when the expiry day's confirmation is present
     and passed its page check).
  7. Anything that cannot be matched is parked in `orphans`, never silently dropped.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, time
from decimal import Decimal

from .parser import Fill

D = Decimal
ZERO = D("0")
CENT = D("0.01")


@dataclass
class SpreadFill:
    trade_date: date
    exec_time: time
    underlying: str
    expiry: date
    right: str
    short_strike: Decimal  # the leg sold on entry (bought back on exit)
    long_strike: Decimal
    qty: int
    action: str  # "open" | "close" | "settle"
    legs: list  # the two Fill objects
    net_cash: Decimal  # sold principal - bought principal (before fees)
    fees: Decimal

    @property
    def direction(self) -> str:
        if self.right == "P":
            return "credit" if self.short_strike > self.long_strike else "debit"
        return "credit" if self.short_strike < self.long_strike else "debit"

    @property
    def key(self) -> tuple:
        return (self.underlying, self.expiry, self.right, self.direction,
                self.short_strike, self.long_strike)


@dataclass
class Orphan:
    fills: list
    reason: str


@dataclass
class Trade:
    id: str
    underlying: str
    expiry: date
    right: str
    direction: str
    short_strike: Decimal
    long_strike: Decimal
    spread_fills: list = field(default_factory=list)
    position: int = 0
    peak: int = 0
    closed_qty: int = 0
    status: str = "open"  # open | closed | settled | expired | needs_attention
    flags: list = field(default_factory=list)
    expired_qty: int = 0
    implied_settlement: Decimal | None = None

    # computed metrics
    qty_opened: int = 0
    entry_avg: Decimal = ZERO
    exit_avg: Decimal = ZERO
    premium: Decimal = ZERO  # signed: positive = collected, negative = paid
    gross: Decimal = ZERO
    fees: Decimal = ZERO
    net: Decimal = ZERO
    width: Decimal = ZERO
    max_risk: Decimal = ZERO
    return_on_risk: Decimal | None = None
    result: str = ""

    @property
    def strategy(self) -> str:
        return f"{'call' if self.right == 'C' else 'put'} {self.direction} spread"

    @property
    def open_date(self) -> date:
        return self.spread_fills[0].trade_date

    @property
    def close_date(self) -> date:
        # A trade whose last contracts expired worthless finishes on its expiry date.
        return self.expiry if self.status == "expired" else self.spread_fills[-1].trade_date

    @property
    def fills(self) -> list:
        return [f for sf in self.spread_fills for f in sf.legs]


def _action(f: Fill) -> str:
    if f.is_settlement:
        return "settle"
    return "open" if f.open_close == "OPEN" else "close"


def pair_opens(fills: list[Fill]) -> tuple[list[SpreadFill], list[Orphan], list[Fill]]:
    """Pair opening fills by time (two legs, same time/expiry/right/quantity).

    Returns (open spread fills, orphans, exit fills). Exits (close / settle) are not paired here:
    they are matched against open positions in build_trades, because several spreads can close at
    the same instant and a spread can settle with only one leg in the money.
    """
    groups: dict[tuple, list[Fill]] = defaultdict(list)
    exits: list[Fill] = []
    for f in fills:
        if _action(f) != "open":
            exits.append(f)
            continue
        groups[(f.trade_date, f.exec_time, f.underlying, f.expiry, f.right, f.quantity)].append(f)

    spread_fills, orphans = [], []
    for key, grp in groups.items():
        if len(grp) == 2 and {g.side for g in grp} == {"Bought", "Sold"} \
                and grp[0].strike != grp[1].strike:
            sold = next(g for g in grp if g.side == "Sold")
            bought = next(g for g in grp if g.side == "Bought")
            spread_fills.append(SpreadFill(
                trade_date=key[0], exec_time=key[1], underlying=key[2], expiry=key[3],
                right=key[4], short_strike=sold.strike, long_strike=bought.strike,
                qty=key[5], action="open", legs=[sold, bought],
                net_cash=sold.principal - bought.principal,
                fees=sold.total_fees + bought.total_fees,
            ))
        else:
            orphans.append(Orphan(grp, f"cannot pair {len(grp)} opening fill(s) at "
                                       f"{key[1]} {key[4]} qty {key[5]}"))
    spread_fills.sort(key=lambda s: (s.trade_date, s.exec_time))
    return spread_fills, orphans, exits


def _exit_spread_fill(t: "Trade", action: str, legs: list, qty: int, f0: Fill) -> SpreadFill:
    return SpreadFill(
        trade_date=f0.trade_date, exec_time=f0.exec_time, underlying=t.underlying,
        expiry=t.expiry, right=t.right, short_strike=t.short_strike, long_strike=t.long_strike,
        qty=qty, action=action, legs=legs,
        net_cash=sum((l.signed_cash for l in legs), ZERO),
        fees=sum((l.total_fees for l in legs), ZERO),
    )


def _find_open(current: dict, und, expiry, right, short=None, long_=None, qty=1):
    """An open trade matching the given strikes, preferring one with enough position left."""
    hits = [t for k, t in current.items()
            if t.position > 0 and (t.underlying, t.expiry, t.right) == (und, expiry, right)
            and (short is None or t.short_strike == short) and (long_ is None or t.long_strike == long_)]
    hits.sort(key=lambda t: (t.position < qty, t.spread_fills[0].trade_date, t.spread_fills[0].exec_time))
    return hits[0] if hits else None


def _apply_exit(t: "Trade", sf: SpreadFill) -> None:
    if sf.qty > t.position:
        t.flags.append("exit_exceeds_position")
        t.status = "needs_attention"
    t.position -= sf.qty
    t.closed_qty += sf.qty
    t.spread_fills.append(sf)


def _resolve_exit_group(group: list[Fill], action: str, current: dict) -> list[Fill]:
    """Match one time-group of close/settle fills to open trades. Returns the unmatched fills."""
    left = list(group)
    # Pass 1: two legs, buy the short strike and sell the long strike, same quantity.
    for b in [f for f in group if f.side == "Bought"]:
        if b not in left:
            continue
        for s in [f for f in left if f.side == "Sold" and f.quantity == b.quantity]:
            t = _find_open(current, b.underlying, b.expiry, b.right, b.strike, s.strike, b.quantity)
            if t:
                _apply_exit(t, _exit_spread_fill(t, action, [s, b], b.quantity, b))
                left.remove(b)
                left.remove(s)
                break
    # Pass 2 (settlement only): one leg in the money. The assigned short leg is bought back at
    # intrinsic value and the long leg expires worthless (no fill); an exercised long leg alone
    # happens when the short leg expired worthless (debit spreads).
    if action == "settle":
        for f in list(left):
            if f.side == "Bought":
                t = _find_open(current, f.underlying, f.expiry, f.right, short=f.strike, qty=f.quantity)
            else:
                t = _find_open(current, f.underlying, f.expiry, f.right, long_=f.strike, qty=f.quantity)
            if t:
                _apply_exit(t, _exit_spread_fill(t, action, [f], f.quantity, f))
                left.remove(f)
    return left


def build_trades(open_fills: list[SpreadFill], exit_fills: list[Fill], coverage_dates: set[date],
                 last_date: date) -> tuple[list[Trade], list[Orphan]]:
    """coverage_dates: days whose confirmation was imported and passed its page check."""
    exit_groups: dict[tuple, list[Fill]] = defaultdict(list)
    for f in exit_fills:
        exit_groups[(f.trade_date, f.exec_time, f.underlying, f.expiry, f.right, _action(f))].append(f)

    # Opens sort before exits at the same instant; exit groups are resolved against positions.
    events = [(sf.trade_date, sf.exec_time, 0, sf) for sf in open_fills]
    events += [(k[0], k[1], 1, (k, g)) for k, g in exit_groups.items()]
    events.sort(key=lambda e: (e[0], e[1], e[2]))

    current: dict[tuple, Trade] = {}
    trades: list[Trade] = []
    orphans: list[Orphan] = []
    seq: dict[date, int] = defaultdict(int)

    for _, _, kind, payload in events:
        if kind == 1:
            key, grp = payload
            left = _resolve_exit_group(grp, key[-1], current)
            if left:
                orphans.append(Orphan(left, f"{key[-1]} fill with no open position "
                                            f"(opening fills not in the imported files)"))
            continue
        sf = payload
        t = current.get(sf.key)
        if t is None or t.position == 0:
            seq[sf.trade_date] += 1
            t = Trade(id=f"{sf.trade_date.isoformat()}-{seq[sf.trade_date]}",
                      underlying=sf.underlying, expiry=sf.expiry, right=sf.right,
                      direction=sf.direction, short_strike=sf.short_strike,
                      long_strike=sf.long_strike)
            current[sf.key] = t
            trades.append(t)
        if t.closed_qty and t.position > 0 and "scaled" not in t.flags:
            t.flags.append("scaled")  # entry after a partial exit: peak only approximates risk
        t.position += sf.qty
        t.qty_opened += sf.qty
        t.peak = max(t.peak, t.position)
        t.spread_fills.append(sf)

    for t in trades:
        _finalize(t, coverage_dates, last_date)
    return trades, orphans


def _finalize(t: Trade, coverage_dates: set[date], last_date: date) -> None:
    if t.position > 0:
        if t.expiry in coverage_dates:
            t.expired_qty = t.position
            t.position = 0
            t.flags.append("expired_inferred")
            t.status = "expired"
        elif t.expiry > last_date:
            t.status = "open"
        else:
            t.status = "needs_attention"
            t.flags.append("past_expiry_without_confirmation")
    elif t.status != "needs_attention":
        t.status = "settled" if any(s.action == "settle" for s in t.spread_fills) else "closed"

    if t.status in ("open", "needs_attention"):
        return
    _metrics(t)


def _metrics(t: Trade) -> None:
    opens = [s for s in t.spread_fills if s.action == "open"]
    exits = [s for s in t.spread_fills if s.action != "open"]
    open_qty = sum(s.qty for s in opens)
    open_cash = sum((s.net_cash for s in opens), ZERO)
    exit_cash = sum((s.net_cash for s in exits), ZERO)  # negative for credit spreads

    t.width = abs(t.short_strike - t.long_strike)
    t.premium = open_cash
    t.gross = open_cash + exit_cash
    t.fees = sum((s.fees for s in t.spread_fills), ZERO)
    t.net = t.gross - t.fees

    per_spread = D(open_qty * 100)
    t.entry_avg = abs(open_cash) / per_spread
    t.exit_avg = abs(exit_cash) / per_spread  # expired-worthless contracts contribute $0
    if t.direction == "credit":
        t.max_risk = (t.width - t.entry_avg) * t.peak * 100
    else:
        t.max_risk = t.entry_avg * t.peak * 100
    t.return_on_risk = (t.net / t.max_risk) if t.max_risk else None
    t.result = "win" if t.net > 0 else "loss" if t.net < 0 else "scratch"

    # Settlement consistency: every ITM settlement fill implies one index settlement value.
    implied = set()
    for s in t.spread_fills:
        if s.action == "settle":
            for leg in s.legs:
                implied.add(leg.strike - leg.price if leg.right == "P" else leg.strike + leg.price)
    if implied:
        t.implied_settlement = sum(implied) / len(implied)
        if max(implied) - min(implied) > D("0.011"):
            t.flags.append("settlement_inconsistent")


def daily_summary(trades: list[Trade]) -> list[dict]:
    """One row per day, by the date a trade finished. Excludes open and needs-attention trades."""
    days: dict[date, list[Trade]] = defaultdict(list)
    for t in trades:
        if t.status in ("closed", "settled", "expired"):
            days[t.close_date].append(t)
    rows = []
    for d in sorted(days):
        ts = days[d]
        risk = sum((t.max_risk for t in ts), ZERO)
        net = sum((t.net for t in ts), ZERO)
        rows.append({
            "trade_date": d, "trades": len(ts),
            "wins": sum(t.result == "win" for t in ts),
            "losses": sum(t.result == "loss" for t in ts),
            "premium_collected": sum((t.premium for t in ts if t.premium > 0), ZERO),
            "premium_paid": sum((-t.premium for t in ts if t.premium < 0), ZERO),
            "gross_pnl": sum((t.gross for t in ts), ZERO),
            "fees": sum((t.fees for t in ts), ZERO),
            "net_pnl": net,
            "return_on_risk": (net / risk) if risk else None,
        })
    return rows


def process(confirmations: list) -> tuple[list[Trade], list[Orphan]]:
    """Run pair + build over one or more parsed confirmations. Blocks on any parse error."""
    bad = [c for c in confirmations if not c.ok]
    if bad:
        raise ValueError("; ".join(f"{c.source_name}: {c.errors}" for c in bad))
    # Fills are keyed by (trade date, trade number): the broker reuses trade numbers on different
    # days, so the number alone is not unique. Re-importing a file cannot double count.
    by_key: dict[tuple, Fill] = {}
    for c in confirmations:
        for f in c.fills:
            by_key.setdefault((f.trade_date, f.trade_number), f)
    fills = list(by_key.values())
    coverage = {c.processing_date for c in confirmations}
    open_fills, pre_orphans, exit_fills = pair_opens(fills)
    trades, orphans = build_trades(open_fills, exit_fills, coverage, max(coverage))
    orphans = pre_orphans + orphans
    # Safety: an unmatched fill on a strike of a trade we would call "expired worthless" means the
    # P&L is unknown, so that trade must not count until a human looks at it.
    for o in orphans:
        for f in o.fills:
            for t in trades:
                if t.status == "expired" and (t.underlying, t.expiry, t.right) == (f.underlying, f.expiry, f.right) \
                        and f.strike in (t.short_strike, t.long_strike):
                    t.status = "needs_attention"
                    t.flags.append("orphan_leg_at_expiry")
    return trades, orphans
