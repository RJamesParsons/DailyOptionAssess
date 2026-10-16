/* Daily Option Assess - front end (plain JS, no build step).
 *
 * Rules this file follows:
 *  - Every trading number shown comes from the API as a string; nothing here adds, averages or re-derives P&L,
 *    fees, premium, risk or win rate. Number() is used only for colour/sign, chart geometry and display scaling.
 *  - All server calls go through api(). Change the look in app.css; change screens in the view functions below.
 */
"use strict";

/* ---------- small helpers ---------- */
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const nil = v => v === null || v === undefined || v === "";
const sign = v => (nil(v) ? 0 : Math.sign(Number(v)));
const cls = v => (sign(v) > 0 ? "win" : sign(v) < 0 ? "loss" : "");
const group = s => s.replace(/\B(?=(\d{3})+(?!\d))/g, ",");

/** "-211.56" -> "-$211.56" (string formatting only; "+" prefix optional). */
function money(v, plus = false) {
  if (nil(v)) return "–";
  let s = String(v).trim(), neg = s[0] === "-";
  if (neg || s[0] === "+") s = s.slice(1);
  const [i, d] = s.split(".");
  const body = "$" + group(i) + (d !== undefined ? "." + d : "");
  return neg ? "−" + body : plus && sign(v) > 0 ? "+" + body : body;
}
/** Ratio string "-0.0300" -> "-3.0%". */
function pct(v, plus = false) {
  if (nil(v)) return "–";
  const n = Number(v) * 100, t = Math.abs(n).toFixed(1) + "%";
  if (t === "0.0%") return t;
  return n < 0 ? "−" + t : plus ? "+" + t : t;
}
const short = v => { // axis labels only
  const n = Number(v), a = Math.abs(n), s = a >= 1000 ? (a / 1000).toFixed(a >= 10000 ? 0 : 1) + "k" : a.toFixed(0);
  return (n < 0 ? "−" : "") + "$" + s;
};
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
function dlabel(d, withYear = true) {
  const [y, m, day] = d.split("-").map(Number);
  const wd = new Date(Date.UTC(y, m - 1, day)).toLocaleDateString("en-US", { weekday: "short", timeZone: "UTC" });
  return `${wd} ${MONTHS[m - 1]} ${day}${withYear ? ", " + y : ""}`;
}
function plabel(g, start) {
  const [y, m, d] = start.split("-").map(Number);
  if (g === "year") return String(y);
  if (g === "month") return `${MONTHS[m - 1]} ${y}`;
  if (g === "week") return `Wk ${MONTHS[m - 1]} ${d}`;
  return `${MONTHS[m - 1]} ${d}`;
}
const tradeTitle = t =>
  `${t.underlying} ${t.strategy}${nil(t.short_strike) ? "" : ` ${t.short_strike}/${t.long_strike}`} × ${t.contracts}`;

/* ---------- state & API ---------- */
const TOKEN_KEY = "doa_token";
const S = { und: "", imports: [], toast: null };
const getToken = () => { try { return localStorage.getItem(TOKEN_KEY); } catch { return null; } };
const setToken = t => { try { t ? localStorage.setItem(TOKEN_KEY, t) : localStorage.removeItem(TOKEN_KEY); } catch { /* ignore */ } };

async function api(path, opt = {}, raw = false) {
  const headers = new Headers(opt.headers || {});
  const t = getToken();
  if (t) headers.set("Authorization", "Bearer " + t);
  let r;
  try { r = await fetch("/api" + path, { ...opt, headers, credentials: "same-origin" }); }
  catch { throw new Error("Could not reach the server. Is it running?"); }
  if (r.status === 401 && !path.startsWith("/login")) { showLogin(); throw new Error("Signed out"); }
  if (!r.ok) {
    let m = r.status === 429 ? "Too many attempts. Please wait and try again." : `Request failed (${r.status})`;
    try { const j = await r.json(); if (j && j.detail) m = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail); } catch { /* ignore */ }
    throw new Error(m);
  }
  return raw ? r.blob() : r.json();
}
const qs = o => { const p = new URLSearchParams(); Object.entries(o).forEach(([k, v]) => { if (v) p.set(k, v); }); const s = p.toString(); return s ? "?" + s : ""; };
const scope = (extra = {}) => qs({ underlyings: S.und, ...extra });

async function download(kind, from, to) {
  try {
    const blob = await api(`/export/${kind}.csv${scope({ from, to })}`, {}, true);
    const url = URL.createObjectURL(blob), a = document.createElement("a");
    a.href = url; a.download = `${kind}${from ? "_" + from : ""}${to && to !== from ? "_" + to : ""}.csv`;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 30000);
  } catch (e) { alert(e.message); }
}
const exportBar = (from, to) => `<div class="row" data-export data-from="${esc(from || "")}" data-to="${esc(to || "")}">
  <span class="mute" style="font-size:12px">Export CSV</span>
  <button class="btn" data-kind="trades">Trades</button><button class="btn" data-kind="fills">Fills</button><button class="btn" data-kind="daily">Daily</button><button class="btn" data-kind="analysis" title="Trades with open/close times and call/put, for outside analysis">Analysis</button></div>`;

/* ---------- shell: login, tabs, routing ---------- */
const TABS = [["day", "Day", "▦"], ["period", "Periods", "▥"], ["trades", "Trades", "☰"], ["import", "Import", "⇪"], ["attention", "Attention", "!"]];

function showLogin() { $("#app").classList.add("hide"); $("#login").classList.remove("hide"); $("#pw").focus(); }
function showApp() { $("#login").classList.add("hide"); $("#app").classList.remove("hide"); }

function route() {
  const h = (location.hash || "#/day").slice(2).split("/");
  return { name: TABS.some(t => t[0] === h[0]) ? h[0] : "day", arg: h[1] || "" };
}
function drawTabs(active) {
  const top = TABS.map(([k, l]) => `<a href="#/${k}" ${k === active ? 'aria-current="page"' : ""}>${l}</a>`).join("");
  const bot = TABS.map(([k, l, ic]) => `<a href="#/${k}" ${k === active ? 'aria-current="page"' : ""}><span class="ic">${ic}</span>${l}</a>`).join("");
  $("#tabs-top").innerHTML = top; $("#tabs-bottom").innerHTML = bot;
}
let viewToken = 0;
async function render() {
  if (!getToken()) return showLogin();
  showApp();
  const { name, arg } = route();
  drawTabs(name);
  const my = ++viewToken, main = $("#main");
  main.innerHTML = '<div class="stack"><div class="skel"></div><div class="skel"></div></div>';
  try {
    if (!S.imports.length || name === "import") S.imports = await api("/imports");
    const html = await ({ day: viewDay, period: viewPeriod, trades: viewTrades, import: viewImport, attention: viewAttention }[name])(arg, main);
    if (my !== viewToken) return;
    if (typeof html === "string") main.innerHTML = html;
  } catch (e) {
    if (my !== viewToken || e.message === "Signed out") return;
    main.innerHTML = `<div class="err"><span>${esc(e.message)}</span><button class="btn" id="retry">Retry</button></div>`;
    $("#retry").onclick = render;
  }
  if (my === viewToken) window.scrollTo(0, 0);
}

/* ---------- shared UI pieces ---------- */
function tiles(s, main = true) {
  const t = (k, v, c = "", m = false) => `<div class="tile ${m ? "main" : ""}"><div class="k">${k}</div><div class="v ${c}">${v}</div></div>`;
  return `<div class="tiles">
    ${t("Net P&L", money(s.net, true), cls(s.net), main)}
    ${t("Gross P&L", money(s.gross, true), cls(s.gross))}
    ${t("Fees", money(s.fees))}
    ${t("Premium collected", money(s.premium_collected))}
    ${Number(s.premium_paid) ? t("Premium paid", money(s.premium_paid)) : ""}
    ${t("Trades", `${s.trades} <span class="mute" style="font-size:13px;font-weight:500">(${s.wins}W / ${s.losses}L)</span>`)}
    ${t("Win rate", pct(s.win_rate))}
    ${t("Return on risk", pct(s.return_on_risk, true), cls(s.return_on_risk))}
  </div>`;
}

/** Bars = net per item, line = running total. items: [{label,net,cum}] (strings from the API). */
function chart(items, { title = "" } = {}) {
  if (!items.length) return "";
  const W = Math.max(320, Math.min(720, Math.round((document.getElementById("main").clientWidth || 720) - 30))), H = W < 500 ? 210 : 230, L = 50, R = 8, T = 12, B = 30, n = items.length;
  const nets = items.map(i => Number(i.net)), cums = items.map(i => Number(i.cum));
  let lo = Math.min(0, ...nets, ...cums), hi = Math.max(0, ...nets, ...cums);
  if (hi === lo) { hi += 1; lo -= 1; }
  const pad = (hi - lo) * 0.08; hi += pad; if (lo < 0) lo -= pad;
  const x = i => L + (i + 0.5) * (W - L - R) / n, y = v => T + (hi - v) * (H - T - B) / (hi - lo);
  const bw = Math.max(2, Math.min(46, (W - L - R) / n * 0.62));
  const step = Math.ceil(n / (W < 500 ? 6 : 12));
  const bars = items.map((it, i) => {
    const v = nets[i], y0 = y(0), y1 = y(v);
    return `<rect class="${v < 0 ? "b-neg" : "b-pos"}" x="${(x(i) - bw / 2).toFixed(1)}" y="${Math.min(y0, y1).toFixed(1)}" width="${bw.toFixed(1)}" height="${Math.max(1, Math.abs(y1 - y0)).toFixed(1)}" rx="2"><title>${esc(it.label)}: net ${esc(money(it.net, true))}, running ${esc(money(it.cum, true))}</title></rect>`;
  }).join("");
  const pts = cums.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const labels = items.map((it, i) => i % step ? "" : `<text x="${x(i).toFixed(1)}" y="${H - 10}" text-anchor="middle">${esc(it.label)}</text>`).join("");
  const ticks = [lo, 0, hi].map(v => `<text x="${L - 6}" y="${(y(v) + 3).toFixed(1)}" text-anchor="end">${short(v)}</text>`).join("");
  return `<div class="card chart"><div class="row between"><h3>${esc(title)}</h3></div>
    <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(title)}: bars show net P&L, line shows running total">
      <line class="ax" x1="${L}" x2="${W - R}" y1="${T}" y2="${T}"/><line class="zero" x1="${L}" x2="${W - R}" y1="${y(0).toFixed(1)}" y2="${y(0).toFixed(1)}"/>
      ${bars}<polyline class="cum" points="${pts}"/>${n <= 40 ? cums.map((v, i) => `<circle class="dot" cx="${x(i).toFixed(1)}" cy="${y(v).toFixed(1)}" r="2.5"/>`).join("") : ""}
      ${ticks}${labels}</svg>
    <div class="legend"><span><i style="background:var(--bar-pos)"></i>Net gain</span><span><i style="background:var(--bar-neg)"></i>Net loss</span><span><i style="background:var(--line-cum)"></i>Running total</span></div></div>`;
}

/** Day screen: one row per trade (in close order) with a diverging bar: solid = result, hatched = fees. */
const clock = t => { if (!t) return ""; let [h, m] = t.split(":").map(Number); const ap = h >= 12 ? "p" : "a"; h = h % 12 || 12; return `${h}:${String(m).padStart(2, "0")}${ap}`; };
function ladder(trades, series, summary) {
  const byKey = Object.fromEntries(trades.map(t => [t.key, t]));
  const rows = series.map(s => ({ t: byKey[s.key], cum: s.cumulative })).filter(r => r.t);
  if (!rows.length) return "";
  const ext = rows.map(({ t }) => { const n = Number(t.net), g = Number(t.gross); return [Math.min(0, n, g), Math.max(0, n, g)]; });
  const lo = Math.min(0, ...ext.map(e => e[0])), hi = Math.max(0, ...ext.map(e => e[1])), span = (hi - lo) || 1;
  const pos = v => ((v - lo) / span * 100);
  const z = pos(0);
  const seg = (cl, a, b) => b - a < 1e-9 ? "" : `<i class="lb ${cl}" style="left:${pos(a).toFixed(2)}%;width:${Math.max(0.8, pos(b) - pos(a)).toFixed(2)}%"></i>`;
  const html = rows.map(({ t }) => {
    const n = Number(t.net), g = Number(t.gross), c = n < 0 ? "neg" : "pos";
    let bar;
    if (n !== 0 && Math.sign(n) === Math.sign(g)) {
      const near = n > 0 ? Math.min(n, g) : Math.max(n, g), far = n > 0 ? Math.max(n, g) : Math.min(n, g);
      bar = n > 0 ? seg(c, 0, near) + seg(c + " fee", near, far) : seg(c, near, 0) + seg(c + " fee", far, near);
    } else bar = n > 0 ? seg(c, 0, n) : seg(c, n, 0);
    const when = t.close_time ? `${clock(t.open_time)}–${clock(t.close_time)}` : `${clock(t.open_time)} · ${esc(t.status === "expired" ? "expired" : t.status.replace("_", " "))}`;
    const name = `${t.right === "C" ? "Call" : "Put"} ${t.short_strike}/${t.long_strike} ×${t.contracts}`;
    return `<button class="lrow" data-goto="${esc(t.key)}" title="Jump to this trade">
      <span class="lhead"><span class="lt">${esc(when)}</span><b>${esc(name)}</b><span class="lv ${cls(t.net)}">${money(t.net, true)}</span></span>
      <span class="ltrack"><i class="zl" style="left:${z.toFixed(2)}%"></i>${bar}</span>
      <span class="lsub">gross ${money(t.gross, true)} · fees ${money(t.fees)}</span></button>`;
  }).join("");
  let spark = "";
  if (rows.length >= 1) {
    const mins = t => { if (!t) return null; const [h, m] = t.split(":").map(Number); return h * 60 + m; };
    const pts = rows.map(r => ({ x: mins(r.t.close_time) ?? 16 * 60, cum: Number(r.cum), net: Number(r.t.net), exp: !r.t.close_time }));
    const x0 = Math.min(...rows.map(r => mins(r.t.open_time) ?? 9 * 60 + 30)), x1 = Math.max(...pts.map(p => p.x));
    const W = Math.max(300, Math.min(700, Math.round((document.getElementById("main").clientWidth || 700) - 60))), H = 150, L = 46, R = 14, T = 20, B = 24;
    const xs = (x1 - x0) || 1, X = m => L + (m - x0) / xs * (W - L - R);
    const vals = pts.map(p => p.cum), lo = Math.min(0, ...vals), hi = Math.max(0, ...vals), sp = (hi - lo) || 1, Y = v => T + (hi - v) / sp * (H - T - B);
    let d = `M${X(x0).toFixed(1)},${Y(0).toFixed(1)}`, prev = 0;
    pts.forEach(p => { d += ` H${X(p.x).toFixed(1)} V${Y(p.cum).toFixed(1)}`; prev = p.cum; });
    d += ` H${(W - R).toFixed(1)}`;
    const ticks = []; for (let m = Math.ceil(x0 / 60) * 60; m <= x1; m += 60) ticks.push(m);
    const lab = (v) => (v < 0 ? "−$" : "+$") + Math.abs(v).toLocaleString("en-US", { maximumFractionDigits: 0 });
    spark = `<div class="spark"><div class="row between"><h3>Running total through the day</h3><span class="mute">after each trade closes</span></div>
      <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Running total through the day, ending ${esc(money(summary.net, true))}">
      <line class="zero" x1="${L}" x2="${W - R}" y1="${Y(0).toFixed(1)}" y2="${Y(0).toFixed(1)}"/><text x="${L - 6}" y="${(Y(0) + 3).toFixed(1)}" text-anchor="end">$0</text>
      ${ticks.map(m => `<line class="ax" x1="${X(m).toFixed(1)}" x2="${X(m).toFixed(1)}" y1="${H - B}" y2="${H - B + 4}"/><text x="${X(m).toFixed(1)}" y="${H - 6}" text-anchor="middle">${clock(String(Math.floor(m / 60)) + ":00")}</text>`).join("")}
      <path class="cum" d="${d}"/>
      ${pts.map(p => `<circle class="dot" cx="${X(p.x).toFixed(1)}" cy="${Y(p.cum).toFixed(1)}" r="4"><title>${esc(money(p.cum, true))}${p.exp ? " (expired)" : ""}</title></circle>
        <text class="${p.net < 0 ? "loss" : "win"}" x="${Math.min(W - R - 18, X(p.x)).toFixed(1)}" y="${(p.net < 0 ? Y(p.cum) + 15 : Y(p.cum) - 8).toFixed(1)}" text-anchor="middle">${lab(p.cum)}</text>`).join("")}</svg></div>`;
  }
  return `<div class="card ladder"><div class="row between"><h3>Trades, in order of close</h3><span class="mute">Day net <b class="${cls(summary.net)}">${money(summary.net, true)}</b></span></div>
    <div class="lrows">${html}</div>${spark}
    <div class="legend"><span><i class="sw"></i>Result</span><span><i class="sw hatch"></i>Fees</span></div></div>`;
}

const MARKETS = ["", "Trending up", "Trending down", "Range-bound", "High volatility / event day", "Other"];
function tradeCard(t, maxAbs) {
  const fb = t.fee_breakdown || {}, win = sign(t.net) >= 0;
  const w = maxAbs ? Math.min(100, Math.abs(Number(t.net)) / maxAbs * 100) : 0;
  const note = t.note || { market_condition: "", learnings: "", tags: [] };
  const flags = [...(t.status && t.status !== "closed" ? [t.status.replace("_", " ")] : []), ...(t.flags || []).map(f => f.replace(/_/g, " "))];
  const cell = (k, v) => `<div><div class="k">${k}</div><div class="v">${v}</div></div>`;
  const fee = (k, v) => `<div><span>${k}</span><span>${money(v)}</span></div>`;
  return `<article class="card trade" data-key="${esc(t.key)}">
    <div class="row between"><div><h2>${esc(tradeTitle(t))}</h2>
      <div class="row" style="margin-top:4px"><span class="pill ${t.result === "win" ? "win" : t.result === "loss" ? "loss" : ""}">${esc(t.result)}</span>${flags.map(f => `<span class="pill">${esc(f)}</span>`).join("")}</div></div>
      <div class="net ${cls(t.net)}">${money(t.net, true)}</div></div>
    <div class="kv">
      ${cell("Entry avg", nil(t.entry_avg) ? "–" : "$" + esc(t.entry_avg))}${cell("Exit avg", nil(t.exit_avg) ? "–" : "$" + esc(t.exit_avg))}
      ${cell("Gross", `<span class="${cls(t.gross)}">${money(t.gross, true)}</span>`)}
      ${cell("Premium collected", money(t.premium_collected))}${Number(t.premium_paid) ? cell("Premium paid", money(t.premium_paid)) : ""}
      ${cell("Max risk", money(t.max_risk))}${cell("Return on risk", `<span class="${cls(t.return_on_risk)}">${pct(t.return_on_risk, true)}</span>`)}
    </div>
    <h3 style="margin-top:6px">Fees${t.fee_source && t.fee_source !== "actual" ? ` <span class="pill">${esc(t.fee_source)}</span>` : ""}</h3>
    <div class="fees">${fee("Commission", fb.commission)}${fee("CAT fee", fb.cat_fee)}${fee("Regulatory & clearing", fb.regulatory_clearing_fee)}${fee("FINRA", fb.finra_fee)}${fee("SEC", fb.sec_fee)}
      <div class="tot"><span>Total fees</span><span>${money(t.fees)}</span></div></div>
    <details><summary>Fills (${(t.legs || []).length})</summary><div class="scroll"><table><thead><tr>
      <th>Time</th><th class="l">Trade #</th><th class="l">Action</th><th>Right</th><th>Strike</th><th>Qty</th><th>Price</th><th>Net amount</th></tr></thead><tbody>
      ${(t.legs || []).map(l => `<tr><td>${esc(l.date.slice(5))} ${esc(l.time)}</td><td class="l">${esc(l.trade_number)}</td><td class="l">${esc(l.side)} to ${esc(l.action)}</td>
        <td>${esc(l.right)}</td><td>${esc(l.strike)}</td><td>${esc(l.quantity)}</td><td>${esc(l.price)}</td><td>${money(l.net_amount)}</td></tr>`).join("")}</tbody></table></div></details>
    <div class="note"><div class="grid">
      <div><label>Market condition</label><select class="n-mc">${MARKETS.map(m => `<option value="${esc(m)}" ${m === note.market_condition ? "selected" : ""}>${m || "— select —"}</option>`).join("")}</select></div>
      <div><label>Tags (comma separated)</label><input class="n-tags" value="${esc((note.tags || []).join(", "))}" style="width:100%"></div></div>
      <label>Learnings</label><textarea class="n-learn" placeholder="What did you learn from this trade?">${esc(note.learnings)}</textarea>
      <div class="saved" aria-live="polite"></div></div>
  </article>`;
}

/* notes: autosave 500 ms after the last change */
document.addEventListener("input", e => {
  const card = e.target.closest(".trade"); if (!card || !e.target.matches(".n-mc,.n-tags,.n-learn")) return;
  clearTimeout(card._t);
  const status = $(".saved", card); status.textContent = "Editing…";
  card._t = setTimeout(async () => {
    const body = { market_condition: $(".n-mc", card).value, learnings: $(".n-learn", card).value,
      tags: $(".n-tags", card).value.split(",").map(s => s.trim()).filter(Boolean) };
    try {
      await api("/notes/" + encodeURIComponent(card.dataset.key), { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      status.textContent = "Saved";
    } catch (err) { status.textContent = "Not saved: " + err.message; }
  }, 500);
});
document.addEventListener("change", e => { if (e.target.matches(".n-mc")) e.target.dispatchEvent(new Event("input", { bubbles: true })); });

/* ---------- Day ---------- */
async function viewDay(arg, main) {
  const dates = S.imports.map(i => i.date).sort();
  const d = /^\d{4}-\d{2}-\d{2}$/.test(arg) ? arg : (dates[dates.length - 1] || new Date().toISOString().slice(0, 10));
  const prev = [...dates].reverse().find(x => x < d), next = dates.find(x => x > d);
  const data = await api(`/day/${d}${scope()}`);
  const trades = data.trades, maxAbs = Math.max(0, ...trades.map(t => Math.abs(Number(t.net))));
  const head = `<div class="page-head"><div class="row">
      <button class="btn" id="prev" ${prev ? "" : "disabled"} aria-label="Previous trading day">‹ Prev</button>
      <input type="date" id="dpick" value="${esc(d)}" aria-label="Date">
      <button class="btn" id="next" ${next ? "" : "disabled"} aria-label="Next trading day">Next ›</button></div>
      <div class="mute">${esc(dlabel(d))}</div></div>`;
  let html = head;
  if (!trades.length) {
    html += `<div class="card empty">No trades on this day${S.und ? "" : " for SPX / SPXW"}.<br><span style="font-size:13px">Import that day's confirmation PDF on the Import tab, or pick another date.</span></div>`;
  } else {
    html += `<div class="stack">${tiles(data.summary)}
      ${ladder(trades, data.series, data.summary)}
      ${trades.map(t => tradeCard(t, maxAbs)).join("")}
      <div class="card">${exportBar(d, d)}</div></div>`;
  }
  main.innerHTML = html;
  const go = x => { location.hash = "#/day/" + x; };
  $$(".lrow", main).forEach(b => b.onclick = () => { const c = $(`.trade[data-key="${CSS.escape(b.dataset.goto)}"]`, main); if (c) c.scrollIntoView({ behavior: "smooth", block: "start" }); });
  $("#prev").onclick = () => prev && go(prev); $("#next").onclick = () => next && go(next);
  $("#dpick").onchange = e => e.target.value && go(e.target.value);
}

/* ---------- Periods ---------- */
const P = { g: "month", from: "", to: "" };
async function viewPeriod(_, main) {
  const data = await api(`/period${scope({ granularity: P.g, from: P.from, to: P.to })}`);
  const rows = data.rows;
  main.innerHTML = `<div class="page-head"><div class="seg" role="radiogroup" aria-label="Granularity" id="gran">
      ${["day", "week", "month", "year"].map(g => `<button role="radio" data-g="${g}" aria-checked="${g === P.g}">${g[0].toUpperCase() + g.slice(1)}</button>`).join("")}</div>
      <div class="row"><input type="date" id="pf" value="${esc(P.from)}" aria-label="From"><span class="mute">to</span><input type="date" id="pt" value="${esc(P.to)}" aria-label="To">
      <button class="btn" id="pclr">Clear</button></div></div>
    ${rows.length ? `<div class="stack">${tiles(data.total)}
      ${chart(rows.map(r => ({ label: plabel(P.g, r.start), net: r.net, cum: r.cumulative_net })), { title: `Net per ${P.g} and running total` })}
      <div class="card"><div class="scroll"><table><thead><tr><th>${P.g[0].toUpperCase() + P.g.slice(1)}</th><th>Trades</th><th>W / L</th><th>Win rate</th><th>Premium coll.</th><th>Premium paid</th><th>Gross</th><th>Fees</th><th>Net</th><th>Return on risk</th><th>Running net</th></tr></thead><tbody>
      ${[...rows].reverse().map(r => `<tr class="${P.g === "day" ? "click" : ""}" data-start="${esc(r.start)}"><td title="${esc(r.start)}">${esc(plabel(P.g, r.start))}</td><td>${r.trades}</td><td>${r.wins} / ${r.losses}</td><td>${pct(r.win_rate)}</td>
        <td>${money(r.premium_collected)}</td><td>${money(r.premium_paid)}</td><td class="${cls(r.gross)}">${money(r.gross, true)}</td><td>${money(r.fees)}</td>
        <td class="${cls(r.net)}"><b>${money(r.net, true)}</b></td><td class="${cls(r.return_on_risk)}">${pct(r.return_on_risk, true)}</td><td class="${cls(r.cumulative_net)}">${money(r.cumulative_net, true)}</td></tr>`).join("")}
      </tbody></table></div>${P.g === "day" ? '<p class="mute" style="font-size:12px;margin:8px 0 0">Click a day to open it.</p>' : ""}</div>
      <div class="card">${exportBar(P.from, P.to)}</div></div>`
    : '<div class="card empty">No trades in this range.</div>'}`;
  $$("#gran button").forEach(b => b.onclick = () => { P.g = b.dataset.g; render(); });
  $("#pf").onchange = e => { P.from = e.target.value; render(); }; $("#pt").onchange = e => { P.to = e.target.value; render(); };
  $("#pclr").onclick = () => { P.from = P.to = ""; render(); };
  if (P.g === "day") $$("tr.click", main).forEach(tr => tr.onclick = () => { location.hash = "#/day/" + tr.dataset.start; });
}

/* ---------- Trades ---------- */
const F = { from: "", to: "", result: "", tag: "" };
async function viewTrades(_, main) {
  const list = await api(`/trades${scope({ from: F.from, to: F.to, result: F.result, tag: F.tag })}`);
  const rows = [...list].reverse();
  main.innerHTML = `<div class="filters">
      <div><label>From</label><input type="date" id="ff" value="${esc(F.from)}"></div><div><label>To</label><input type="date" id="ft" value="${esc(F.to)}"></div>
      <div><label>Result</label><select id="fr"><option value="">All</option><option value="win" ${F.result === "win" ? "selected" : ""}>Wins</option><option value="loss" ${F.result === "loss" ? "selected" : ""}>Losses</option></select></div>
      <div><label>Tag</label><input id="fg" value="${esc(F.tag)}" placeholder="any"></div>
      <button class="btn" id="fclr">Clear</button><span class="mute grow" style="text-align:right">${list.length} trade${list.length === 1 ? "" : "s"}</span></div>
    ${rows.length ? `<div class="card"><div class="scroll"><table><thead><tr><th>Date</th><th class="l">Trade</th><th>Result</th><th>Premium coll.</th><th>Premium paid</th><th>Gross</th><th>Fees</th><th>Net</th><th>Return on risk</th></tr></thead><tbody>
      ${rows.map(t => `<tr class="click" data-d="${esc(t.date)}"><td>${esc(t.date)}</td><td class="l">${esc(tradeTitle(t))}</td><td class="${t.result === "win" ? "win" : t.result === "loss" ? "loss" : ""}">${esc(t.result)}</td>
        <td>${money(t.premium_collected)}</td><td>${money(t.premium_paid)}</td><td class="${cls(t.gross)}">${money(t.gross, true)}</td><td>${money(t.fees)}</td><td class="${cls(t.net)}"><b>${money(t.net, true)}</b></td><td class="${cls(t.return_on_risk)}">${pct(t.return_on_risk, true)}</td></tr>`).join("")}
      </tbody></table></div></div><div class="card" style="margin-top:12px">${exportBar(F.from, F.to)}</div>` : '<div class="card empty">No trades match.</div>'}`;
  const set = (id, k) => { $(id).onchange = e => { F[k] = e.target.value.trim(); render(); }; };
  set("#ff", "from"); set("#ft", "to"); set("#fr", "result"); set("#fg", "tag");
  $("#fclr").onclick = () => { Object.keys(F).forEach(k => F[k] = ""); render(); };
  $$("tr.click", main).forEach(tr => tr.onclick = () => { location.hash = "#/day/" + tr.dataset.d; });
}

/* ---------- Import ---------- */
async function viewImport(_, main) {
  main.innerHTML = `<div class="stack">
    <label class="drop" id="drop" for="files"><b>Drop confirmation PDFs here</b><br><span style="font-size:13px">or click to choose one or more files. Re-uploading a day is safe.</span>
      <input id="files" type="file" accept="application/pdf,.pdf" multiple class="hide"></label>
    <div id="results"></div>
    <div class="card"><h3 style="margin-bottom:6px">Imported days</h3>${S.imports.length ? `<div class="scroll"><table><thead><tr><th>Day</th><th>Fills</th><th>Pages</th><th>Imported</th></tr></thead><tbody>
      ${S.imports.map(i => `<tr class="click" data-d="${esc(i.date)}"><td>${esc(i.date)}</td><td>${i.fills}</td><td>${i.pages}</td><td>${esc(String(i.imported_at).replace("T", " ").slice(0, 16))}</td></tr>`).join("")}</tbody></table></div>` : '<div class="empty">Nothing imported yet.</div>'}</div></div>`;
  $$("tr.click", main).forEach(tr => tr.onclick = () => { location.hash = "#/day/" + tr.dataset.d; });
  const drop = $("#drop"), input = $("#files");
  const upload = async files => {
    files = [...files].filter(f => /\.pdf$/i.test(f.name) || f.type === "application/pdf");
    if (!files.length) return;
    $("#results").innerHTML = `<div class="card">Importing ${files.length} file${files.length > 1 ? "s" : ""}…</div>`;
    const fd = new FormData(); files.forEach(f => fd.append("files", f));
    try {
      const r = await api("/import", { method: "POST", body: fd });
      S.imports = await api("/imports");
      const label = { imported: "Imported", duplicate: "Already imported", error: "Problem" };
      $("#results").innerHTML = `<div class="card"><h3>Results</h3>${r.results.map(x => `<div class="res"><span class="st ${x.status === "imported" ? "win" : x.status === "error" ? "loss" : "mute"}"><b>${label[x.status] || esc(x.status)}</b></span>
        <span class="grow">${esc(x.file)}<small>${x.status === "error" ? "" : `${x.new_fills ?? 0} new fill${x.new_fills === 1 ? "" : "s"} of ${x.fills ?? 0}`}${(x.errors || []).concat(x.warnings || []).map(m => `<br>${esc(m)}`).join("")}</small></span></div>`).join("")}
        ${S.imports.length ? `<div class="row" style="margin-top:10px"><a class="btn primary" href="#/day/${esc(S.imports[0].date)}" style="text-decoration:none;display:inline-flex;align-items:center">Open latest day</a></div>` : ""}</div>`;
    } catch (e) { $("#results").innerHTML = `<div class="err"><span>${esc(e.message)}</span></div>`; }
  };
  input.onchange = () => { upload(input.files); input.value = ""; };
  ["dragenter", "dragover"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add("over"); }));
  ["dragleave", "drop"].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove("over"); }));
  drop.addEventListener("drop", e => upload(e.dataTransfer.files));
}

/* ---------- Needs attention ---------- */
async function viewAttention(_, main) {
  const a = await api(`/attention${scope()}`);
  const none = !a.trades.length && !a.orphans.length;
  main.innerHTML = `<div class="page-head"><h2>Needs attention</h2></div><div class="stack">
    ${none ? '<div class="card empty">Nothing needs attention. Every fill is matched to a trade.</div>' : ""}
    ${a.orphans.length ? `<div class="card"><h3>Fills with no matching entry (${a.orphans.length})</h3>
      ${a.orphans.map(o => `<div class="res"><span class="st"><b>${esc(o.date)}</b></span><span class="grow">${esc(o.reason)}<small>${(o.fills || []).map(esc).join("<br>")}</small></span></div>`).join("")}</div>` : ""}
    ${a.trades.length ? `<div class="card"><h3>Trades to review (${a.trades.length})</h3><div class="scroll"><table><thead><tr><th>Date</th><th class="l">Trade</th><th class="l">Status</th><th>Net</th></tr></thead><tbody>
      ${a.trades.map(t => `<tr class="click" data-d="${esc(t.date)}"><td>${esc(t.date)}</td><td class="l">${esc(tradeTitle(t))}</td><td class="l">${esc((t.status || "").replace("_", " "))} ${(t.flags || []).map(f => `<span class="pill">${esc(f.replace(/_/g, " "))}</span>`).join(" ")}</td><td>${money(t.net, true)}</td></tr>`).join("")}</tbody></table></div></div>` : ""}
    <p class="mute" style="font-size:13px">Opening fills may be missing because that day's confirmation hasn't been imported yet.</p></div>`;
  $$("tr.click", main).forEach(tr => tr.onclick = () => { location.hash = "#/day/" + tr.dataset.d; });
}

/* ---------- wiring ---------- */
document.addEventListener("click", e => {
  const b = e.target.closest("[data-export] [data-kind]"); if (!b) return;
  const bar = b.closest("[data-export]"); download(b.dataset.kind, bar.dataset.from, bar.dataset.to);
});
$("#und").addEventListener("click", e => {
  const b = e.target.closest("button"); if (!b) return;
  S.und = b.dataset.v; $$("#und button").forEach(x => x.setAttribute("aria-checked", x === b)); render();
});
$("#logout").onclick = async () => { try { await api("/logout", { method: "POST" }); } catch { /* ignore */ } setToken(null); S.imports = []; showLogin(); };
$("#loginform").addEventListener("submit", async e => {
  e.preventDefault(); const btn = $("#loginbtn"), err = $("#loginerr"); btn.disabled = true; err.textContent = "";
  try {
    const r = await api("/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ password: $("#pw").value }) });
    setToken(r.token); $("#pw").value = ""; S.imports = []; render();
  } catch (x) { err.textContent = x.message; } finally { btn.disabled = false; }
});
window.addEventListener("hashchange", render);
render();
