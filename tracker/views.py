"""What each screen shows, built from the derived World."""
from __future__ import annotations

import hashlib
import json
from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal
from typing import Dict, List, Optional

from sqlalchemy import select

from . import db, llm
from .derive import World, covered
from .portfolios import PORTFOLIO_BY_KEY, PORTFOLIOS

QUIET_TYPES = {'maintenance', 'utility'}


def f(x) -> Optional[float]:
    return None if x is None else float(x)


def _month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def _month_end(y: int, m: int) -> date:
    return date(y, m, monthrange(y, m)[1])


def _iter_months(start: date, end: date):
    cur = date(start.year, start.month, 1)
    while cur <= end:
        yield cur
        cur = date(cur.year + cur.month // 12, cur.month % 12 + 1, 1)


def active_portfolios(w: World, today: date) -> List[str]:
    out = []
    for p in PORTFOLIOS:
        sts = [st for st in w.statements if st.portfolio == p['key'] and st.properties]
        if sts and max(st.period_end for st in sts) >= today - timedelta(days=150):
            out.append(p['key'])
    return out


def current_properties(w: World, pf: str) -> List[str]:
    sts = [st for st in w.statements if st.portfolio == pf and st.properties]
    if not sts:
        return []
    latest = max(st.period_end for st in sts)
    keys = []
    for k, info in w.properties.items():
        if info['portfolio'] != pf:
            continue
        last_seen = max(c[1] for c in w.property_coverage[k])
        if last_seen >= latest - timedelta(days=60):
            keys.append(k)
    return sorted(keys, key=lambda k: w.properties[k]['address'])


def missing_months(w: World, pf: str, today: date, since: Optional[date] = None) -> List[str]:
    """Calendar months with no statement covering most of the month."""
    cov = w.coverage.get(pf, [])
    if not cov:
        return []
    since = since or date(today.year, 1, 1)
    last_full = date(today.year, today.month, 1) - timedelta(days=1)
    out = []
    for m in _iter_months(since, last_full):
        end = _month_end(m.year, m.month)
        if not covered(cov, m, end, slack=5):
            out.append(f"{m:%b %Y}")
    return out


def property_card(w: World, k: str, today: date) -> dict:
    info = w.properties[k]
    ts = w.tenancies.get(k, [])
    cur = next((t for t in reversed(ts) if t.end is None), None)
    latest_cover = max(c[1] for c in w.property_coverage[k])
    snaps = sorted(w.rent_snapshots.get(k, []), key=lambda x: x[0])
    rent = next((r for _, r in reversed(snaps) if r is not None), None)
    lease_now = bool(snaps) and snaps[-1][1] is not None

    if cur:
        status, tenant = 'occupied', cur.tenant
        since = cur.start
    elif ts and ts[-1].end and ts[-1].end_known:
        status, tenant, since = 'vacant', None, ts[-1].end
    else:
        status, tenant, since = 'unknown', (ts[-1].tenant if ts else None), None

    months = w.month_rent.get(k, {})
    detail_months = [m for m in _iter_months(latest_cover - timedelta(days=62), latest_cover)
                     if any(c[2] and c[0] <= m <= c[1] for c in w.property_coverage[k])]
    payment = None
    if detail_months and status == 'occupied':
        m = detail_months[-1]
        rec = months.get(_month_key(m))
        if not rec or rec['received'] <= 0:
            payment = {'month': f"{m:%B}", 'state': 'missing', 'text': f"No rent received in {m:%B}"}
        else:
            pays = sorted(rec['payments'])
            last = pays[-1][0] if pays else None
            first_month = cur is not None and (cur.start.year, cur.start.month) == (m.year, m.month)
            late = bool(pays) and pays[0][0].day > 10 and not first_month
            text = f"${rec['received']:,.2f}" + (f", {len(pays)} payments" if len(pays) > 1 else '') \
                + (f", last {last:%d %b}" if last else '')
            payment = {'month': f"{m:%B}", 'state': 'late' if late else 'paid', 'text': text}

    events = [e for e in w.events if e.property_key == k and e.type not in QUIET_TYPES]
    recent = [ev(e) for e in sorted(events, key=lambda e: e.date, reverse=True)
              if e.date >= latest_cover - timedelta(days=365)][:4]

    flags = []
    if status == 'vacant' and since:
        days = (today - since).days
        flags.append({'level': 'orange', 'text': f"Vacant {days // 30} months (since {since:%b %Y})"
                      if days > 60 else f"Vacant since {since:%d %b %Y}"})
    year_ago = latest_cover - timedelta(days=365)
    returned = [e for e in events if e.type == 'returned' and e.date >= year_ago]
    if returned:
        flags.append({'level': 'amber', 'text': f"{len(returned)} returned payment(s) in the last 12 months"})
    late = [e for e in events if e.type == 'late' and e.date >= latest_cover - timedelta(days=183)]
    if len(late) >= 3:
        flags.append({'level': 'amber', 'text': f"Rent late or missing {len(late)} times in the last 6 months"})
    evictions = [e for e in events if e.type == 'eviction' and e.date >= year_ago]
    if evictions:
        flags.append({'level': 'red', 'text': f"Eviction activity {evictions[-1].date:%b %Y}"})
    if status == 'occupied' and not lease_now and snaps:
        flags.append({'level': 'amber', 'text': 'Latest statement shows no current lease'})

    return {
        'key': k, 'address': info['address'], 'status': status, 'tenant': tenant,
        'since': since.isoformat() if since else None, 'rent': f(rent), 'lease_now': lease_now,
        'payment': payment, 'recent': recent, 'flags': flags, 'data_through': latest_cover.isoformat(),
    }


def ev(e) -> dict:
    return {'date': e.date.isoformat(), 'type': e.type, 'title': e.title, 'detail': e.detail,
            'amount': f(e.amount), 'source': e.source, 'property': e.property_key}


def status(w: World, today: Optional[date] = None) -> dict:
    today = today or date.today()
    out = []
    for pf in active_portfolios(w, today):
        meta = PORTFOLIO_BY_KEY[pf]
        sts = sorted((st for st in w.statements if st.portfolio == pf), key=lambda st: st.period_end)
        latest = sts[-1]
        month_ends = [(d, b) for d, b in w.balances.get(pf, [])
                      if d == _month_end(d.year, d.month) and d >= latest.period_end - timedelta(days=400)]
        dists = w.distributions.get(pf, [])
        out.append({
            'key': pf, 'name': meta['name'], 'short': meta['short'], 'color': meta['color'],
            'balance': f(latest.ending_balance), 'balance_as_of': latest.period_end.isoformat(),
            'balance_series': [{'date': d.isoformat(), 'balance': f(b)} for d, b in month_ends[-13:]],
            'last_distribution': ({'date': dists[-1].date.isoformat(), 'amount': f(dists[-1].amount)} if dists else None),
            'data_through': latest.period_end.isoformat(),
            'missing': missing_months(w, pf, today),
            'houses': [property_card(w, k, today) for k in current_properties(w, pf)],
        })
    return {'today': today.isoformat(), 'portfolios': out}


def timeline(w: World, today: Optional[date] = None) -> dict:
    today = today or date.today()
    groups: Dict[str, list] = {}
    for k, info in w.properties.items():
        cov = sorted(w.property_coverage[k], key=lambda c: c[0])
        first, last_seen = cov[0][0], max(c[1] for c in cov)
        still_owned = info['portfolio'] in active_portfolios(w, today) and k in current_properties(w, info['portfolio'])
        horizon = today if still_owned else last_seen
        segs = []
        ts = w.tenancies.get(k, [])
        for i, t in enumerate(ts):
            solid_end = t.end if (t.end and t.end_known) else (t.last_payment or t.start) if t.end else horizon
            segs.append({'kind': 'tenant', 'label': t.tenant, 'start': t.start.isoformat(),
                         'end': max(solid_end, t.start).isoformat(), 'start_known': t.start_known})
            if t.end and not t.end_known:
                segs.append({'kind': 'unconfirmed', 'label': t.tenant, 'start': (t.last_payment or t.start).isoformat(),
                             'end': t.end.isoformat()})
            if t.end and t.end_known:
                nxt = ts[i + 1].start if i + 1 < len(ts) else horizon
                if (nxt - t.end).days > 7:
                    segs.append({'kind': 'vacant', 'label': 'Vacant', 'start': t.end.isoformat(), 'end': nxt.isoformat()})
        gaps = []
        cur = first
        for a, b, _ in cov:
            if a > cur + timedelta(days=20):
                gaps.append({'start': cur.isoformat(), 'end': a.isoformat()})
            cur = max(cur, b)
        if still_owned and horizon > cur + timedelta(days=20):
            gaps.append({'start': cur.isoformat(), 'end': horizon.isoformat()})
        rents = []
        prev = None
        for d, r in sorted(w.rent_snapshots.get(k, []), key=lambda x: x[0]):
            if r is not None and r != prev:
                rents.append({'date': d.replace(day=1).isoformat(), 'rent': f(r)})
                prev = r
        row = {'key': k, 'address': info['address'], 'first': first.isoformat(), 'last': horizon.isoformat(),
               'still_owned': still_owned, 'segments': segs, 'gaps': gaps, 'rents': rents,
               'events': [ev(e) for e in w.events if e.property_key == k]}
        groups.setdefault(info['portfolio'] or 'unknown', []).append(row)
    out = []
    for p in PORTFOLIOS:
        if p['key'] in groups:
            out.append({**p, 'rows': sorted(groups[p['key']], key=lambda r: (not r['still_owned'], r['address']))})
    return {'today': today.isoformat(), 'groups': out}


def analytics(w: World) -> dict:
    years = sorted({y for pf in w.yearly.values() for y in pf})
    portfolios = []
    for p in PORTFOLIOS:
        rows = w.yearly.get(p['key'])
        if not rows:
            continue
        portfolios.append({**p, 'years': {y: {k: (f(v) if isinstance(v, Decimal) else v) for k, v in r.items()}
                                          for y, r in rows.items()}})
    props = []
    for k, years_ in w.property_year.items():
        info = w.properties.get(k, {})
        props.append({'key': k, 'address': info.get('address', k), 'portfolio': info.get('portfolio'),
                      'years': {y: {kk: f(vv) for kk, vv in r.items()} for y, r in years_.items()}})
    dists = [{'portfolio': pf, 'date': d.date.isoformat(), 'amount': f(d.amount), 'note': d.note}
             for pf, ds in w.distributions.items() for d in ds]
    return {'years': years, 'portfolios': portfolios, 'properties': props, 'distributions': dists}


def month_facts(w: World, month: str, portfolios: Optional[List[str]] = None, session=None) -> dict:
    y, m = map(int, month.split('-'))
    start, end = date(y, m, 1), _month_end(y, m)
    facts = {'month': f"{start:%B %Y}", 'portfolios': []}
    for p in PORTFOLIOS:
        if portfolios and p['key'] not in portfolios:
            continue
        sts = [st for st in w.statements if st.portfolio == p['key'] and st.period_start <= end and st.period_end >= start]
        if not sts and not portfolios and p['key'] not in active_portfolios(w, end):
            continue
        monthly = [st for st in sts if st.days <= 45]
        st = monthly[0] if monthly else None
        houses = []
        keys = {k for k, info in w.properties.items() if info['portfolio'] == p['key']}
        for k in sorted(keys):
            cov = w.property_coverage[k]
            if not any(c[0] <= end and c[1] >= start for c in cov):
                continue
            rec = w.month_rent.get(k, {}).get(month)
            ts = w.tenancies.get(k, [])
            live = [t for t in ts if t.start <= end and (t.end is None or t.end >= start)]
            tenant = max(live, key=lambda t: t.start).tenant if live else None
            houses.append({
                'house': w.properties[k]['address'], 'tenant': tenant or 'none (vacant or unknown)',
                'rent_received': f(rec['received']) if rec else 0.0,
                'payment_dates': [d.isoformat() for d, _ in (rec['payments'] if rec else [])],
                'events': [{'date': e.date.isoformat(), 'what': e.title, 'amount': f(e.amount)}
                           for e in w.events if e.property_key == k and start <= e.date <= end],
            })
        entry = {'portfolio': p['name'], 'houses': houses}
        if st:
            entry['statement'] = {'income': f(st.income), 'expenses': f(st.expenses), 'management_fees': f(st.mgmt_fees),
                                  'paid_out_to_owner': f(st.draws), 'balance_start': f(st.previous_balance),
                                  'balance_end': f(st.ending_balance)}
        else:
            entry['statement'] = 'missing: no statement for this month has been received'
        facts['portfolios'].append(entry)
    own = session is None
    s = session or db.session()
    try:
        emails = list(s.scalars(select(db.Email).where(db.Email.kind == 'update')))
        facts['manager_emails'] = [{'date': e.date.date().isoformat(), 'subject': e.subject, 'summary': e.summary}
                                   for e in emails if e.date and start <= e.date.date() <= end + timedelta(days=10)
                                   and (not portfolios or e.portfolio in portfolios or e.portfolio is None)]
    finally:
        if own:
            s.close()
    return facts


def month_checks(w: World, month: str, session) -> List[str]:
    """Things in a month worth asking the manager about."""
    y, m = map(int, month.split('-'))
    start, end = date(y, m, 1), _month_end(y, m)
    names = {p['key']: p['name'] for p in PORTFOLIOS}
    checks = []
    for pf in active_portfolios(w, end):
        sts = [st for st in w.statements if st.portfolio == pf and st.period_start <= end and st.period_end >= start]
        if not covered(w.coverage.get(pf, []), start, end, slack=5):
            checks.append(f"{names[pf]}: no statement covering all of {start:%B %Y}")
        for st in sts:
            if st.days < 27 and st.period_end < end:
                checks.append(f"{names[pf]}: statement for part of a month only "
                              f"({st.period_start:%m/%d/%Y} to {st.period_end:%m/%d/%Y})")
            if not st.reconciled:
                checks.append(f"{names[pf]}: statement for {st.period_start:%m/%d/%Y} to {st.period_end:%m/%d/%Y} "
                              f"does not add up ({st.problems})")
    for e in w.events:
        if not (start <= e.date <= end) or e.property_key not in w.properties:
            continue
        house = w.properties[e.property_key]['address']
        if e.type in ('late', 'returned', 'eviction', 'legal'):
            checks.append(f"{house}: {e.title} ({e.date:%m/%d/%Y})")
        elif e.type in ('repair', 'make_ready', 'maintenance') and e.amount is not None and abs(e.amount) >= 500:
            checks.append(f"{house}: {e.title}, ${abs(e.amount):,.2f} ({e.date:%m/%d/%Y})")
    review = session.scalars(select(db.Email).where(db.Email.status == 'needs_review'))
    for e in review:
        if e.date and start <= e.date.date() <= end + timedelta(days=10):
            checks.append(f"Email not understood automatically: '{e.subject}' ({e.date:%m/%d/%Y})")
    return checks


def summary(w: World, month: str, audience: str = 'owner', refresh: bool = False) -> dict:
    portfolios = ['torgo'] if audience == 'family' else None
    with db.session() as s:
        facts = month_facts(w, month, portfolios, session=s)
        if audience == 'manager':
            facts['checks'] = month_checks(w, month, s)
        # The prompt is part of the key, so a change of style rewrites old letters.
        digest = hashlib.sha256(json.dumps([facts, llm.SUMMARY_SYSTEM[audience]], sort_keys=True,
                                           default=str).encode()).hexdigest()
        cached = s.scalar(select(db.Summary).where(db.Summary.month == month, db.Summary.audience == audience,
                                                   db.Summary.facts_hash == digest))
        text = cached.text if cached else None
        if (text is None or refresh) and llm.available():
            text = llm.write_summary(facts, audience)
            if text:
                s.add(db.Summary(month=month, audience=audience, facts_hash=digest, text=text))
                s.commit()
    return {'month': month, 'audience': audience, 'facts': facts, 'text': text, 'llm': llm.available()}
