# DailyOptionAssess API contract

Base URL: `VITE_API_BASE_URL` (no trailing slash). All paths below start with `/api`.
Every endpoint except `POST /api/login` and `GET /api/health` needs `Authorization: Bearer <token>`.
A missing or expired token returns **401** (send the user to the login screen).

All money values are **strings** with two decimals (`"-211.56"`); ratios are strings with four decimals
(`"-0.0300"` = -3.0%). Show them as given. Never add, subtract, multiply or re-derive them.

Query parameters used by most read endpoints:
- `underlyings`: omit for the default (SPX and SPXW only); `ALL` for everything; or a comma list.
- `from`, `to`: `YYYY-MM-DD`, inclusive.

| Method and path | Purpose |
|---|---|
| `POST /api/login` body `{"password": "..."}` | returns `{ok, token, expires_in_days}` |
| `GET /api/me` | `200` if the token is valid |
| `GET /api/imports` | list of imported days, newest first: `{date, fills, pages, imported_at}` |
| `POST /api/import` multipart field `files` (one or many PDFs) | `{results:[{file,status,fills,new_fills,warnings[],errors[]}]}`; status is `imported`, `duplicate` or `error` |
| `GET /api/day/{YYYY-MM-DD}` | one day: `{date, summary, trades[], series[]}` |
| `GET /api/period?granularity=day\|week\|month\|year` | `{granularity, total, rows[]}`; each row has `start` plus the summary fields and `cumulative_net` |
| `GET /api/trades?from&to&result=win\|loss&strategy&tag` | array of trades |
| `GET /api/attention` | `{trades[], orphans[]}` things to review |
| `PUT /api/notes/{trade.key}` body `{market_condition, learnings, tags[]}` | saves a trade note |
| `GET /api/export/trades.csv`, `fills.csv`, `daily.csv` | CSV file; same `from`, `to`, `underlyings` |

## Summary object (day.summary, period.total, period.rows[])
`trades, wins, losses, win_rate, premium_collected, premium_paid, gross, fees, net, max_risk, return_on_risk`

## Trade object
`id, key, underlying, expiry, strategy, right, short_strike, long_strike, contracts, open_date, date, status,
flags[], entry_avg, exit_avg, premium_collected, premium_paid, gross, fees, net, max_risk, return_on_risk, result,
fee_breakdown{commission, cat_fee, regulatory_clearing_fee, finra_fee, sec_fee}, fee_source, legs[], note{market_condition, learnings, tags[]}`

- `key` identifies the trade for notes. It never changes. Use it in `PUT /api/notes/{key}`.
- `date` is the day the trade finished (the expiry day if it expired). `open_date` is when it was opened.
- `result` is `win`, `loss` or `scratch`. `status` is `closed`, `settled`, `expired` (expired worthless, inferred) or `needs_attention`.
- `flags` can include `scaled`, `legged_out`, `expired_inferred`; show them as small labels, not errors.
- Credit spreads fill `premium_collected` (and `premium_paid` is `"0.00"`); debit spreads the reverse.
- `legs[]` are the individual fills: `{trade_number, date, time, side, action, right, strike, quantity, price, net_amount}`.

## Day series
`series[]` is `{id, net, cumulative}` in trade order, for the running-total line.

## CSV downloads
Because they need the auth header, fetch them with `fetch()`, turn the response into a Blob and download it.
(A plain link would not send the token.)

## Errors
Non-2xx responses have `{"detail": "message"}`. Show the message. `429` on login means too many attempts.
