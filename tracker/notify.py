"""Email the monthly summaries once a month's statements are all in.

Run after each mail job. Nothing is sent until the recipients are set:
SUMMARY_OWNER_TO gets the full summary and SUMMARY_FAMILY_TO the Torgo
family version (comma-separated addresses). For every month from
SUMMARY_SEND_FROM (YYYY-MM, default last month) up to last month, once every
active portfolio has statements covering the whole month, each recipient
gets that month's summary once.

Delivery is over the Resend HTTPS API (Railway blocks SMTP). Resend only
delivers from its onboarding address to the Resend account's own address;
other recipients need EMAIL_FROM on a domain verified in Resend.
"""
from __future__ import annotations

import logging
import os
from datetime import date, timedelta
from typing import Callable, List, Optional

import requests
from sqlalchemy import select

from . import db, views
from .derive import World, build_world, covered

log = logging.getLogger(__name__)

RESEND_URL = 'https://api.resend.com/emails'
AUDIENCES = (('owner', 'SUMMARY_OWNER_TO'), ('family', 'SUMMARY_FAMILY_TO'))


def recipients() -> List[tuple]:
    """(audience, address) pairs from the settings."""
    return [(audience, addr.strip()) for audience, var in AUDIENCES
            for addr in os.getenv(var, '').split(',') if addr.strip()]


def month_complete(w: World, month: str) -> bool:
    """Every portfolio active at the month's end has statements covering the whole month."""
    y, m = map(int, month.split('-'))
    start, end = date(y, m, 1), views._month_end(y, m)
    active = views.active_portfolios(w, end)
    return bool(active) and all(covered(w.coverage.get(pf, []), start, end, slack=0) for pf in active)


def due_months(today: date) -> List[str]:
    last = date(today.year, today.month, 1) - timedelta(days=1)
    first = os.getenv('SUMMARY_SEND_FROM') or f"{last.year:04d}-{last.month:02d}"
    y, m = map(int, first.split('-'))
    return [f"{d.year:04d}-{d.month:02d}" for d in views._iter_months(date(y, m, 1), last)]


def resend(to: str, subject: str, text: str) -> None:
    sender = os.getenv('EMAIL_FROM', 'Rental Tracker <onboarding@resend.dev>')
    resp = requests.post(RESEND_URL, timeout=30,
                         headers={'Authorization': f"Bearer {os.environ['RESEND_API_KEY']}"},
                         json={'from': sender, 'to': [to], 'subject': subject, 'text': text})
    if resp.status_code >= 400:
        raise RuntimeError(f"Resend {resp.status_code}: {resp.text[:300]}")


def run(today: Optional[date] = None, send: Callable[[str, str, str], None] = resend,
        dry_run: bool = False) -> dict:
    today = today or date.today()
    targets = recipients()
    if not targets:
        return {'skipped': 'no recipients set'}
    if send is resend and not dry_run and not os.getenv('RESEND_API_KEY'):
        return {'skipped': 'RESEND_API_KEY not set'}
    w = build_world()
    counts: dict = {}
    for month in due_months(today):
        if not month_complete(w, month):
            continue
        label = date(*map(int, month.split('-')), 1).strftime('%B %Y')
        for audience, to in targets:
            with db.session() as s:
                if s.scalar(select(db.SentSummary.id).where(
                        db.SentSummary.month == month, db.SentSummary.audience == audience,
                        db.SentSummary.recipient == to)):
                    continue
            text = views.summary(w, month, audience)['text']
            if not text:
                log.warning("No %s summary for %s (is ANTHROPIC_API_KEY set?)", audience, month)
                counts['no_text'] = counts.get('no_text', 0) + 1
                continue
            subject = f"Torgo houses, {label}" if audience == 'family' else f"Rentals, {label}"
            if dry_run:
                print(f"--- would send to {to}: {subject}\n{text}\n")
                counts['would_send'] = counts.get('would_send', 0) + 1
                continue
            try:
                send(to, subject, text)
            except Exception:
                log.exception("Sending the %s summary for %s to %s failed; will retry", audience, month, to)
                counts['failed'] = counts.get('failed', 0) + 1
                continue
            with db.session() as s:
                s.add(db.SentSummary(month=month, audience=audience, recipient=to))
                s.commit()
            counts['sent'] = counts.get('sent', 0) + 1
    return counts
