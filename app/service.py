"""Import and reporting logic. All P&L math lives in the pnl package; this only stores and groups."""
from __future__ import annotations

import json
import tempfile
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

from pnl.export import avg, daily_csv, fills_csv, trades_csv
from pnl.matching import Orphan, Trade, daily_summary, process_fills
from pnl.parser import Fill, parse_confirmation

from . import config
from .models import FillRow, Import, TradeNote, session

ZERO = Decimal(0)
FEE_TYPES = ["commission", "cat_fee", "regulatory_clearing_fee", "finra_fee", "sec_fee"]


# ---------------------------------------------------------------- import
def import_pdf(data: bytes, filename: str) -> dict:
    """Parse one confirmation, keep only its fills, discard the file. Returns a per-file report."""
    with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp:     # deleted on close
        tmp.write(data)
        tmp.flush()
        conf = parse_confirmation(tmp.name)
    report = {"file": filename, "status": "error", "fills": 0, "new_fills": 0,
              "warnings": list(conf.warnings), "errors": list(conf.errors)}
    if conf.errors:
        return report
    with session() as db:
        if db.scalar(select(Import).where(Import.file_hash == conf.file_hash)):
            report.update(status="duplicate", fills=len(conf.fills))
            return report
        imp = Import(processing_date=conf.processing_date, page_count=conf.page_count,
                     file_hash=conf.file_hash, account_last4=conf.account_last4)
        db.add(imp)
        db.flush()
        existing = {(d, n) for d, n in db.execute(
            select(FillRow.trade_date, FillRow.trade_number)
            .where(FillRow.trade_date.in_({f.trade_date for f in conf.fills})))}
        new = 0
        for f in conf.fills:
            if (f.trade_date, f.trade_number) in existing:
                continue                      # same fill already stored from an earlier copy
            db.add(FillRow(
                import_id=imp.id, trade_date=f.trade_date, trade_number=f.trade_number,
                exec_time=f.exec_time, side=f.side, open_close=f.open_close,
                is_settlement=f.is_settlement, underlying=f.underlying, expiry=f.expiry,
                right=f.right, strike=f.strike, quantity=f.quantity, price=f.price,
                principal=f.principal, fees_json=json.dumps({k: str(v) for k, v in f.fees.items()}),
                net_amount=f.net_amount))
            new += 1
        imp.fill_count = new
        db.commit()
    _bust()
    report.update(status="imported" if new else "duplicate", fills=len(conf.fills), new_fills=new)
    return report


# ---------------------------------------------------------------- loading
_cache: dict = {}


def _bust():
    _cache.clear()


def _load():
    """(trades, orphans, fills, notes) recomputed from stored fills, cached until the next import."""
    if "all" in _cache:
        return _cache["all"]
    with session() as db:
        rows = db.scalars(select(FillRow).order_by(FillRow.trade_date, FillRow.exec_time)).all()
        coverage = {d for d in db.scalars(select(Import.processing_date))}
        notes = {n.trade_key: n for n in db.scalars(select(TradeNote))}
    fills = [Fill(trade_number=r.trade_number, trade_date=r.trade_date, exec_time=r.exec_time,
                  side=r.side, open_close=r.open_close, is_settlement=r.is_settlement,
                  underlying=r.underlying, expiry=r.expiry, right=r.right, strike=r.strike,
                  quantity=r.quantity, price=r.price, principal=r.principal, fees=r.fees,
                  net_amount=r.net_amount) for r in rows]
    trades, orphans = process_fills(fills, coverage)
    _cache["all"] = (trades, orphans, fills, notes)
    return _cache["all"]


def trade_key(t: Trade) -> str:
    f = t.spread_fills[0].legs[0]
    return f"{f.trade_date.isoformat()}:{f.trade_number}"


def _notes_for(notes: dict) -> dict:
    return {k: {"market_condition": n.market_condition, "learnings": n.learnings,
                "tags": [x for x in n.tags.split(";") if x]} for k, n in notes.items()}


def _underlyings(arg: str | None):
    if arg is None or arg == "":
        return set(config.DEFAULT_UNDERLYINGS)
    if arg.upper() == "ALL":
        return None
    return {u.strip().upper() for u in arg.split(",") if u.strip()}


def select_trades(frm: date | None = None, to: date | None = None, underlyings: str | None = None,
                  statuses=("closed", "settled", "expired")) -> list[Trade]:
    trades, _, _, _ = _load()
    us = _underlyings(underlyings)
    out = []
    for t in trades:
        if t.status not in statuses:
            continue
        if us is not None and t.underlying not in us:
            continue
        d = t.close_date if t.status != "needs_attention" else t.open_date
        if frm and d < frm or to and d > to:
            continue
        out.append(t)
    return sorted(out, key=lambda t: (t.close_date, t.spread_fills[0].exec_time))


# ---------------------------------------------------------------- serialization
def _s(x):
    return None if x is None else format(x, "f") if isinstance(x, Decimal) else str(x)


def _m(x):
    """Dollars as a plain decimal string with exactly 2 places."""
    return None if x is None else format(x.quantize(Decimal("0.01")), "f")


def _r(x):
    """Ratios as a decimal string with 4 places (-0.0300 means -3.0%)."""
    return None if x is None else format(x.quantize(Decimal("0.0001")), "f")


def trade_dict(t: Trade, notes: dict) -> dict:
    fee_lines = {k: ZERO for k in FEE_TYPES}
    legs = []
    for sf in t.spread_fills:
        for leg in sf.legs:
            for k, v in leg.fees.items():
                fee_lines[k] = fee_lines.get(k, ZERO) + v
            legs.append({"trade_number": leg.trade_number, "date": leg.trade_date.isoformat(),
                         "time": leg.exec_time.strftime("%H:%M:%S"), "side": leg.side.lower(),
                         "action": sf.action, "right": leg.right, "strike": _s(leg.strike.normalize()),
                         "quantity": leg.quantity, "price": _s(leg.price), "net_amount": _m(leg.net_amount)})
    key = trade_key(t)
    n = notes.get(key, {"market_condition": "", "learnings": "", "tags": []})
    return {
        "id": t.id, "key": key, "underlying": t.underlying, "expiry": t.expiry.isoformat(),
        "strategy": t.strategy, "right": t.right, "short_strike": _s(t.short_strike.normalize()),
        "long_strike": _s(t.long_strike.normalize()), "contracts": t.peak,
        "open_date": t.open_date.isoformat(), "date": t.close_date.isoformat(), "status": t.status,
        "flags": t.flags, "entry_avg": avg(t.entry_avg), "exit_avg": avg(t.exit_avg),
        "premium_collected": _m(max(t.premium, ZERO)), "premium_paid": _m(max(-t.premium, ZERO)),
        "gross": _m(t.gross), "fees": _m(t.fees), "net": _m(t.net), "max_risk": _m(t.max_risk),
        "return_on_risk": _r(t.return_on_risk), "result": t.result,
        "fee_breakdown": {k: _m(v) for k, v in fee_lines.items()},
        "fee_source": "actual", "legs": legs, "note": n,
    }


def _agg(ts: list[Trade]) -> dict:
    wins = sum(t.result == "win" for t in ts)
    losses = sum(t.result == "loss" for t in ts)
    risk = sum((t.max_risk for t in ts), ZERO)
    net = sum((t.net for t in ts), ZERO)
    return {"trades": len(ts), "wins": wins, "losses": losses,
            "win_rate": _r(Decimal(wins) / Decimal(wins + losses)) if wins + losses else None,
            "premium_collected": _m(sum((t.premium for t in ts if t.premium > 0), ZERO)),
            "premium_paid": _m(sum((-t.premium for t in ts if t.premium < 0), ZERO)),
            "gross": _m(sum((t.gross for t in ts), ZERO)), "fees": _m(sum((t.fees for t in ts), ZERO)),
            "net": _m(net), "max_risk": _m(risk),
            "return_on_risk": _r(net / risk) if risk else None}


def day_view(d: date, underlyings: str | None) -> dict:
    _, _, _, notes = _load()
    nd = _notes_for(notes)
    ts = select_trades(d, d, underlyings)
    running, series = ZERO, []
    for t in ts:
        running += t.net
        series.append({"id": t.id, "net": _m(t.net), "cumulative": _m(running)})
    return {"date": d.isoformat(), "summary": _agg(ts), "trades": [trade_dict(t, nd) for t in ts],
            "series": series}


def _bucket(d: date, g: str) -> date:
    if g == "week":
        return d - timedelta(days=d.weekday())
    if g == "month":
        return d.replace(day=1)
    if g == "year":
        return d.replace(month=1, day=1)
    return d


def period_view(g: str, frm, to, underlyings) -> dict:
    ts = select_trades(frm, to, underlyings)
    buckets: dict[date, list[Trade]] = defaultdict(list)
    for t in ts:
        buckets[_bucket(t.close_date, g)].append(t)
    rows, cum = [], ZERO
    for b in sorted(buckets):
        a = _agg(buckets[b])
        cum += Decimal(a["net"])
        rows.append({"start": b.isoformat(), **a, "cumulative_net": _m(cum)})
    return {"granularity": g, "total": _agg(ts), "rows": rows}


def attention(underlyings: str | None) -> dict:
    trades, orphans, _, _ = _load()
    us = _underlyings(underlyings)
    ts = [t for t in trades if (t.status in ("open", "needs_attention") or "scaled" in t.flags
                                or "legged_out" in t.flags) and (us is None or t.underlying in us)]
    _, _, _, notes = _load()
    nd = _notes_for(notes)
    orph = [{"date": o.fills[0].trade_date.isoformat(), "reason": o.reason,
             "fills": [f"{f.side} {f.quantity} {f.underlying} {f.expiry:%y%m%d}{f.right}{f.strike.normalize():f} #{f.trade_number}"
                       for f in o.fills]}
            for o in orphans if us is None or o.fills[0].underlying in us]
    return {"trades": [trade_dict(t, nd) for t in ts], "orphans": orph}


# ---------------------------------------------------------------- notes
def save_note(key: str, market_condition: str, learnings: str, tags: list[str]) -> dict:
    with session() as db:
        n = db.get(TradeNote, key) or TradeNote(trade_key=key)
        n.market_condition = market_condition[:40]
        n.learnings = learnings[:5000]
        n.tags = ";".join(t.strip()[:30] for t in tags if t.strip())[:500]
        db.merge(n)
        db.commit()
    _bust()
    return {"ok": True}


# ---------------------------------------------------------------- exports
def export_trades(frm, to, underlyings) -> str:
    _, _, _, notes = _load()
    ts = select_trades(frm, to, underlyings)
    nd = _notes_for(notes)
    return trades_csv(ts, {t.id: nd[trade_key(t)] for t in ts if trade_key(t) in nd})


def export_daily(frm, to, underlyings) -> str:
    return daily_csv(select_trades(frm, to, underlyings))


def export_fills(frm, to, underlyings) -> str:
    trades, _, fills, _ = _load()
    us = _underlyings(underlyings)
    keep = [f for f in fills if (us is None or f.underlying in us)
            and (not frm or f.trade_date >= frm) and (not to or f.trade_date <= to)]
    return fills_csv(keep, [t for t in trades if t.status in ("closed", "settled", "expired")])


def imports_list() -> list[dict]:
    with session() as db:
        return [{"date": i.processing_date.isoformat(), "fills": i.fill_count, "pages": i.page_count,
                 "imported_at": i.imported_at.isoformat(timespec="seconds")}
                for i in db.scalars(select(Import).order_by(Import.processing_date.desc()))]
