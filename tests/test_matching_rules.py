"""Synthetic cases for matching rules the real fixtures do not exercise."""
import sys
import unittest
from datetime import date, time
from decimal import Decimal as D
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pnl.matching import process  # noqa: E402
from pnl.parser import Fill, ParsedConfirmation  # noqa: E402

DAY = date(2026, 10, 14)
_n = [0]


def fill(side, oc, right, strike, qty, price, t, settle=False, day=DAY, tn=None):
    _n[0] += 1
    principal = D(str(price)) * qty * 100
    fees = {} if settle else {"commission": D("0.75") * qty}
    f = sum(fees.values(), D(0))
    net = principal - f if side == "Sold" else principal + f
    return Fill(tn or f"T{_n[0]}", day, t, side, oc, settle, "SPXW", day, right, D(strike),
                qty, D(str(price)), principal, fees, net)


def conf(fills, day=DAY, name="x"):
    return ParsedConfirmation(name, name, day, "1234", 1, 1, fills)


class Rules(unittest.TestCase):
    def test_single_leg_settlement_short_put_assigned(self):
        # Put credit spread 7000/6990 x2 ends ITM only on the short leg.
        fs = [fill("Sold", "OPEN", "P", 7000, 2, 1.50, time(10, 0)),
              fill("Bought", "OPEN", "P", 6990, 2, 0.50, time(10, 0)),
              fill("Bought", "CLOSE", "P", 7000, 2, 3.00, time(16, 0), settle=True)]
        trades, orphans = process([conf(fs)])
        self.assertEqual(orphans, [])
        t = trades[0]
        self.assertEqual(t.status, "settled")
        self.assertEqual(t.premium, D("200"))
        self.assertEqual(t.gross, D("200") - D("600"))

    def test_two_spreads_closing_at_same_instant_are_matched_by_strike(self):
        fs = [fill("Sold", "OPEN", "C", 7100, 1, 1.00, time(10, 0)),
              fill("Bought", "OPEN", "C", 7110, 1, 0.20, time(10, 0)),
              fill("Sold", "OPEN", "P", 6900, 1, 1.00, time(10, 5)),
              fill("Bought", "OPEN", "P", 6890, 1, 0.20, time(10, 5)),
              fill("Bought", "CLOSE", "C", 7100, 1, 0.40, time(11, 0)),
              fill("Sold", "CLOSE", "C", 7110, 1, 0.05, time(11, 0)),
              fill("Bought", "CLOSE", "P", 6900, 1, 0.30, time(11, 0)),
              fill("Sold", "CLOSE", "P", 6890, 1, 0.05, time(11, 0))]
        trades, orphans = process([conf(fs)])
        self.assertEqual(orphans, [])
        self.assertEqual(sorted(t.status for t in trades), ["closed", "closed"])
        self.assertEqual(sorted(t.gross for t in trades), [D("45"), D("55")])

    def test_unmatched_leg_at_expiry_blocks_expired_worthless(self):
        # Only the open fills of one spread are present, plus a settle fill on the right strike
        # but the wrong side, which fits no known position: the trade must not be called "expired worthless".
        fs = [fill("Sold", "OPEN", "C", 7100, 1, 1.00, time(10, 0)),
              fill("Bought", "OPEN", "C", 7110, 1, 0.20, time(10, 0)),
              fill("Sold", "CLOSE", "C", 7100, 1, 5.00, time(16, 0), settle=True)]
        trades, orphans = process([conf(fs)])
        self.assertEqual(len(orphans), 1)
        self.assertEqual(trades[0].status, "needs_attention")
        self.assertIn("orphan_leg_at_expiry", trades[0].flags)

    def test_debit_spread_premium_is_paid_not_collected(self):
        from pnl.export import trades_csv
        import csv, io
        fs = [fill("Bought", "OPEN", "C", 7100, 1, 2.00, time(10, 0)),
              fill("Sold", "OPEN", "C", 7110, 1, 0.50, time(10, 0)),
              fill("Sold", "CLOSE", "C", 7100, 1, 3.00, time(12, 0)),
              fill("Bought", "CLOSE", "C", 7110, 1, 1.00, time(12, 0))]
        trades, orphans = process([conf(fs)])
        self.assertEqual(orphans, [])
        row = next(csv.DictReader(io.StringIO(trades_csv(trades))))
        self.assertEqual(row["premium_collected"], "0.00")
        self.assertEqual(row["premium_paid"], "150.00")
        self.assertEqual(row["gross_pnl"], "50.00")

    def test_same_trade_number_on_different_days_both_kept_and_duplicate_file_ignored(self):
        d2 = date(2026, 10, 15)
        a = [fill("Sold", "OPEN", "C", 7100, 1, 1.0, time(10, 0), tn="DUP1"),
             fill("Bought", "OPEN", "C", 7110, 1, 0.2, time(10, 0), tn="DUP2")]
        b = [fill("Sold", "OPEN", "C", 7100, 1, 1.0, time(10, 0), day=d2, tn="DUP1"),
             fill("Bought", "OPEN", "C", 7110, 1, 0.2, time(10, 0), day=d2, tn="DUP2")]
        trades, _ = process([conf(a, DAY, "a"), conf(b, d2, "b"), conf(a, DAY, "a-copy")])
        self.assertEqual(len(trades), 2)


class ParserRegression(unittest.TestCase):
    def test_fill_line_with_alphanumeric_exchange_code_is_parsed(self):
        from pnl.parser import FILL_RE
        line = ("08/04/2026       08/05/2026   Sold      INVESCO QQQ TR                  "
                "QQQ 260804P722         1       0.30   Principal                30.00   MGN      S1   S2747")
        m = FILL_RE.match(line)
        self.assertIsNotNone(m)
        self.assertEqual(m.group("tn"), "S2747")


if __name__ == "__main__":
    unittest.main()
