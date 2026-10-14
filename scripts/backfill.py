"""Backfill report: python3 -I scripts/backfill.py <folder-of-pdfs>

Parses every PDF, skips byte-identical duplicates (file hash) and re-listed fills (trade number),
runs matching, and prints everything that needs a human look.
"""
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pnl.parser import parse_confirmation  # noqa: E402
from pnl.matching import daily_summary, process  # noqa: E402


def main(folder: str) -> None:
    paths = sorted(Path(folder).glob("*.pdf"))
    seen_hash: dict[str, str] = {}
    good, failed, dup_files = [], [], []
    for p in paths:
        c = parse_confirmation(p)
        if c.file_hash in seen_hash:
            dup_files.append((p.name, seen_hash[c.file_hash]))
            continue
        seen_hash[c.file_hash] = p.name
        (good if c.ok else failed).append(c)

    print(f"PDFs: {len(paths)}  unique: {len(good) + len(failed)}  byte-duplicates: {len(dup_files)}  "
          f"parse failures: {len(failed)}")
    for name, orig in dup_files:
        print(f"  duplicate file {name!r} == {orig!r}")
    for c in failed:
        print(f"  FAILED {c.source_name}: {c.errors}")

    # Same day imported from two different files (not byte-identical)?
    by_day = defaultdict(list)
    for c in good:
        by_day[c.processing_date].append(c)
    for d, cs in sorted(by_day.items()):
        if len(cs) > 1:
            nums = [frozenset(f.trade_number for f in c.fills) for c in cs]
            same = all(n == nums[0] for n in nums)
            print(f"  {d}: {len(cs)} files ({', '.join(c.source_name for c in cs)}) "
                  f"{'identical fills' if same else 'DIFFERENT FILLS'}")
    warns = [(c.source_name, w) for c in good for w in c.warnings]
    print(f"parser warnings: {len(warns)}")
    for w in warns[:20]:
        print("  ", w)

    all_fills = [f for c in good for f in c.fills]
    n_unique = len({(f.trade_date, f.trade_number) for f in all_fills})
    print(f"fills read: {len(all_fills)}  unique by (date, trade number): {n_unique}")

    trades, orphans = process(good)
    status = Counter(t.status for t in trades)
    print(f"trades: {len(trades)}  status: {dict(status)}  orphan groups: {len(orphans)}")
    flags = Counter(fl for t in trades for fl in t.flags)
    print(f"trade flags: {dict(flags)}")
    print(f"trade types: {dict(Counter(t.strategy for t in trades))}")
    print(f"processing dates: {min(by_day)} to {max(by_day)}  ({len(by_day)} days)")

    print("\n-- needs attention / orphans --")
    for o in orphans:
        f0 = o.fills[0]
        print(f"  {f0.trade_date} {o.reason}: " +
              ", ".join(f"{f.side} {f.quantity} {f.underlying} {f.expiry:%y%m%d}{f.right}{f.strike} #{f.trade_number}"
                        for f in o.fills))
    for t in trades:
        if t.status in ("open", "needs_attention") or t.flags:
            print(f"  trade {t.id} {t.strategy} {t.short_strike}/{t.long_strike} qty {t.qty_opened} "
                  f"status {t.status} flags {t.flags}")

    # Independent cash check per day: printed NET AMOUNTs vs trade P&L, for days without orphans.
    orphan_days = {f.trade_date for o in orphans for f in o.fills}
    fills_by_day = defaultdict(list)
    for f in {(f.trade_date, f.trade_number): f for f in all_fills}.values():
        fills_by_day[f.trade_date].append(f)
    mismatches = []
    checked = 0
    trade_net_by_day = defaultdict(lambda: 0)
    overnight_days = set()
    for t in trades:
        if t.status in ("closed", "settled", "expired"):
            trade_net_by_day[t.close_date] += t.net
            if t.open_date != t.close_date:
                overnight_days.add(t.close_date)   # cash for these lands on two different days
    for d, fs in sorted(fills_by_day.items()):
        if d in orphan_days or d in overnight_days:
            continue
        # Only fully-flat same-day 0DTE SPX/SPXW days: anything else carries cash across days.
        if not all(f.underlying in ("SPX", "SPXW") and f.expiry == d for f in fs):
            continue
        checked += 1
        cash = sum((f.net_amount if f.side == "Sold" else -f.net_amount for f in fs), 0)
        if cash != trade_net_by_day.get(d, 0):
            mismatches.append((d, cash, trade_net_by_day.get(d, 0)))
    print(f"\ncash cross-check: {checked} same-day 0DTE days checked, mismatches: {len(mismatches)}")
    for m in mismatches:
        print("  ", m)

    rows = daily_summary(trades)
    print(f"\ndays with realized trades: {len(rows)}")
    print(f"total: trades {sum(r['trades'] for r in rows)}  W/L {sum(r['wins'] for r in rows)}/"
          f"{sum(r['losses'] for r in rows)}  gross {sum(r['gross_pnl'] for r in rows)}  "
          f"fees {sum(r['fees'] for r in rows)}  net {sum(r['net_pnl'] for r in rows)}")


if __name__ == "__main__":
    main(sys.argv[1])
