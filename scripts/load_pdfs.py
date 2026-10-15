"""Load a folder of confirmation PDFs into the app database: python -m scripts.load_pdfs <folder>"""
import sys
from pathlib import Path

from app import service
from app.models import init_db

init_db()
paths = sorted(Path(sys.argv[1]).glob("*.pdf"))
counts = {}
for p in paths:
    r = service.import_pdf(p.read_bytes(), p.name)
    counts[r["status"]] = counts.get(r["status"], 0) + 1
    if r["status"] == "error":
        print("ERROR", p.name, r["errors"])
print(len(paths), "files:", counts)
