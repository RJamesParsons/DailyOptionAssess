"""Fee estimator accuracy against the real confirmations.

NOTE: these rates were fitted to these same files, so this is an in-sample check. It proves the
schedule reproduces what was observed, not that it will predict a future fee change.
"""
import sys
import unittest
from decimal import Decimal as D
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pnl.fees import estimate_fill_fees, estimate_total, schedule_for  # noqa: E402
from pnl.parser import parse_confirmation  # noqa: E402

FILES = sorted((ROOT / "fixtures").glob("*.pdf"))


class FeeEstimator(unittest.TestCase):
    def test_every_fill_within_two_cents_and_every_line_within_one(self):
        worst_total = D(0)
        n = 0
        for path in FILES:
            conf = parse_confirmation(path)
            for f in conf.fills:
                est = estimate_fill_fees(f.trade_date, f.side, f.quantity, f.is_settlement)
                total_err = abs(sum(est.values(), D(0)) - f.total_fees)
                worst_total = max(worst_total, total_err)
                self.assertLessEqual(total_err, D("0.02"), f"{path.name[:8]} {f.trade_number}")
                for line in set(est) | set(f.fees):
                    self.assertLessEqual(abs(est.get(line, D(0)) - f.fees.get(line, D(0))), D("0.01"),
                                         f"{path.name[:8]} {f.trade_number} {line}")
                n += 1
        self.assertEqual(n, 118)

    def test_october_files_are_exact(self):
        """The October files are the schedule currently in force, so they must match to the cent."""
        for path in FILES:
            if not path.name.startswith("10"):
                continue
            for f in parse_confirmation(path).fills:
                est = estimate_total(f.trade_date, f.side, f.quantity, f.is_settlement)
                self.assertEqual(est, f.total_fees, f"{path.name[:8]} {f.trade_number}")

    def test_schedule_selection(self):
        self.assertEqual(schedule_for(__import__("datetime").date(2026, 10, 14)).name, "Oct 8 2026 onward")
        with self.assertRaises(ValueError):
            schedule_for(__import__("datetime").date(2025, 12, 31))


if __name__ == "__main__":
    unittest.main()
