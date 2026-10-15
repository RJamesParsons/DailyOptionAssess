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

## Run locally (browser UI included)

```
pip install -r requirements.txt            # also needs poppler-utils (pdftotext)
python -m app.run_local --load /path/to/confirmations    # --load is optional; first run asks for a password
```

It opens http://localhost:8000. The first run saves your settings to a local `.env` file (git-ignored);
data lives in `dailyoptionassess.db`. Add `--host 0.0.0.0` to open it from your phone on the same Wi-Fi
(http://<your-computer-ip>:8000). You can also import PDFs from the Import tab.

The screens are plain files in `app/static/` (`index.html`, `app.css`, `app.js`) with no build step:
edit and refresh the browser. Colours are variables at the top of `app.css`; each screen is one function in `app.js`.

Manual setup instead of `run_local`: `python -m app.hash_password`, set `APP_PASSWORD_HASH`, `APP_SESSION_SECRET`,
`APP_SECURE_COOKIE=0`, then `uvicorn app.main:app --port 8000`.

`DATABASE_URL` defaults to a local SQLite file; set it to a Postgres URL on Railway.
Only extracted fills are stored (never the PDF, name or address; account last 4 only).

Tests: `python3 -m unittest discover -s tests` (the API tests need the six fixture PDFs in `fixtures/`).

## Separate front ends
`docs/lovable/` holds the API contract and sample responses, in case the UI is ever hosted separately.
Set `APP_CORS_ORIGINS` to that app's origin so the browser may call the API.
