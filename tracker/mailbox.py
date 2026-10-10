"""Read every Mid South email from mascariproperties@gmail.com and label it.

Run daily. Each message is handled once:
- statements (PDF attached)            -> stored and parsed
- "Owner Statement Published" notices  -> recorded; the tracker then expects a statement
- "Pending Deposit" notices            -> recorded as a payout notice
- everything else from Mid South       -> read by Claude for property events
                                          (thefts, vandalism, leases, repairs...)

Labels: RentalTracker/Processed once handled, RentalTracker/NeedsReview
when Claude was unsure or unavailable. A message that fails is left
unlabelled and retried on the next run. Messages are recorded by their
Message-ID, so removing a label to reprocess never duplicates anything.
"""
from __future__ import annotations

import email
import email.utils
import imaplib
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from email.header import decode_header
from typing import List, Optional

from sqlalchemy import select

from . import db, llm
from .ingest import ingest_pdf_bytes
from .portfolios import property_key

log = logging.getLogger(__name__)

PROCESSED = os.getenv('PROCESSED_LABEL', 'RentalTracker/Processed')
NEEDS_REVIEW = os.getenv('REVIEW_LABEL', 'RentalTracker/NeedsReview')
SENDERS = os.getenv('MANAGER_SENDERS', 'midsouthbestrentals.com propertyware.com midsouthhomebuyers.com').split()
SINCE = os.getenv('MAIL_SINCE', '2026/01/01')
RECIPIENT_PORTFOLIO = {
    'torgo': 'torgo', 'dunwich': 'dunwich', 'miskatonic': 'miskatonic', 'dmascari@': 'david',
}


@dataclass
class Message:
    uid: bytes
    message_id: str
    sender: str
    recipients: str
    subject: str
    date: datetime
    body: str
    pdfs: List[tuple] = field(default_factory=list)   # (filename, bytes)


def _decode(value: Optional[str]) -> str:
    if not value:
        return ''
    out = []
    for text, charset in decode_header(value):
        out.append(text.decode(charset or 'utf-8', errors='replace') if isinstance(text, bytes) else text)
    return ''.join(out)


def _quote(text: str) -> str:
    return '"' + text.replace('\\', '\\\\').replace('"', '\\"') + '"'


def _label_query(label: str) -> str:
    return label.lower().replace('/', '-').replace(' ', '-')


class Mailbox:
    def __init__(self):
        self.conn = imaplib.IMAP4_SSL(os.getenv('IMAP_HOST', 'imap.gmail.com'))
        self.conn.login(os.environ['GMAIL_USER'], os.environ['GMAIL_APP_PASSWORD'])
        for label in (PROCESSED, NEEDS_REVIEW):
            try:
                self.conn.create(_quote(label))
            except imaplib.IMAP4.error:
                pass
        typ, data = self.conn.list('""', '*')
        folder = '[Gmail]/All Mail'
        for line in data or []:
            decoded = (line or b'').decode(errors='replace')
            if '\\All' in decoded:
                folder = decoded.rsplit(' "/" ', 1)[-1].strip().strip('"')
        self.conn.select(_quote(folder))

    def unprocessed(self, since: str = SINCE) -> List[Message]:
        senders = ' OR '.join(f'from:{s}' for s in SENDERS)
        query = f"({senders} OR subject:\"Owner Statement\") -label:{_label_query(PROCESSED)} after:{since}"
        typ, data = self.conn.uid('SEARCH', 'X-GM-RAW', _quote(query))
        uids = data[0].split() if data and data[0] else []
        return [self._fetch(uid) for uid in uids]

    def _fetch(self, uid: bytes) -> Message:
        typ, data = self.conn.uid('FETCH', uid, '(RFC822)')
        msg = email.message_from_bytes(data[0][1])
        try:
            when = email.utils.parsedate_to_datetime(msg.get('Date', ''))
        except (TypeError, ValueError):
            when = datetime.now()
        body, pdfs = '', []
        for part in msg.walk():
            if part.get_content_maintype() == 'multipart':
                continue
            filename = _decode(part.get_filename())
            payload = part.get_payload(decode=True)
            if filename and filename.lower().endswith('.pdf') and payload:
                pdfs.append((filename, payload))
            elif part.get_content_type() == 'text/plain' and payload and not body:
                body = payload.decode(part.get_content_charset() or 'utf-8', errors='replace')
            elif part.get_content_type() == 'text/html' and payload and not body:
                html = payload.decode(part.get_content_charset() or 'utf-8', errors='replace')
                body = re.sub(r'<[^>]+>', ' ', html)
        return Message(uid=uid, message_id=msg.get('Message-ID', f'uid-{uid.decode()}'),
                       sender=_decode(msg.get('From')), recipients=_decode(msg.get('To')),
                       subject=_decode(msg.get('Subject')), date=when.replace(tzinfo=None), body=body, pdfs=pdfs)

    def label(self, msg: Message, label: str) -> None:
        self.conn.uid('STORE', msg.uid, '+X-GM-LABELS', _quote(label))

    def close(self):
        try:
            self.conn.logout()
        except Exception:
            pass


def portfolio_from_recipients(text: str) -> Optional[str]:
    t = text.lower()
    for hint, pf in RECIPIENT_PORTFOLIO.items():
        if hint in t:
            return pf
    return None


def classify(msg: Message) -> str:
    subject = msg.subject.lower()
    if msg.pdfs:
        return 'statement'
    if 'statement published' in subject:
        return 'published_notice'
    if 'pending deposit' in subject:
        return 'deposit_notice'
    return 'update'


def handle(msg: Message) -> str:
    """Process one message; returns the label to apply."""
    with db.session() as s:
        if s.scalar(select(db.Email.id).where(db.Email.message_id == msg.message_id)):
            return PROCESSED
    kind = classify(msg)
    hint = portfolio_from_recipients(msg.recipients)
    record = db.Email(message_id=msg.message_id, sender=msg.sender, recipients=msg.recipients,
                      subject=msg.subject, date=msg.date, kind=kind, status='done', body=msg.body[:50000],
                      portfolio=hint)
    label = PROCESSED
    if kind == 'statement':
        notes = []
        for filename, data in msg.pdfs:
            doc = ingest_pdf_bytes(data, filename, 'email', source_ref=msg.message_id,
                                   received_at=msg.date, portfolio_hint=hint)
            notes.append(f"{filename}: {doc.status}")
        record.summary = '; '.join(notes)
    elif kind == 'deposit_notice':
        m = re.search(r'\$([\d,]+\.\d\d)', msg.body)
        if m:
            record.amount = Decimal(m.group(1).replace(',', ''))
        record.summary = f"Pending deposit{f' of ${record.amount:,.2f}' if record.amount else ''}"
    elif kind == 'published_notice':
        record.summary = 'Statement published on the owner portal'
    else:
        record.status, label = _read_update(msg, record)
    with db.session() as s:
        s.add(record)
        s.flush()
        for ev in getattr(record, '_events', []):
            ev.source_id = record.id
            s.add(ev)
        s.commit()
    return label


def _read_update(msg: Message, record: db.Email):
    if not llm.available():
        record.summary = '(not read: no ANTHROPIC_API_KEY)'
        return 'needs_review', NEEDS_REVIEW
    result = llm.extract_email_events(msg.subject, msg.sender, msg.date.isoformat(), msg.body)
    if result is None:
        record.summary = '(Claude declined to read this email)'
        return 'needs_review', NEEDS_REVIEW
    record.summary = result.get('summary', '')
    events = []
    for ev in result.get('events', []):
        try:
            when = date.fromisoformat(ev['date'])
        except (KeyError, ValueError):
            when = msg.date.date()
        events.append(db.Event(property_key=property_key(ev.get('property', '')), portfolio=record.portfolio,
                               date=when, type=ev.get('type', 'update'), title=ev.get('title', msg.subject)[:300],
                               detail=record.summary,
                               amount=Decimal(str(ev['amount'])) if ev.get('amount') is not None else None,
                               source_type='email'))
    record._events = events
    if not result.get('relevant', True):
        record.kind = 'other'
    return 'done', PROCESSED


def run(since: str = SINCE) -> dict:
    box = Mailbox()
    counts = {}
    try:
        for msg in box.unprocessed(since):
            try:
                label = handle(msg)
                box.label(msg, label)
                if label == NEEDS_REVIEW:
                    box.label(msg, PROCESSED)
                counts[label] = counts.get(label, 0) + 1
            except Exception:
                log.exception("Failed on %s (%s); will retry next run", msg.subject, msg.message_id)
                counts['failed'] = counts.get('failed', 0) + 1
    finally:
        box.close()
    return counts
