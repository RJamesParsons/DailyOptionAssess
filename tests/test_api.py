"""End-to-end API tests against a temporary SQLite database."""
import csv
import io
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import bcrypt  # noqa: E402

_dir = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_dir}/test.db"
os.environ["APP_SESSION_SECRET"] = "test-secret"
os.environ["APP_PASSWORD_HASH"] = bcrypt.hashpw(b"pw", bcrypt.gensalt(4)).decode()
os.environ["APP_SECURE_COOKIE"] = "0"

from fastapi.testclient import TestClient  # noqa: E402

from app import service  # noqa: E402
from app.main import app  # noqa: E402

FIX = sorted((ROOT / "fixtures").glob("*.pdf"))


def upload(client, paths):
    files = [("files", (p.name, p.read_bytes(), "application/pdf")) for p in paths]
    return client.post("/api/import", files=files)


@unittest.skipUnless(len(FIX) == 6, "needs the six fixture PDFs in fixtures/")
class Api(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ctx = TestClient(app)
        cls.client = cls.ctx.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.ctx.__exit__(None, None, None)

    def test_01_requires_login(self):
        self.assertEqual(self.client.get("/api/imports").status_code, 401)
        self.assertEqual(self.client.post("/api/login", json={"password": "bad"}).status_code, 401)
        self.assertEqual(self.client.post("/api/login", json={"password": "pw"}).status_code, 200)
        self.assertEqual(self.client.get("/api/imports").status_code, 200)

    def test_02_import_oct13_and_day_view(self):
        oct13 = [p for p in FIX if p.name.startswith("10132026")]
        r = upload(self.client, oct13).json()["results"][0]
        self.assertEqual((r["status"], r["fills"]), ("imported", 14))
        d = self.client.get("/api/day/2026-10-13").json()
        self.assertEqual(d["summary"]["net"], "-177.32")
        self.assertEqual(d["summary"]["fees"], "47.32")
        self.assertEqual([t["net"] for t in d["trades"]], ["-211.56", "34.24"])
        self.assertEqual(sum(float(v) for v in d["trades"][0]["fee_breakdown"].values()), 31.56)
        self.assertEqual(d["series"][-1]["cumulative"], "-177.32")

    def test_03_reimport_changes_nothing(self):
        oct13 = [p for p in FIX if p.name.startswith("10132026")]
        r = upload(self.client, oct13).json()["results"][0]
        self.assertEqual(r["status"], "duplicate")
        self.assertEqual(self.client.get("/api/day/2026-10-13").json()["summary"]["net"], "-177.32")

    def test_04_import_rest_and_period_views(self):
        r = upload(self.client, [p for p in FIX if not p.name.startswith("10132026")]).json()["results"]
        self.assertEqual([x["status"] for x in r], ["imported"] * 5)
        self.assertTrue(all(not x["errors"] for x in r))
        m = self.client.get("/api/period?granularity=month").json()
        self.assertEqual([x["start"] for x in m["rows"]], ["2026-06-01", "2026-10-01"])
        daily = self.client.get("/api/period?granularity=day").json()["rows"]
        self.assertEqual({x["start"]: x["net"] for x in daily}["2026-06-17"], "-5299.60")
        self.assertEqual(self.client.get("/api/day/2026-10-01").json()["summary"]["net"], "1524.40")

    def test_05_notes_roundtrip_and_csv(self):
        t = self.client.get("/api/day/2026-10-13").json()["trades"][0]
        r = self.client.put(f"/api/notes/{t['key']}", json={
            "market_condition": "trending up", "learnings": "=BAD()", "tags": ["fomc"]})
        self.assertEqual(r.status_code, 200)
        t2 = self.client.get("/api/day/2026-10-13").json()["trades"][0]
        self.assertEqual(t2["note"]["market_condition"], "trending up")
        text = self.client.get("/api/export/trades.csv?from=2026-10-13&to=2026-10-13").text
        rows = list(csv.DictReader(io.StringIO(text)))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["learnings"], "'=BAD()")
        self.assertEqual(rows[0]["premium_paid"], "0.00")
        self.assertEqual(self.client.get("/api/export/fills.csv?from=2026-10-13&to=2026-10-13").text.count("\n"), 15)
        self.assertIn("-177.32", self.client.get("/api/export/daily.csv?from=2026-10-13&to=2026-10-13").text)

    def test_06_default_filter_and_attention(self):
        a = self.client.get("/api/attention?underlyings=ALL").json()
        self.assertEqual(len(a["orphans"]), 2)           # the Feb 19 fills with no entries on file
        self.assertEqual(len(self.client.get("/api/trades").json()), 20)

    def test_07_database_holds_no_personal_data(self):
        con = sqlite3.connect(f"{_dir}/test.db")
        blob = "".join(str(v) for t in ("import", "fill", "trade_note")
                       for row in con.execute(f"select * from {t}") for v in row).upper()
        for needle in ("PARSONS", "MAIN ST", "AMERICAN FORK", "12013103"):
            self.assertNotIn(needle, blob)
        self.assertEqual({r[0] for r in con.execute("select distinct length(account_last4) from import")}, {4})

    def test_08_rejects_non_pdf(self):
        r = self.client.post("/api/import", files=[("files", ("x.pdf", b"hello", "application/pdf"))])
        self.assertEqual(r.json()["results"][0]["status"], "error")

    def test_09_logout(self):
        self.client.post("/api/logout")
        self.client.cookies.clear()
        self.assertEqual(self.client.get("/api/day/2026-10-13").status_code, 401)


if __name__ == "__main__":
    unittest.main()
