"""HTTP API. One user, one password, a signed session cookie."""
from __future__ import annotations

import hmac
import time
from datetime import date
from pathlib import Path

import bcrypt
from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from itsdangerous import BadSignature, SignatureExpired, TimestampSigner
from pydantic import BaseModel

from . import config, service
from .models import init_db

app = FastAPI(title="DailyOptionAssess", docs_url=None, redoc_url=None, openapi_url=None)
if config.CORS_ORIGINS:      # a separately hosted front end (Lovable) calls this API from another origin
    app.add_middleware(CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_methods=["GET", "POST", "PUT"],
                       allow_headers=["Authorization", "Content-Type"], max_age=600)
STATIC = Path(__file__).parent / "static"
COOKIE = "doa_session"
_fails: dict[str, list[float]] = {}


@app.on_event("startup")
def _startup():
    init_db()
    if not config.SESSION_SECRET or not config.PASSWORD_HASH:
        print("WARNING: APP_SESSION_SECRET / APP_PASSWORD_HASH not set - login is disabled")


def _signer() -> TimestampSigner:
    return TimestampSigner(config.SESSION_SECRET, salt="doa-session")


def require_login(request: Request):
    auth = request.headers.get("authorization", "")
    tok = auth[7:] if auth.lower().startswith("bearer ") else request.cookies.get(COOKIE)
    if not tok or not config.SESSION_SECRET:
        raise HTTPException(401, "Login required")
    try:
        _signer().unsign(tok, max_age=config.SESSION_DAYS * 86400)
    except (BadSignature, SignatureExpired):
        raise HTTPException(401, "Login required")


class Login(BaseModel):
    password: str


@app.post("/api/login")
def login(body: Login, request: Request, response: Response):
    ip = request.client.host if request.client else "?"
    now = time.time()
    recent = [t for t in _fails.get(ip, []) if now - t < 900]
    if len(recent) >= 5:
        raise HTTPException(429, "Too many attempts. Try again in 15 minutes.")
    ok = bool(config.PASSWORD_HASH and config.SESSION_SECRET) and bcrypt.checkpw(
        body.password.encode(), config.PASSWORD_HASH.encode())
    if not ok:
        _fails[ip] = recent + [now]
        raise HTTPException(401, "Wrong password")
    _fails.pop(ip, None)
    token = _signer().sign("ok").decode()
    response.set_cookie(COOKIE, token, httponly=True, samesite="lax",
                        secure=config.SECURE_COOKIE, max_age=config.SESSION_DAYS * 86400)
    # The token is also returned for a separately hosted front end, which sends it as
    # "Authorization: Bearer <token>" (third-party cookies are unreliable across domains).
    return {"ok": True, "token": token, "expires_in_days": config.SESSION_DAYS}


@app.post("/api/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE)
    return {"ok": True}


@app.get("/api/me", dependencies=[Depends(require_login)])
def me():
    return {"ok": True, "default_underlyings": list(config.DEFAULT_UNDERLYINGS)}


@app.get("/api/health")
def health():
    return {"ok": True}


@app.post("/api/import", dependencies=[Depends(require_login)])
async def import_files(files: list[UploadFile] = File(...)):
    out = []
    for f in files:
        data = await f.read()
        if len(data) > config.MAX_UPLOAD_MB * 1024 * 1024:
            out.append({"file": f.filename, "status": "error", "errors": ["File too large"]})
            continue
        if not data.startswith(b"%PDF"):
            out.append({"file": f.filename, "status": "error", "errors": ["Not a PDF"]})
            continue
        out.append(service.import_pdf(data, f.filename or "upload.pdf"))
    return {"results": out}


@app.get("/api/imports", dependencies=[Depends(require_login)])
def imports():
    return service.imports_list()


@app.get("/api/day/{d}", dependencies=[Depends(require_login)])
def day(d: date, underlyings: str | None = None):
    return service.day_view(d, underlyings)


@app.get("/api/period", dependencies=[Depends(require_login)])
def period(granularity: str = Query("month", pattern="^(day|week|month|year)$"),
           frm: date | None = Query(None, alias="from"), to: date | None = None,
           underlyings: str | None = None):
    return service.period_view(granularity, frm, to, underlyings)


@app.get("/api/trades", dependencies=[Depends(require_login)])
def trades(frm: date | None = Query(None, alias="from"), to: date | None = None,
           underlyings: str | None = None, result: str | None = None,
           strategy: str | None = None, tag: str | None = None):
    _, _, _, notes = service._load()
    nd = service._notes_for(notes)
    rows = [service.trade_dict(t, nd) for t in service.select_trades(frm, to, underlyings)]
    if result:
        rows = [r for r in rows if r["result"] == result]
    if strategy:
        rows = [r for r in rows if r["strategy"] == strategy]
    if tag:
        rows = [r for r in rows if tag in r["note"]["tags"]]
    return rows


@app.get("/api/attention", dependencies=[Depends(require_login)])
def attention(underlyings: str | None = None):
    return service.attention(underlyings)


class Note(BaseModel):
    market_condition: str = ""
    learnings: str = ""
    tags: list[str] = []


@app.put("/api/notes/{key}", dependencies=[Depends(require_login)])
def note(key: str, body: Note):
    if len(key) > 40 or ":" not in key:
        raise HTTPException(400, "Bad trade key")
    return service.save_note(key, body.market_condition, body.learnings, body.tags)


@app.get("/api/export/{kind}.csv", dependencies=[Depends(require_login)])
def export(kind: str, frm: date | None = Query(None, alias="from"), to: date | None = None,
           underlyings: str | None = None):
    fn = {"trades": service.export_trades, "fills": service.export_fills,
          "daily": service.export_daily}.get(kind)
    if not fn:
        raise HTTPException(404, "Unknown export")
    return PlainTextResponse(fn(frm, to, underlyings), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{kind}.csv"'})


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")
