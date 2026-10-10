"""Load statement PDFs: store the original, parse it, write its statements.

Every PDF is identified by its content hash, so the same file arriving from
several places is stored once. Every statement is identified by its period
and figures, so the same statement inside different PDFs (a repeated copy, a
forwarded email) is loaded once.
"""
from __future__ import annotations

import hashlib
import logging
import tempfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import select

from . import db
from .parsing import PARSER_VERSION, ParseError, parse_text
from .parsing.model import ParsedStatement
from .parsing.text import pdf_to_text
from .portfolios import portfolio_for, property_key
from .storage import sha256, store

log = logging.getLogger(__name__)


def statement_fingerprint(st: ParsedStatement, portfolio: Optional[str]) -> str:
    parts = [st.format, str(portfolio), st.period_start.isoformat(), st.period_end.isoformat(),
             str(st.previous_balance), str(st.income), str(st.expenses), str(st.mgmt_fees),
             str(st.draws), str(st.ending_balance)]
    parts += sorted(f"{property_key(p.address)}:{len(p.lines)}" for p in st.properties)
    return hashlib.sha256('|'.join(parts).encode()).hexdigest()


def line_fingerprint(pkey: str, line, occurrence: int) -> str:
    raw = '|'.join([pkey, line.section, line.category, line.txn_type, line.date.isoformat(),
                    line.name, str(line.amount), str(occurrence)])
    return hashlib.sha256(raw.encode()).hexdigest()


def ingest_pdf_bytes(data: bytes, filename: str, source: str, source_ref: str = '',
                     received_at: Optional[datetime] = None, portfolio_hint: Optional[str] = None) -> db.Document:
    digest = sha256(data)
    with db.session() as s:
        existing = s.scalar(select(db.Document).where(db.Document.sha256 == digest))
        if existing is not None:
            return existing
        store().put(digest, data)
        doc = db.Document(sha256=digest, filename=filename, source=source, source_ref=source_ref,
                          received_at=received_at, size=len(data), status='error', parser_version=PARSER_VERSION)
        s.add(doc)
        s.flush()
        try:
            with tempfile.NamedTemporaryFile(suffix='.pdf') as tmp:
                tmp.write(data)
                tmp.flush()
                text = pdf_to_text(tmp.name)
            _parse_into(s, doc, text, portfolio_hint)
        except ParseError as e:
            doc.status, doc.problems = 'error', str(e)
        except Exception as e:  # keep the document; the error is visible in the app
            log.exception("Failed to parse %s", filename)
            doc.status, doc.problems = 'error', f"{type(e).__name__}: {e}"
        s.commit()
        return doc


def ingest_text(text: str, filename: str, source: str = 'test', portfolio_hint: Optional[str] = None) -> db.Document:
    """Load statement text that has already been extracted (tests, re-parsing)."""
    digest = sha256(text.encode())
    with db.session() as s:
        existing = s.scalar(select(db.Document).where(db.Document.sha256 == digest))
        if existing is not None:
            return existing
        doc = db.Document(sha256=digest, filename=filename, source=source, size=len(text), status='error',
                          parser_version=PARSER_VERSION)
        s.add(doc)
        s.flush()
        _parse_into(s, doc, text, portfolio_hint)
        s.commit()
        return doc


def _parse_into(s, doc: db.Document, text: str, portfolio_hint: Optional[str]) -> None:
    fmt, statements = parse_text(text)
    doc.format = fmt
    _load_statements(s, doc, statements, portfolio_hint)


def _load_statements(s, doc: db.Document, statements, portfolio_hint: Optional[str]) -> None:
    if doc.format in ('investor', 'tax_form', 'unknown'):
        doc.status = 'unsupported'
        return
    if not statements:
        doc.status, doc.problems = 'error', 'no statements found'
        return
    loaded, problems = 0, []
    for st in statements:
        if st.is_empty:
            continue
        keys = [property_key(p.address) for p in st.properties]
        portfolio = portfolio_for(keys, st.recipient) or portfolio_hint
        fp = statement_fingerprint(st, portfolio)
        if s.scalar(select(db.Statement.id).where(db.Statement.fingerprint == fp)) is not None:
            continue
        row = db.Statement(
            document_id=doc.id, fingerprint=fp, portfolio=portfolio, recipient=st.recipient, format=st.format,
            period_start=st.period_start, period_end=st.period_end, generated_at=st.generated_at,
            previous_balance=st.previous_balance, income=st.income, expenses=st.expenses,
            mgmt_fees=st.mgmt_fees, assets=st.assets, contributions=st.contributions, draws=st.draws,
            ending_balance=st.ending_balance, unpaid_bills=st.unpaid_bills,
            reconciled=st.reconciled, problems='\n'.join(st.problems) or None)
        s.add(row)
        s.flush()
        for p in st.properties:
            pkey = property_key(p.address)
            if s.get(db.Property, pkey) is None:
                s.add(db.Property(key=pkey, address=_display_address(p.address)))
                s.flush()
            unit = ' '.join(p.address.split())
            lease = st.tenants_by_unit.get(unit)
            row.properties.append(db.StatementProperty(
                property_key=pkey, address=p.address, current_rent=p.current_rent, deposit=p.deposit,
                total_income=p.total_income, total_expenses=p.total_expenses,
                lease_name=lease[0] if lease else None, lease_start=st.lease_starts.get(unit)))
            seen = Counter()
            for line in p.lines:
                base = (line.section, line.category, line.txn_type, line.date, line.name, line.amount)
                occurrence = seen[base]
                seen[base] += 1
                s.add(db.LedgerLine(
                    statement_id=row.id, portfolio=portfolio, property_key=pkey, section=line.section,
                    category=line.category, txn_type=line.txn_type, date=line.date, name=line.name,
                    tenant_key=line.tenant_key, comment=line.comment, amount=line.amount,
                    fingerprint=line_fingerprint(pkey, line, occurrence)))
        for pay in st.owner_payments:
            s.add(db.OwnerPayment(statement_id=row.id, portfolio=portfolio, date=pay.date, amount=pay.amount))
        loaded += 1
        problems += st.problems
        if portfolio is None:
            problems.append(f"could not tell which portfolio the {st.period_start}..{st.period_end} statement belongs to")
    if loaded == 0:
        all_empty = all(st.is_empty for st in statements)
        doc.status = 'empty' if all_empty else 'duplicate'
    else:
        doc.status = 'unreconciled' if problems else 'parsed'
    doc.problems = '\n'.join(problems) or None


def _display_address(raw: str) -> str:
    """'Ladue3403' -> 'Ladue 3403' style cleanup; detail statements already read '3403 Ladue St'."""
    import re
    m = re.match(r'^([A-Za-z.]+)\s?(\d+)$', raw.strip())
    if m:
        return f"{m.group(2)} {m.group(1)}"
    return raw.strip()


def ingest_folder(path: str | Path, source: str = 'folder') -> Counter:
    counts = Counter()
    for pdf in sorted(Path(path).rglob('*.pdf')):
        doc = ingest_pdf_bytes(pdf.read_bytes(), pdf.name, source, source_ref=str(pdf))
        counts[doc.status] += 1
    return counts
