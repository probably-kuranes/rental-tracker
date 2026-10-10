"""Parser for the 2013-2017 annual "Owner Statement Property Summary".

These statements have no per-payment detail. What they do have:
- who the tenant on each unit was at year end, and the rent ("Scheduled Rent by Unit")
- the rent collected per lease, with the lease start date ("Operating Income")
- every expense with date, payee and comment ("Operating Expenses")
- every payment to the owner, dated ("Payments to Owner")
"""
from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from typing import List, Optional

from .model import LedgerLine, OwnerPayment, ParsedStatement, PropertyPage
from .text import AMOUNT_RE, ParseError, mdy, money

DATE = r'\d\d/\d\d/\d{4}'
PERIOD_RE = re.compile(r'(' + DATE + r')\s*and\s*(' + DATE + r')')
TOTALS_RE = re.compile(
    r'(' + AMOUNT_RE + r')\s*\+\s*(' + AMOUNT_RE + r')\s*-\s*(' + AMOUNT_RE + r')\s*-\s*('
    + AMOUNT_RE + r')\s*-\s*(' + AMOUNT_RE + r')\s*=\s*(' + AMOUNT_RE + r')')
INCOME_ROW_RE = re.compile(
    r'^(.+?)(?:\s*/\s*(' + DATE + r'))?\s{2,}(.+?)\s{2,}(' + AMOUNT_RE + r')\s+(' + AMOUNT_RE + r')\s+(' + AMOUNT_RE + r')\s*$')
SCHED_ROW_RE = re.compile(r'^(\S.*?)\s{2,}(.+?)\s{2,}(' + AMOUNT_RE + r')\s*$')
EXPENSE_ROW_RE = re.compile(r'^(' + DATE + r')\s+(.*?)\s*(' + AMOUNT_RE + r')\s*$')
UNIT_TOTAL_RE = re.compile(r'Total for (.+?)\s+(' + AMOUNT_RE + r')\s*$')
PAYMENT_RE = re.compile(r'^(' + DATE + r')\s+(.+?)\s{2,}(' + AMOUNT_RE + r')\s*$')
KNOWN_CATEGORIES = {'Repairs', 'Utility Expenses', 'Common Area Maintenance', 'Legal and Professional',
                    'Leasing Fee', 'Lease Renewal', 'Advertising', 'Cleaning', 'Insurance', 'County Taxes'}
NOISE = ('Generated', 'Mid South Best Rentals', '46 N. Flicker', 'Memphis', 'ph. (901)', 'www.')


def is_summary_format(text: str) -> bool:
    return 'Owner Statement' in text and 'Property Summary' in text


def parse_summary_text(text: str) -> List[ParsedStatement]:
    lines = [l.replace('\f', '') for l in text.splitlines()]
    flat = '\n'.join(lines)
    m = PERIOD_RE.search(flat)
    if not m:
        raise ParseError("No period found in summary statement")
    st = ParsedStatement(format='summary', recipient='', period_start=mdy(m.group(1)), period_end=mdy(m.group(2)))

    for l in lines:
        if 'This report reflects' in l:
            st.recipient = l.split('This report reflects')[0].strip()
            break

    t = TOTALS_RE.search(re.sub(r'\s+', ' ', flat))
    if t:
        st.previous_balance, st.income, st.mgmt_fees, st.expenses, st.draws, st.ending_balance = (
            money(t.group(i)) for i in range(1, 7))
        st.total = st.previous_balance + st.income - st.mgmt_fees - st.expenses
        st.due_to_owner = st.ending_balance
    else:
        st.problems.append("summary totals line not found")

    pages: dict = {}

    def page(unit: str) -> PropertyPage:
        unit = re.sub(r'\s+', ' ', unit.strip())
        if unit not in pages:
            pages[unit] = PropertyPage(address=unit)
        return pages[unit]

    section = None
    pending_expenses: List[tuple] = []
    for raw in lines:
        s = raw.strip()
        if not s or s.startswith(NOISE):
            continue
        if s.startswith('Scheduled Rent by Unit'):
            section = 'sched'; continue
        if s in ('Operating Income', 'Income'):
            section = 'income'; continue
        if s in ('Operating Expenses', 'Expenses'):
            section = 'expenses'; continue
        if s.startswith('Payments to Owner'):
            section = 'payments'; continue
        if s.startswith(('Other Accounts', 'Owner Contributions')):
            section = None; continue

        if section == 'sched':
            if s.startswith(('Property/Unit', 'Total')):
                continue
            r = SCHED_ROW_RE.match(s)
            if r:
                st.tenants_by_unit[re.sub(r'\s+', ' ', r.group(1))] = (r.group(2).strip(), money(r.group(3)))
        elif section == 'income':
            if s.startswith(('Lease', 'Total')):
                continue
            r = INCOME_ROW_RE.match(s)
            if r:
                unit = r.group(1)
                p = page(unit)
                if r.group(2):
                    st.lease_starts[re.sub(r'\s+', ' ', unit.strip())] = mdy(r.group(2))
                p.lines.append(LedgerLine(section='income', category=r.group(3).strip(), txn_type='Period total',
                                          date=st.period_end, name=unit.strip(), comment='', amount=money(r.group(4))))
                p.lines.append(LedgerLine(section='expense', category='Management Fees', txn_type='Period total',
                                          date=st.period_end, name='Mid South Best Rentals', comment='',
                                          amount=money(r.group(5))))
        elif section == 'expenses':
            if s.startswith(('Date ', 'Total Operating Expenses')):
                continue
            u = UNIT_TOTAL_RE.search(s)
            if u:
                p = page(u.group(1))
                for d, middle, amt in pending_expenses:
                    chunks = [c for c in re.split(r'\s{2,}', middle) if c]
                    # chunks: [unit?, description, payee, comment]; the unit is
                    # dropped when it wrapped onto lines of its own.
                    if chunks and re.sub(r'\s+', '', chunks[0]).lower() == re.sub(r'\s+', '', u.group(1)).lower():
                        chunks = chunks[1:]
                    if chunks and re.match(r'^[A-Za-z]+\s?\d+\s', chunks[0] + ' ') and len(chunks) > 3:
                        chunks = chunks[1:]
                    if len(chunks) >= 3:
                        category, payee, comment = chunks[0], chunks[1], ' '.join(chunks[2:])
                    elif len(chunks) == 2 and chunks[0] in KNOWN_CATEGORIES:
                        # The payee wrapped onto other lines; keep the category.
                        category, payee, comment = chunks[0], '', chunks[1]
                    else:
                        category, payee, comment = '', (chunks[0] if chunks else ''), ' '.join(chunks[1:])
                    p.lines.append(LedgerLine(section='expense', category=category, txn_type='Bill', date=d,
                                              name=payee, comment=comment, amount=amt))
                pending_expenses = []
                continue
            r = EXPENSE_ROW_RE.match(s)
            if r:
                middle = r.group(2)
                # A unit name glued to its description ("Argonne3934 Repairs")
                middle = re.sub(r'^([A-Za-z]+ ?\d+)\s+', r'\1  ', middle)
                pending_expenses.append((mdy(r.group(1)), middle, money(r.group(3))))
        elif section == 'payments':
            if s.startswith(('Date', 'Total')):
                continue
            r = PAYMENT_RE.match(s)
            if r:
                st.owner_payments.append(OwnerPayment(date=mdy(r.group(1)), amount=money(r.group(3)),
                                                      description=r.group(2).strip()))

    st.properties = list(pages.values())
    for p in st.properties:
        p.total_income = sum((l.amount for l in p.lines if l.section == 'income'), Decimal('0'))
        p.total_expenses = sum((l.amount for l in p.lines if l.section == 'expense'), Decimal('0'))
        unit = re.sub(r'\s+', ' ', p.address)
        if unit in st.tenants_by_unit:
            p.current_rent = st.tenants_by_unit[unit][1]

    tol = Decimal('0.05')
    inc = sum((p.total_income for p in st.properties), Decimal('0'))
    if st.properties and abs(inc - st.income) > tol:
        st.problems.append(f"income rows {inc} != summary income {st.income}")
    exp = sum((l.amount for p in st.properties for l in p.lines
               if l.section == 'expense' and l.txn_type == 'Bill'), Decimal('0'))
    if st.properties and abs(exp - st.expenses) > tol:
        st.problems.append(f"expense rows {exp} != summary expenses {st.expenses}")
    if st.owner_payments:
        paid = sum((p.amount for p in st.owner_payments), Decimal('0'))
        if abs(paid - st.draws) > tol:
            st.problems.append(f"owner payments {paid} != draws {st.draws}")
    return [st]
