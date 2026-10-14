"""Parse a TradeStation confirmation PDF into fills with itemized fees.

Only extracted fills are kept. Name and address are never read into the result,
and the account number is reduced to its last four digits.
"""
from __future__ import annotations

import hashlib
import re
import subprocess
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path

D = Decimal
MONEY = r"([\d,]+\.\d+)"

FILL_RE = re.compile(
    r"^(?P<td>\d\d/\d\d/\d{4})\s+(?P<sd>\d\d/\d\d/\d{4})\s+(?P<side>Bought|Sold)\s+.*?\s+"
    r"(?P<und>[A-Z]+)\s+(?P<exp>\d{6})(?P<right>[CP])(?P<strike>\d+(?:\.\d+)?)\s+"
    r"(?P<qty>\d+)\s+(?P<price>\d+(?:\.\d+)?)\s+Principal\s+(?P<principal>[\d,]+\.\d+)\s+"
    r"\w+\s+\d+\s+(?P<tn>\w+)\s*$"
)
FEE_PATTERNS = {
    "commission": re.compile(r"Commission\s+" + MONEY),
    "cat_fee": re.compile(r"CAT Fee\s+" + MONEY),
    # Labelled "Options Regulatory Fee" before October 2026, "... & Clearing Fee" after.
    "regulatory_clearing_fee": re.compile(r"Options Regulatory(?: & Clearing)? Fee\s+" + MONEY),
    "finra_fee": re.compile(r"FINRA Trade Activity Fee\s+" + MONEY),
    "sec_fee": re.compile(r"SEC Transaction Fee\s+" + MONEY),
}
NET_RE = re.compile(r"NET AMOUNT\s+" + MONEY)
EXEC_RE = re.compile(r"Execution Time\s+(\d\d:\d\d:\d\d)")
OPENCLOSE_RE = re.compile(r"\b(OPENING|CLOSING) CONTRACT\b")
SETTLE_RE = re.compile(r"\b(ASSIGNMENT|EXERCISE) OF OPTION\b")
PAGE_RE = re.compile(r"Page\s+(\d+)\s+of\s+(\d+)")
PROC_DATE_RE = re.compile(r"Processing Date\s+(\d{1,2}/\d{1,2}/\d{4})")
ACCT_RE = re.compile(r"Account Number\s+(\d{4,})")


def money(s: str) -> Decimal:
    return D(s.replace(",", ""))


def mdy(s: str) -> date:
    return datetime.strptime(s, "%m/%d/%Y").date()


@dataclass
class Fill:
    trade_number: str
    trade_date: date
    exec_time: time
    side: str  # "Bought" | "Sold"
    open_close: str  # "OPEN" | "CLOSE"
    is_settlement: bool  # assignment / exercise at expiry
    underlying: str  # e.g. "SPXW"
    expiry: date
    right: str  # "C" | "P"
    strike: Decimal
    quantity: int
    price: Decimal
    principal: Decimal
    fees: dict
    net_amount: Decimal

    @property
    def total_fees(self) -> Decimal:
        return sum(self.fees.values(), D("0"))

    @property
    def signed_cash(self) -> Decimal:
        """Cash effect before fees: positive when sold, negative when bought."""
        return self.principal if self.side == "Sold" else -self.principal


@dataclass
class ParsedConfirmation:
    source_name: str
    file_hash: str
    processing_date: date | None
    account_last4: str | None
    page_count: int | None
    physical_pages: int
    fills: list[Fill] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def extract_text(pdf_path: Path) -> str:
    out = subprocess.run(
        ["pdftotext", "-layout", str(pdf_path), "-"],
        check=True, capture_output=True, text=True,
    )
    return out.stdout


def parse_confirmation(pdf_path: str | Path) -> ParsedConfirmation:
    pdf_path = Path(pdf_path)
    file_hash = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
    text = extract_text(pdf_path)
    pages = text.split("\f")
    if pages and not pages[-1].strip():
        pages = pages[:-1]
    lines = text.splitlines()

    m = PROC_DATE_RE.search(text)
    proc_date = mdy(m.group(1)) if m else None
    m = ACCT_RE.search(text)
    last4 = m.group(1)[-4:] if m else None
    header_pages = {int(a) for a, _ in PAGE_RE.findall(text)}
    declared = {int(b) for _, b in PAGE_RE.findall(text)}
    page_count = max(declared) if declared else None

    result = ParsedConfirmation(
        source_name=pdf_path.name, file_hash=file_hash, processing_date=proc_date,
        account_last4=last4, page_count=page_count, physical_pages=len(pages),
    )

    # Page check: every "Page X of N" header from 1..N-1 must be present, and the PDF must
    # physically have N pages (the last one is boilerplate). A missing page could hide fills,
    # so this must pass before an unmatched leg may be treated as expired worthless.
    if page_count is None:
        result.errors.append("No 'Page X of N' header found")
    else:
        if len(declared) != 1:
            result.errors.append(f"Inconsistent page totals in headers: {sorted(declared)}")
        expected = set(range(1, page_count))
        if header_pages != expected:
            result.errors.append(
                f"Page headers found {sorted(header_pages)}, expected {sorted(expected)}"
            )
        if len(pages) != page_count:
            result.errors.append(f"PDF has {len(pages)} pages but headers say {page_count}")

    # Walk the lines: a fill starts at a FILL_RE line and ends at its NET AMOUNT line.
    i = 0
    while i < len(lines):
        fm = FILL_RE.match(lines[i].strip())
        if not fm:
            i += 1
            continue
        block = [lines[i]]
        j = i + 1
        net = None
        while j < len(lines) and not FILL_RE.match(lines[j].strip()):
            block.append(lines[j])
            nm = NET_RE.search(lines[j])
            if nm:
                net = money(nm.group(1))
                break
            j += 1
        if net is None:
            result.errors.append(f"Fill {fm.group('tn')} has no NET AMOUNT line")
            i = j
            continue
        # The ASSIGNMENT/EXERCISE label can print on the line after NET AMOUNT, so look at the
        # next few non-blank lines too (stopping at the next fill).
        k, extra = j + 1, 0
        while k < len(lines) and extra < 3 and not FILL_RE.match(lines[k].strip()):
            if lines[k].strip():
                block.append(lines[k])
                extra += 1
            k += 1
        _finish_fill(result, fm, block, net)
        i = j + 1

    if not result.fills:
        result.errors.append("No fills found")
    seen: set[str] = set()
    for f in result.fills:
        if f.trade_number in seen:
            result.errors.append(f"Duplicate trade number {f.trade_number} in file")
        seen.add(f.trade_number)
    return result


def _finish_fill(result: ParsedConfirmation, start: re.Match, block: list[str], net: Decimal) -> None:
    tn = start.group("tn")
    body = "\n".join(block)

    em = EXEC_RE.search(body)
    oc = OPENCLOSE_RE.search(body)
    if not em:
        result.errors.append(f"Fill {tn}: execution time missing")
    if not oc:
        result.errors.append(f"Fill {tn}: OPENING/CLOSING CONTRACT missing")
    if not em or not oc:
        return

    fees = {}
    for name, rx in FEE_PATTERNS.items():
        fm = rx.search(body)
        if fm:
            fees[name] = money(fm.group(1))

    ys = start.group("exp")
    expiry = date(2000 + int(ys[:2]), int(ys[2:4]), int(ys[4:6]))
    fill = Fill(
        trade_number=tn,
        trade_date=mdy(start.group("td")),
        exec_time=datetime.strptime(em.group(1), "%H:%M:%S").time(),
        side=start.group("side"),
        open_close="OPEN" if oc.group(1) == "OPENING" else "CLOSE",
        is_settlement=bool(SETTLE_RE.search(body)),
        underlying=start.group("und"),
        expiry=expiry,
        right=start.group("right"),
        strike=D(start.group("strike")),
        quantity=int(start.group("qty")),
        price=D(start.group("price")),
        principal=money(start.group("principal")),
        fees=fees,
        net_amount=net,
    )

    # Line check: net = principal - fees when sold, principal + fees when bought.
    fee_total = fill.total_fees
    expected_net = fill.principal - fee_total if fill.side == "Sold" else fill.principal + fee_total
    if expected_net != net:
        result.errors.append(
            f"Fill {tn}: net amount {net} != principal {fill.principal} "
            f"{'-' if fill.side == 'Sold' else '+'} fees {fee_total} (= {expected_net})"
        )
    # Soft check: price x quantity x 100 should match principal (price is shown to 3 decimals).
    approx = fill.price * fill.quantity * 100
    tol = D("0.0005") * fill.quantity * 100 + D("0.005")
    if abs(approx - fill.principal) > tol:
        result.warnings.append(
            f"Fill {tn}: price x qty x 100 = {approx} but principal is {fill.principal}"
        )
    result.fills.append(fill)
