"""Acceptance tests from the spec, run against the six real confirmations.

Run:  python3 -m unittest discover -s tests -v   (from the project folder)
"""
import sys
import tempfile
import unittest
from collections import Counter
from decimal import Decimal as D
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pnl.parser import parse_confirmation  # noqa: E402
from pnl.matching import daily_summary, process  # noqa: E402

FIX = ROOT / "fixtures"


def load(prefix: str):
    path = next(FIX.glob(f"{prefix}*.pdf"))
    conf = parse_confirmation(path)
    if not conf.ok:
        return conf, None, None
    trades, orphans = process([conf])
    return conf, trades, orphans


def shape(trades):
    return [(t.short_strike, t.long_strike, t.qty_opened) for t in trades]


class ParserChecks(unittest.TestCase):
    def test_every_file_passes_line_and_page_checks(self):
        expected_fills = {"02192026": 4, "06172026": 18, "10012026": 28,
                          "10082026": 34, "10092026": 20, "10132026": 14}
        for prefix, n in expected_fills.items():
            conf = parse_confirmation(next(FIX.glob(f"{prefix}*.pdf")))
            self.assertTrue(conf.ok, f"{prefix}: {conf.errors}")
            self.assertEqual(len(conf.fills), n, prefix)
            self.assertEqual(conf.warnings, [], prefix)
            self.assertEqual(conf.account_last4, "3103")

    def test_missing_page_blocks_import(self):
        """A dropped page must fail the page check, so a missing page can't pass as 'expired'."""
        from pypdf import PdfReader, PdfWriter
        src = next(FIX.glob("10132026*.pdf"))
        reader = PdfReader(str(src))
        w = PdfWriter()
        for i, page in enumerate(reader.pages):
            if i != 1:
                w.add_page(page)
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "short.pdf"
            with open(out, "wb") as fh:
                w.write(fh)
            conf = parse_confirmation(out)
        self.assertFalse(conf.ok)
        self.assertTrue(any("page" in e.lower() for e in conf.errors), conf.errors)
        with self.assertRaises(ValueError):
            process([conf])


class Oct13(unittest.TestCase):
    def test_hand_calculated_values(self):
        conf, trades, orphans = load("10132026")
        self.assertEqual(orphans, [])
        self.assertEqual(len(trades), 2)
        call, put = trades
        self.assertEqual((call.strategy, call.short_strike, call.long_strike, call.qty_opened),
                         ("call credit spread", D(7800), D(7810), 10))
        self.assertEqual((call.premium, call.gross, call.fees, call.net, call.max_risk),
                         (D("2950"), D("-180"), D("31.56"), D("-211.56"), D("7050")))
        self.assertEqual(round(call.return_on_risk, 3), D("-0.030"))
        self.assertEqual(call.result, "loss")
        self.assertEqual(call.entry_avg, D("2.95"))
        self.assertEqual(call.exit_avg, D("3.13"))
        self.assertEqual((put.strategy, put.short_strike, put.long_strike, put.qty_opened),
                         ("put credit spread", D(7790), D(7780), 5))
        self.assertEqual((put.premium, put.gross, put.fees, put.net, put.max_risk),
                         (D("500"), D("50"), D("15.76"), D("34.24"), D("4500")))
        self.assertEqual(round(put.return_on_risk, 4), D("0.0076"))
        day = daily_summary(trades)[0]
        self.assertEqual((day["gross_pnl"], day["fees"], day["net_pnl"]),
                         (D("-130"), D("47.32"), D("-177.32")))


class TradeShapes(unittest.TestCase):
    def test_oct8_flat_to_flat_grouping(self):
        _, trades, orphans = load("10082026")
        self.assertEqual(orphans, [])
        self.assertEqual(shape(trades), [
            (D(7750), D(7740), 10), (D(7750), D(7740), 5), (D(7750), D(7740), 5),
            (D(7750), D(7740), 15), (D(7725), D(7715), 1)])

    def test_oct1_calls_and_puts(self):
        _, trades, _ = load("10012026")
        self.assertEqual(len(trades), 6)
        self.assertEqual(Counter(t.right for t in trades), Counter({"P": 4, "C": 2}))
        self.assertEqual(max(t.qty_opened for t in trades), 10)
        big = next(t for t in trades if t.qty_opened == 10)
        self.assertEqual(big.right, "C")

    def test_oct9_averaging_across_fills(self):
        _, trades, _ = load("10092026")
        self.assertEqual(len(trades), 4)
        big = next(t for t in trades if t.qty_opened == 10)
        self.assertEqual(sum(1 for s in big.spread_fills if s.action == "open"), 2)
        self.assertEqual(sum(1 for s in big.spread_fills if s.action == "close"), 2)
        self.assertEqual(big.entry_avg, D("2.45"))  # averaged from fill principals


class Jun17Settlement(unittest.TestCase):
    def test_settlement_and_inferred_expiry(self):
        _, trades, orphans = load("06172026")
        self.assertEqual(orphans, [])
        self.assertEqual(len(trades), 3)
        puts = [t for t in trades if t.right == "P"]
        calls = [t for t in trades if t.right == "C"]
        self.assertEqual(len(puts), 2)
        for t in puts:
            self.assertEqual(t.status, "settled")
            self.assertEqual(t.implied_settlement, D("7420.10"))
            self.assertEqual(t.flags, [])
        self.assertEqual(calls[0].status, "expired")
        self.assertIn("expired_inferred", calls[0].flags)
        self.assertEqual(sum(t.gross for t in trades), D("-5270"))
        self.assertEqual(sorted(t.gross for t in puts), [D("-3970"), D("-1445")])
        self.assertEqual(calls[0].gross, D("145"))


class Feb19OutOfScope(unittest.TestCase):
    def test_parked_not_counted(self):
        _, trades, orphans = load("02192026")
        self.assertEqual(trades, [])
        self.assertEqual(len(orphans), 2)
        self.assertEqual(daily_summary(trades), [])


class Integrity(unittest.TestCase):
    def test_day_net_equals_independent_cash_total(self):
        """Independent check: summing printed NET AMOUNTs (sold +, bought -) must equal the sum of
        trade net P&L on any fully flat day. This does not use the matching logic at all."""
        for prefix in ("10012026", "10082026", "10092026", "10132026", "06172026"):
            conf, trades, orphans = load(prefix)
            cash = sum((f.net_amount if f.side == "Sold" else -f.net_amount for f in conf.fills), D(0))
            self.assertEqual(orphans, [], prefix)
            self.assertEqual(sum((t.net for t in trades), D(0)), cash, prefix)

    def test_every_fill_is_accounted_for(self):
        for prefix in ("10012026", "10082026", "10092026", "10132026", "06172026", "02192026"):
            conf, trades, orphans = load(prefix)
            in_trades = {f.trade_number for t in trades for f in t.fills}
            in_orphans = {f.trade_number for o in orphans for f in o.fills}
            self.assertEqual(in_trades | in_orphans, {f.trade_number for f in conf.fills}, prefix)
            self.assertTrue(in_trades.isdisjoint(in_orphans), prefix)

    def test_reimport_changes_nothing(self):
        conf, trades, _ = load("10132026")
        again, _ = process([conf, conf])
        self.assertEqual([(t.id, t.net, t.fees) for t in trades],
                         [(t.id, t.net, t.fees) for t in again])

    def test_multi_file_import_matches_single_files(self):
        confs = [parse_confirmation(p) for p in sorted(FIX.glob("*.pdf"))]
        both, orphans = process(confs)
        singles = []
        for c in confs:
            singles.extend(process([c])[0])
        self.assertEqual(sorted((t.id, t.net) for t in both), sorted((t.id, t.net) for t in singles))
        self.assertEqual(len(orphans), 2)  # only the Feb 19 closing fills


if __name__ == "__main__":
    unittest.main()
