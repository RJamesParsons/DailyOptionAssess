import csv
import io
import sys
import unittest
from decimal import Decimal as D
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pnl.export import daily_csv, fills_csv, safe_text, trades_csv  # noqa: E402
from pnl.matching import process  # noqa: E402
from pnl.parser import parse_confirmation  # noqa: E402

FIX = ROOT / "fixtures"

# Copied verbatim from the "CSV export" section of the spec doc.
SPEC_SAMPLE = """trade_date,underlying,expiry,strategy,short_strike,long_strike,contracts,entry_avg,exit_avg,premium_collected,premium_paid,gross_pnl,fees,net_pnl,max_risk,return_on_risk,result,fee_source,market_condition,learnings,tags
2026-10-13,SPXW,2026-10-13,call credit spread,7800,7810,10,2.95,3.13,2950.00,0.00,-180.00,31.56,-211.56,7050.00,-0.0300,loss,actual,,,
2026-10-13,SPXW,2026-10-13,put credit spread,7790,7780,5,1.00,0.90,500.00,0.00,50.00,15.76,34.24,4500.00,0.0076,win,actual,,,
"""


def oct13():
    conf = parse_confirmation(next(FIX.glob("10132026*.pdf")))
    trades, orphans = process([conf])
    return conf, trades


class Exports(unittest.TestCase):
    def test_trades_csv_matches_spec_sample_exactly(self):
        _, trades = oct13()
        self.assertEqual(trades_csv(trades), SPEC_SAMPLE)

    def test_notes_are_included_and_formula_guarded(self):
        _, trades = oct13()
        notes = {trades[0].id: {"market_condition": "trending up",
                                "learnings": "=HYPERLINK(\"http://x\")", "tags": ["fomc", "-bad"]}}
        rows = list(csv.DictReader(io.StringIO(trades_csv(trades, notes))))
        self.assertEqual(rows[0]["market_condition"], "trending up")
        self.assertEqual(rows[0]["learnings"], "'=HYPERLINK(\"http://x\")")
        self.assertEqual(rows[0]["tags"], "fomc;-bad")  # starts with 'f', so unchanged
        self.assertEqual(rows[1]["learnings"], "")
        self.assertEqual(safe_text("@SUM(1)"), "'@SUM(1)")
        self.assertEqual(safe_text("+1"), "'+1")

    def test_fills_csv_reconciles_to_trades(self):
        conf, trades = oct13()
        rows = list(csv.DictReader(io.StringIO(fills_csv(conf.fills, trades))))
        self.assertEqual(len(rows), 14)
        self.assertEqual(rows[0]["symbol"], "SPXW 261013C7800")
        self.assertTrue(all(r["trade_id"] for r in rows))
        # Fee columns sum to the trade fees, and net_amount reconciles to principal +/- fees.
        fees = sum(D(r[c] or 0) for r in rows for c in
                   ("commission", "cat_fee", "regulatory_clearing_fee", "finra_fee", "sec_fee"))
        self.assertEqual(fees, sum(t.fees for t in trades))
        for r in rows:
            f = sum(D(r[c] or 0) for c in ("commission", "cat_fee", "regulatory_clearing_fee",
                                            "finra_fee", "sec_fee"))
            expect = D(r["principal"]) - f if r["side"] == "sold" else D(r["principal"]) + f
            self.assertEqual(D(r["net_amount"]), expect, r["trade_number"])

    def test_daily_csv_oct13(self):
        _, trades = oct13()
        rows = list(csv.DictReader(io.StringIO(daily_csv(trades))))
        self.assertEqual(rows, [{
            "trade_date": "2026-10-13", "trades": "2", "wins": "1", "losses": "1",
            "premium_collected": "3450.00", "premium_paid": "0.00",
            "gross_pnl": "-130.00", "fees": "47.32",
            # -177.32 / (7050 + 4500) = -0.015352..., rounded to 4 places
            "net_pnl": "-177.32", "return_on_risk": "-0.0154"}])

    def test_all_files_export_and_expired_trade_dates(self):
        confs = [parse_confirmation(p) for p in sorted(FIX.glob("*.pdf"))]
        trades, orphans = process(confs)
        text = trades_csv(trades)
        rows = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual(len(rows), 2 + 3 + 6 + 5 + 4)  # Oct13, Jun17, Oct1, Oct8, Oct9
        self.assertEqual([r["trade_date"] for r in rows], sorted(r["trade_date"] for r in rows))
        daily = list(csv.DictReader(io.StringIO(daily_csv(trades))))
        self.assertEqual([d["trade_date"] for d in daily],
                         ["2026-06-17", "2026-10-01", "2026-10-08", "2026-10-09", "2026-10-13"])
        allfills = [f for c in confs for f in c.fills]
        self.assertEqual(len(list(csv.DictReader(io.StringIO(fills_csv(allfills, trades, "actual"))))), 118)
        orphan_rows = [r for r in csv.DictReader(io.StringIO(fills_csv(allfills, trades))) if not r["trade_id"]]
        self.assertEqual(len(orphan_rows), 4)  # the four Feb 19 fills


if __name__ == "__main__":
    unittest.main()
