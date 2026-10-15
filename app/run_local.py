"""One-command local run:  python -m app.run_local [--load FOLDER_OF_PDFS] [--port 8000] [--host 127.0.0.1]

First run asks you to choose a password and saves the settings to a local `.env` file (not committed to git).
Data is stored in ./dailyoptionassess.db (SQLite). Use --host 0.0.0.0 to open it from your phone on the same Wi-Fi.
"""
from __future__ import annotations

import argparse
import getpass
import os
import secrets
import shutil
import socket
import sys
import traceback
import webbrowser
from pathlib import Path

ENV = Path(".env")


def _read_env() -> dict[str, str]:
    out: dict[str, str] = {}
    if ENV.exists():
        for line in ENV.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip().strip("'\"")
    return out


def _setup(env: dict[str, str]) -> dict[str, str]:
    if env.get("APP_PASSWORD_HASH") and env.get("APP_SESSION_SECRET"):
        return env
    import bcrypt
    print("First-time setup: choose a password for the app.")
    print("(Characters are hidden while you type or paste - that is normal. Press Enter when done.)")
    while True:
        pw = getpass.getpass("New password: ")
        if len(pw) >= 6 and pw == getpass.getpass("Repeat: "):
            break
        print("Passwords must match and be at least 6 characters.")
    env["APP_PASSWORD_HASH"] = bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()
    env["APP_SESSION_SECRET"] = secrets.token_hex(32)
    env.setdefault("APP_SECURE_COOKIE", "0")     # plain http on your own computer
    # bcrypt hashes contain "$", so the values are single-quoted for anyone who sources the file in a shell
    ENV.write_text("# Local settings for DailyOptionAssess. Do not commit or share.\n"
                   + "".join(f"{k}='{v}'\n" for k, v in env.items()))
    try:
        ENV.chmod(0o600)
    except OSError:
        pass
    print(f"Saved settings to {ENV.resolve()}")
    return env


def _free_port(host: str, want: int) -> int:
    """Return `want` if it can be bound, otherwise the next free port (Windows dev machines often use 8000)."""
    for port in range(want, want + 30):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((host, port))
                return port
            except OSError:
                print(f"Port {port} is already in use, trying the next one...", flush=True)
    raise SystemExit(f"No free port found between {want} and {want + 29}. Close other programs or pass --port.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--load", metavar="FOLDER", help="import every confirmation PDF in this folder first")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    print(f"DailyOptionAssess starting (Python {sys.version.split()[0]}) in {Path.cwd()}", flush=True)
    if not shutil.which("pdftotext"):
        print("\nWARNING: 'pdftotext' was not found. The app will open, but importing PDFs will fail until it is installed:\n"
              "  Windows: install poppler (e.g. 'winget install oschwartz10612.Poppler' or 'scoop install poppler'), then reopen the terminal\n"
              "  macOS:   brew install poppler\n  Linux:   sudo apt install poppler-utils\n", flush=True)

    env = _setup(_read_env())
    for k, v in env.items():
        os.environ.setdefault(k, v)

    if a.load:
        from app import service
        from app.models import init_db
        init_db()
        folder = Path(a.load).expanduser()
        if not folder.is_dir():
            raise SystemExit(f"--load folder not found: {folder}\nUse the real path to your confirmation PDFs, or leave --load out and import from the Import tab.")
        paths = sorted(folder.glob("*.pdf"))
        counts: dict[str, int] = {}
        for p in paths:
            r = service.import_pdf(p.read_bytes(), p.name)
            counts[r["status"]] = counts.get(r["status"], 0) + 1
            if r["status"] == "error":
                print("ERROR", p.name, r["errors"])
        print(f"Loaded {len(paths)} files: {counts}", flush=True)

    import uvicorn
    port = _free_port(a.host, a.port)
    url = f"http://{'localhost' if a.host in ('127.0.0.1', '0.0.0.0') else a.host}:{port}/"
    print(f"\nOpen {url}   (Ctrl+C to stop)\n", flush=True)
    if not a.no_browser:
        webbrowser.open(url)
    try:
        uvicorn.run("app.main:app", host=a.host, port=port, log_level="info")
    except KeyboardInterrupt:
        pass
    except BaseException:
        print("\nThe server stopped because of this error:\n", flush=True)
        traceback.print_exc()
        raise SystemExit(1)
    print("\nServer stopped.", flush=True)


if __name__ == "__main__":
    main()
