"""Work out what happened at each house from the ledger.

Everything here is recomputed from the source tables on demand, so a better
rule applies to the whole history at once.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from sqlalchemy import select

from . import db
from .portfolios import PORTFOLIO_BY_KEY

ZERO = Decimal('0')


@dataclass
class Tenancy:
    property_key: str
    tenant: str
    start: date
    start_known: bool          # from a lease date rather than the first payment seen
    last_payment: Optional[date]
    end: Optional[date] = None  # None while still there
    end_known: bool = True      # False when statements are missing around the end


@dataclass
class TimelineEvent:
    property_key: Optional[str]
    portfolio: Optional[str]
    date: date
    type: str      # move_in | move_out | rent_change | late | returned | assistance | repair | make_ready
                   # | legal | eviction | lease | renewal | maintenance | utility | transfer | update
    title: str
    detail: str = ''
    amount: Optional[Decimal] = None
    source: str = ''         # "statement:<id>" | "email:<id>" | "manual:<id>"


@dataclass
class Distribution:
    portfolio: str
    date: date
    amount: Decimal
    note: str = ''


@dataclass
class World:
    properties: Dict[str, dict] = field(default_factory=dict)
    tenancies: Dict[str, List[Tenancy]] = field(default_factory=lambda: defaultdict(list))
    events: List[TimelineEvent] = field(default_factory=list)
    rent_snapshots: Dict[str, List[Tuple[date, Optional[Decimal]]]] = field(default_factory=lambda: defaultdict(list))
    month_rent: Dict[str, Dict[str, dict]] = field(default_factory=lambda: defaultdict(dict))
    balances: Dict[str, List[Tuple[date, Decimal]]] = field(default_factory=lambda: defaultdict(list))
    distributions: Dict[str, List[Distribution]] = field(default_factory=lambda: defaultdict(list))
    coverage: Dict[str, List[Tuple[date, date, bool]]] = field(default_factory=lambda: defaultdict(list))
    property_coverage: Dict[str, List[Tuple[date, date, bool]]] = field(default_factory=lambda: defaultdict(list))
    statements: List[db.Statement] = field(default_factory=list)
    yearly: Dict[str, Dict[str, dict]] = field(default_factory=lambda: defaultdict(dict))
    property_year: Dict[str, Dict[str, dict]] = field(default_factory=lambda: defaultdict(dict))


def tenant_display(key: str) -> str:
    return re.sub(r'_\d+$', '', key.strip())


def tenant_norm(name: str) -> str:
    name = tenant_display(name).lower()
    tokens = re.findall(r'[a-z]+', name)
    return ' '.join(sorted(t for t in tokens if len(t) > 1 or len(tokens) <= 2))


def classify_line(line: db.LedgerLine) -> Optional[str]:
    """Event type for a ledger line worth showing on the timeline, else None."""
    cat = (line.category or '').lower()
    text = f"{line.category} {line.comment} {line.name}".lower()
    if line.section == 'income':
        if line.txn_type == 'Journal Entry' and line.amount < 0 and 'return' in text:
            return 'returned'
        if 'returned_nsf' in text or 'nsf' in text.split():
            return None   # the charge being reversed; the journal entry carries the event
        if re.search(r'\bera\b', (line.comment or '').lower()) or 'rental assistance' in text:
            return 'assistance'
        return None
    if line.section != 'expense':
        return None
    if 'management fee' in cat or 'mortgage' in cat or 'tax' in cat or 'insurance' in cat:
        return None
    if 'evict' in text or 'detainer' in text or 'court' in text:
        return 'eviction'
    if 'legal' in cat:
        return 'legal'
    if 'get ready' in text or 'make ready' in text or 'make-ready' in text or 'turnover' in text:
        return 'make_ready'
    if 'renewal' in text:
        return 'renewal'
    if 'leasing fee' in text or 'lease fee' in text or 'placement' in text:
        return 'lease'
    if 'landscap' in text or 'common area' in cat or 'lawn' in text:
        return 'maintenance'
    if 'utilit' in text or 'mlg' in text:
        return 'utility'
    if 'repair' in text or 'invoice' in text or 'plumb' in text or 'hvac' in text or 'electric' in text:
        return 'repair'
    return 'repair' if line.amount and line.amount > 0 else None


def covered(intervals, d1: date, d2: date, slack: int = 20) -> bool:
    """Whether statements cover every day from d1 to d2 (allowing small gaps)."""
    if d2 < d1:
        return True
    cur = d1
    for a, b, _ in sorted(intervals, key=lambda x: x[0]):
        if a - timedelta(days=slack) <= cur <= b:
            cur = max(cur, b)
            if cur >= d2:
                return True
    return cur >= d2 - timedelta(days=slack)


def _month(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def build_world(session=None) -> World:
    own = session is None
    s = session or db.session()
    try:
        return _build(s)
    finally:
        if own:
            s.close()


def _build(s) -> World:
    w = World()
    statements = list(s.scalars(select(db.Statement).order_by(db.Statement.period_end, db.Statement.id)))
    w.statements = statements
    by_id = {st.id: st for st in statements}

    # -- properties, coverage, rent snapshots, current owner ---------------------
    addresses = {p.key: p.address for p in s.scalars(select(db.Property))}
    for st in statements:
        detail = st.format == 'detail'
        if st.portfolio:
            w.coverage[st.portfolio].append((st.period_start, st.period_end, detail))
        for sp in st.properties:
            info = w.properties.setdefault(sp.property_key, {
                'key': sp.property_key, 'address': addresses.get(sp.property_key, sp.address),
                'portfolio': st.portfolio, 'owners': []})
            if detail and _looks_like_street(sp.address):
                info['address'] = sp.address
            if st.portfolio and (not info['owners'] or info['owners'][-1][0] != st.portfolio):
                info['owners'].append((st.portfolio, st.period_start))
            info['portfolio'] = st.portfolio or info['portfolio']
            w.property_coverage[sp.property_key].append((st.period_start, st.period_end, detail))
            w.rent_snapshots[sp.property_key].append((st.period_end, sp.current_rent))
            if sp.lease_name:
                w.tenancies[sp.property_key].append(Tenancy(
                    property_key=sp.property_key, tenant=sp.lease_name.strip(),
                    start=sp.lease_start or st.period_end, start_known=sp.lease_start is not None,
                    last_payment=st.period_end))

    for pkey, info in w.properties.items():
        owners = info['owners']
        for (prev_pf, _), (pf, start) in zip(owners, owners[1:]):
            name_a = PORTFOLIO_BY_KEY.get(prev_pf, {}).get('short', prev_pf)
            name_b = PORTFOLIO_BY_KEY.get(pf, {}).get('short', pf)
            w.events.append(TimelineEvent(pkey, pf, start, 'transfer', f"Moved from {name_a} to {name_b}"))

    # -- canonical ledger (one row per transaction even when it appears on a
    #    monthly and an annual statement) ------------------------------------------
    seen = set()
    lines: List[db.LedgerLine] = []
    for line in s.scalars(select(db.LedgerLine).order_by(db.LedgerLine.date, db.LedgerLine.id)):
        if line.fingerprint in seen:
            continue
        seen.add(line.fingerprint)
        lines.append(line)

    # -- tenancies from rent receipts -----------------------------------------------
    spans: Dict[Tuple[str, str], dict] = {}
    for line in lines:
        if line.section != 'income' or not line.tenant_key:
            continue
        key = (line.property_key, tenant_norm(line.tenant_key))
        sp = spans.setdefault(key, {'name': tenant_display(line.tenant_key), 'first': line.date, 'last': line.date})
        sp['first'] = min(sp['first'], line.date)
        if line.amount > 0:
            sp['last'] = max(sp['last'], line.date)
    for (pkey, norm), sp in spans.items():
        existing = next((t for t in w.tenancies[pkey] if tenant_norm(t.tenant) == norm), None)
        if existing:
            existing.start = min(existing.start, sp['first']) if not existing.start_known else existing.start
            existing.last_payment = max(existing.last_payment or sp['last'], sp['last'])
            existing.tenant = sp['name']
        else:
            w.tenancies[pkey].append(Tenancy(pkey, sp['name'], sp['first'], False, sp['last']))
    # merge summary-format duplicates of the same tenant across years
    for pkey, ts in w.tenancies.items():
        merged: Dict[str, Tenancy] = {}
        for t in ts:
            n = tenant_norm(t.tenant)
            if n in merged:
                m = merged[n]
                if t.start_known and (not m.start_known or t.start < m.start):
                    m.start, m.start_known = t.start, True
                elif not m.start_known:
                    m.start = min(m.start, t.start)
                m.last_payment = max(filter(None, [m.last_payment, t.last_payment]), default=None)
                if any(ch in t.tenant for ch in ',_') and not any(ch in m.tenant for ch in ','):
                    m.tenant = t.tenant
            else:
                merged[n] = t
        ordered = sorted(merged.values(), key=lambda t: t.start)
        latest_snapshot = max(w.rent_snapshots.get(pkey, []), default=None, key=lambda x: x[0])
        latest_cover = max((c[1] for c in w.property_coverage.get(pkey, [])), default=None)
        cov = w.property_coverage.get(pkey, [])
        for a, b in zip(ordered, ordered[1:]):
            seen_until = a.last_payment or a.start
            if covered(cov, seen_until, b.start):
                a.end = min(b.start, seen_until + timedelta(days=31))
            else:
                a.end, a.end_known = b.start, False
        if ordered:
            last = ordered[-1]
            no_lease_now = latest_snapshot is not None and latest_snapshot[1] is None
            stale = latest_cover and last.last_payment and (latest_cover - last.last_payment).days > 62
            if no_lease_now or stale:
                last.end = (last.last_payment or last.start) + timedelta(days=15)
                last.end_known = covered(cov, last.last_payment or last.start, latest_cover)
        w.tenancies[pkey] = ordered

    first_seen = {k: min(c[0] for c in v) for k, v in w.property_coverage.items()}
    for pkey, ts in w.tenancies.items():
        pf = w.properties.get(pkey, {}).get('portfolio')
        for t in ts:
            cov = w.property_coverage.get(pkey, [])
            if t.start_known or ((t.start - first_seen.get(pkey, t.start)).days > 45
                                 and covered(cov, t.start - timedelta(days=60), t.start)):
                w.events.append(TimelineEvent(pkey, pf, t.start, 'move_in', f"{t.tenant} moved in"))
            if t.end and t.end_known:
                w.events.append(TimelineEvent(pkey, pf, t.end, 'move_out', f"{t.tenant} moved out",
                                              detail=f"Last rent payment {t.last_payment:%d %b %Y}" if t.last_payment else ''))

    # -- rent changes --------------------------------------------------------------
    for pkey, snaps in w.rent_snapshots.items():
        pf = w.properties.get(pkey, {}).get('portfolio')
        prev = None
        prev_date = None
        cov = w.property_coverage.get(pkey, [])
        for d, rent in sorted(snaps, key=lambda x: x[0]):
            if rent is None:
                continue
            if prev is not None and rent != prev:
                detail = '' if covered(cov, prev_date, d) else f"Changed some time between {prev_date:%b %Y} and {d:%b %Y}"
                w.events.append(TimelineEvent(pkey, pf, d.replace(day=1), 'rent_change',
                                              f"Rent ${prev:,.0f} → ${rent:,.0f}", detail=detail, amount=rent))
            prev, prev_date = rent, d

    # -- per-line events and monthly rent --------------------------------------------
    late_fee_months = set()
    for line in lines:
        py = w.property_year[line.property_key].setdefault(str(line.date.year), {
            'income': ZERO, 'expenses': ZERO, 'mgmt_fees': ZERO, 'repairs': ZERO})
        if line.section == 'income':
            py['income'] += line.amount
        elif line.section == 'expense':
            if 'management fee' in (line.category or '').lower():
                py['mgmt_fees'] += line.amount
            else:
                py['expenses'] += line.amount
                if classify_line(line) in ('repair', 'make_ready'):
                    py['repairs'] += line.amount
        st = by_id.get(line.statement_id)
        source = f"statement:{line.statement_id}"
        if line.section == 'income' and line.tenant_key and st and st.format == 'detail':
            cat = (line.category or '').lower()
            if cat.startswith('rent'):
                m = w.month_rent[line.property_key].setdefault(_month(line.date), {
                    'received': ZERO, 'payments': [], 'tenant': tenant_display(line.tenant_key)})
                m['received'] += line.amount
                if line.amount > 0 and 'prepay' not in (line.comment or '').lower():
                    m['payments'].append((line.date, line.amount))
            if 'late fee' in cat and line.amount > 0 and line.txn_type == 'Charge':
                late_fee_months.add((line.property_key, _month(line.date)))
        kind = classify_line(line)
        if not kind:
            continue
        titles = {
            'returned': 'Payment returned', 'assistance': 'Rent paid by rental assistance',
            'repair': (line.comment or line.category or 'Repair'), 'make_ready': 'Make-ready: ' + (line.comment or 'turnover work'),
            'legal': 'Legal: ' + (line.comment or line.name), 'eviction': 'Eviction: ' + (line.comment or line.name),
            'lease': 'Leasing fee (new lease)', 'renewal': 'Lease renewal',
            'maintenance': line.comment or line.category, 'utility': line.comment or 'Utilities',
        }
        w.events.append(TimelineEvent(line.property_key, line.portfolio, line.date, kind, titles[kind].strip(),
                                      detail=f"{line.name} · {line.category}".strip(' ·'),
                                      amount=abs(line.amount), source=source))

    # late / missed rent, only where monthly-level detail exists
    for pkey, months in w.month_rent.items():
        pf = w.properties.get(pkey, {}).get('portfolio')
        for t in w.tenancies.get(pkey, []):
            cur = date(t.start.year, t.start.month, 1)
            if t.end and not t.end_known:
                end = t.last_payment or t.start      # do not judge months after we lost sight of them
            else:
                end = t.end or max((c[1] for c in w.property_coverage[pkey]), default=t.start)
            while cur <= end:
                ym = _month(cur)
                has_detail = any(c[2] and c[0] <= cur <= c[1] for c in w.property_coverage[pkey])
                if has_detail and cur > date(t.start.year, t.start.month, 1):
                    m = months.get(ym)
                    if not m or m['received'] <= 0:
                        if cur.replace(day=28) <= end:
                            w.events.append(TimelineEvent(pkey, pf, cur, 'late', f"No rent received in {cur:%B %Y}",
                                                          detail=t.tenant))
                    else:
                        first = min((p[0] for p in m['payments']), default=None)
                        if (pkey, ym) in late_fee_months or (first and first.day > 10):
                            w.events.append(TimelineEvent(pkey, pf, first or cur, 'late',
                                                          f"{cur:%B} rent paid late" + (f" ({first:%d %b})" if first else ''),
                                                          detail=f"{t.tenant} · {len(m['payments'])} payment(s)",
                                                          amount=m['received']))
                cur = date(cur.year + (cur.month // 12), cur.month % 12 + 1, 1)

    # -- email and manual events -------------------------------------------------------
    for ev in s.scalars(select(db.Event)):
        w.events.append(TimelineEvent(ev.property_key, ev.portfolio, ev.date, ev.type, ev.title,
                                      detail=ev.detail or '', amount=ev.amount, source=f"{ev.source_type}:{ev.source_id}"))

    # -- balances and distributions ------------------------------------------------------
    for st in statements:
        if not st.portfolio:
            continue
        w.balances[st.portfolio].append((st.period_start - timedelta(days=1), st.previous_balance))
        w.balances[st.portfolio].append((st.period_end, st.ending_balance))
    for pf, pts in w.balances.items():
        dedup = {}
        for d, b in sorted(pts, key=lambda x: x[0]):
            dedup[d] = b
        w.balances[pf] = sorted(dedup.items())

    payments = list(s.scalars(select(db.OwnerPayment)))
    for pay in payments:
        if pay.portfolio:
            w.distributions[pay.portfolio].append(Distribution(pay.portfolio, pay.date, pay.amount))
    with_payments = {pay.statement_id for pay in payments}
    short = [st for st in statements if st.portfolio and st.days <= 45 and st.draws]
    for st in short:
        when = st.generated_at.date() if st.generated_at else st.period_end
        w.distributions[st.portfolio].append(Distribution(st.portfolio, when, st.draws))
    for st in statements:
        if not st.portfolio or st.days <= 45 or st.id in with_payments or not st.draws:
            continue
        inside = sum((d.amount for d in w.distributions[st.portfolio]
                      if st.period_start <= d.date <= st.period_end + timedelta(days=10)), ZERO)
        rest = st.draws - inside
        if rest > Decimal('0.5'):
            w.distributions[st.portfolio].append(Distribution(st.portfolio, st.period_end, rest,
                                                              note='year total, month not known'))
    for pf in w.distributions:
        w.distributions[pf].sort(key=lambda d: d.date)

    # -- yearly analytics (by statement, deduplicated by period) -------------------------
    w.yearly = _yearly(statements)
    w.events = _merge_same_day(w.events)
    return w


def _merge_same_day(events: List[TimelineEvent]) -> List[TimelineEvent]:
    """One returned-payment event per day per house (rent, late fee and
    convenience fee reversals arrive as separate journal entries)."""
    out: List[TimelineEvent] = []
    index: Dict[tuple, TimelineEvent] = {}
    for e in sorted(events, key=lambda e: (e.date, e.property_key or '', e.type)):
        key = (e.property_key, e.date, e.type)
        if e.type == 'returned' and key in index:
            index[key].amount = (index[key].amount or ZERO) + (e.amount or ZERO)
            continue
        index[key] = e
        out.append(e)
    return out


def _looks_like_street(address: str) -> bool:
    return bool(re.match(r'^\d+\s+\S', address.strip()))


def _yearly(statements: List[db.Statement]) -> Dict[str, Dict[str, dict]]:
    """Income, expenses, fees and payouts per portfolio per calendar year.

    Annual statements are used where they exist; monthly statements fill in
    the months no annual covers (the current year). Annual periods run
    Dec-Nov, so the year is the year of the period's end.
    """
    out: Dict[str, Dict[str, dict]] = defaultdict(dict)
    annual = [st for st in statements if st.portfolio and st.days > 300]
    monthly = [st for st in statements if st.portfolio and st.days <= 45]
    for st in annual:
        y = str(st.period_end.year)
        row = out[st.portfolio].setdefault(y, _zero_year())
        _add(row, st)
        row['source'] = 'annual'
    for st in monthly:
        if any(a.portfolio == st.portfolio and a.period_start <= st.period_start and st.period_end <= a.period_end
               for a in annual):
            continue
        y = str(st.period_end.year)
        row = out[st.portfolio].setdefault(y, _zero_year())
        if row.get('source') == 'annual':
            continue
        _add(row, st)
        row['source'] = 'monthly'
        row['months'] = row.get('months', 0) + 1
    return out


def _zero_year() -> dict:
    return {'income': ZERO, 'expenses': ZERO, 'mgmt_fees': ZERO, 'assets': ZERO, 'draws': ZERO,
            'contributions': ZERO}


def _add(row: dict, st: db.Statement) -> None:
    for k in ('income', 'expenses', 'mgmt_fees', 'assets', 'draws', 'contributions'):
        row[k] += getattr(st, k) or ZERO
