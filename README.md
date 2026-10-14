# DailyOptionAssess

Single-user app that turns TradeStation daily confirmation PDFs into per-trade P&L,
itemized fees, premium collected/paid and return on risk (SPX/SPXW 0DTE vertical spreads in v1).

- `pnl/parser.py` extracts fills from confirmation PDFs (needs `pdftotext` from poppler-utils)
- `pnl/matching.py` pairs legs, groups trades, settles at expiry, computes metrics
- `pnl/fees.py` effective-dated fee estimator for days without a PDF
- `pnl/export.py` CSV exports (trades, fills, daily summary)
- `scripts/backfill.py <dir>` backfill report over a folder of PDFs

Confirmation PDFs contain personal data and are NOT stored in this repo (see `.gitignore`).
Put sample PDFs in `fixtures/` locally to run the acceptance tests:
`python3 -m unittest discover -s tests`.
