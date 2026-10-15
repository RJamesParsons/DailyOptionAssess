# Lovable instructions: DailyOptionAssess front end

Paste everything below the line into Lovable as the first message. Attach `API.md` and the files in `sample/`
(or paste their contents) so Lovable can build against real response shapes.

---

Build the front end only for a single-user options trading P&L viewer, "Daily Option Assess". A separate,
already-tested Python API does all parsing, matching and calculation. Your job is the screens.

## Hard rules
1. **Do not create a database.** Do not enable Lovable Cloud, Supabase, or any storage or auth service. Everything
   comes from the API in `API.md`. The only thing stored in the browser is the login token.
2. **Do not calculate trading numbers.** Never add, subtract, average, round or re-derive P&L, fees, premium, risk,
   win rate or return on risk. Display the strings the API returns. You may format them for display only
   (thousands separators, a $ sign, % for ratios). Do not sort or filter in a way that changes totals; use the API's
   query parameters instead.
3. **Do not invent data.** If a value is null, show a dash. If a list is empty, show a friendly empty state.
4. **Base URL from the environment.** Read it from `VITE_API_BASE_URL`. If `VITE_USE_MOCK=true`, serve the sample
   JSON files from `src/mock/` instead of calling the network, so the screens can be built before the API is
   online. Mock mode must be a single switch in one data module; no screen may know about it.
5. **Auth:** one login screen with a password field. `POST /api/login`, keep the returned `token` in memory and in
   localStorage (wrapped in try/catch), and send `Authorization: Bearer <token>` on every request. On any 401, clear
   the token and return to the login screen. Provide a Sign out button.
6. No trading advice, predictions or recommendations anywhere in the UI text.

## Screens
Top navigation on desktop; bottom tab bar on phone. Must work well at 390px wide and on desktop.

1. **Day (home).** Opens on the most recent imported day (first item of `GET /api/imports`). Date picker with
   previous/next-trading-day buttons. Summary tiles from `summary`: Net P&L, Gross P&L, Fees, Premium collected
   (and Premium paid only when it is not 0.00), Wins/Losses, Win rate, Return on risk. A bar chart of each trade's
   `net` with a line for `series[].cumulative`. Then one card per trade: title (underlying, strategy, strikes,
   contracts), result badge, flag labels, net in green or red, a bar showing its size relative to the day's largest
   trade, entry and exit averages, gross, max risk, return on risk, the itemized fee list from `fee_breakdown`
   (commission, CAT, regulatory and clearing, FINRA, SEC) with the total, a collapsible fills table from `legs`,
   and the note editor.
2. **Week / Month / Year.** A segmented control (Day, Week, Month, Year) calling `GET /api/period`. Summary tiles from
   `total`, a bar chart of `net` per row with the `cumulative_net` line, and a table of rows. Clicking a row in Day
   mode opens that day.
3. **Trades.** A filterable table from `GET /api/trades`: date range, result, tag. Row click opens that day. Show
   a count only (the number of rows), nothing computed from the rows.
4. **Import.** A drag-and-drop zone and file picker accepting several PDFs. Upload with `POST /api/import` (multipart
   field name `files`). Show one result line per file: status (`imported`, `duplicate`, `error`), new fills, and any
   `errors` or `warnings` text. After success, offer "Open latest day". Re-uploading must never look like a failure:
   `duplicate` is shown as neutral.
5. **Needs attention.** From `GET /api/attention`: a list of `orphans` (fills with no matching entry) and the review
   `trades`. Read-only.
6. **Export.** On Day, Period and Trades, three buttons (Trades CSV, Fills CSV, Daily CSV) that download from
   `/api/export/{kind}.csv` with the same `from`, `to` and `underlyings` the screen is showing. Use fetch + Blob
   so the auth header is sent.
7. **Underlying switch** in the header: "SPX / SPXW" (default, sends no `underlyings` parameter) and "All"
   (`underlyings=ALL`). It applies to every screen and export.

## Trade notes
Each trade card has: a market-condition dropdown (trending up, trending down, range-bound, high volatility / event
day, other), a tags input (comma separated), and a learnings text box. Autosave with a 500 ms debounce using
`PUT /api/notes/{trade.key}` and show "Saved" or the error. Send all three fields every time.

## Look and feel
Clean, calm, data-first. Light and dark themes following the system setting. Green for positive and red for negative
numbers, always paired with the sign or a label (never colour alone). Tabular numerals for money columns. Large tap
targets on phone. Charts with Recharts. Loading skeletons and clear error messages with a Retry button.

## Acceptance checklist (using the sample data)
- Day 2026-10-13 shows Net -$177.32, Gross -$130.00, Fees $47.32, Premium collected $3,450.00, 1 win, 1 loss,
  Win rate 50.0%, Return on risk -1.5%.
- Its first trade (SPXW call credit spread 7800/7810 x 10) shows Net -$211.56, Fees $31.56 (commission 30.00, CAT 0.10,
  regulatory and clearing 1.46, FINRA 0.00, SEC 0.00), Return on risk -3.0%, Max risk $7,050.00.
- Editing a note and reloading the page keeps the note (in mock mode, keep it in memory only and say so).
- No network request goes anywhere except `VITE_API_BASE_URL`.
- No database, no Supabase, no Lovable Cloud in the project.
