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

## Run locally

```
pip install -r requirements.txt            # also needs poppler-utils (pdftotext)
python -m app.hash_password                # prints a value for APP_PASSWORD_HASH
export APP_PASSWORD_HASH='...' APP_SESSION_SECRET="$(python -c 'import secrets;print(secrets.token_hex(32))')"
export APP_SECURE_COOKIE=0                 # local http only
python -m scripts.load_pdfs /path/to/confirmations   # optional bulk load
uvicorn app.main:app --port 8000           # open http://localhost:8000
```

`DATABASE_URL` defaults to a local SQLite file; set it to a Postgres URL on Railway.
Only extracted fills are stored (never the PDF, name or address; account last 4 only).
