"""Parser for Propertyware's "Owner Statement Detail By Building".

This is the format of every monthly statement and of the annual statements
from statement-year 2018 on. Each property page lists every transaction
(rent receipts with the tenant's ledger key, late fees, returned payments,
bills with vendor and description), so the whole history can be rebuilt from
these lines.

Layout notes (pdftotext -layout output):
- One PDF often holds the same statement two or more times, once per
  recipient on the portfolio; each copy starts at an "OWNER STATEMENT" line.
- Comments are a wrapped table cell, vertically centred on their row, so a
  two-line comment prints one line above the row and one below.
- Long sections continue onto the next page with no property heading.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from .model import LedgerLine, ParsedStatement, PropertyPage
from .text import AMOUNT_RE, ParseError, mdy, money

SUMMARY_FIELDS = {
    'Previous Balance': 'previous_balance',
    'Income': 'income',
    'Expenses': 'expenses',
    'Mgmt Fees': 'mgmt_fees',
    'Assets': 'assets',
    'Total': 'total',
    'Contributions': 'contributions',
    'Draws': 'draws',
    'Ending Balance': 'ending_balance',
    'Portfolio Minimum': 'portfolio_minimum',
    'Unpaid Bills': 'unpaid_bills',
    'Due To Owner': 'due_to_owner',
}
SUMMARY_RE = re.compile(
    r'^\s*(' + '|'.join(re.escape(k) for k in SUMMARY_FIELDS) + r')\s+(?:[+-]\s+)?(' + AMOUNT_RE + r')\s*$'
)
PERIOD_RE = re.compile(r'Report Period:\s*(\d\d/\d\d/\d{4})\s*-\s*(\d\d/\d\d/\d{4})')
GENERATED_RE = re.compile(r'Generated\s+(\d\d/\d\d/\d{4}),\s+(\d{1,2}:\d\d\s*[AP]M)')
PAGE_FOOTER_RE = re.compile(r'^\s*Generated\b.*\bPage\b')
TXN_RE = re.compile(
    r'^\s{0,8}([A-Z][A-Za-z]+(?: [A-Z][a-z]+)*)\s{2,}(\d\d/\d\d/\d{4})\s+(.*?)\s*(' + AMOUNT_RE + r')\s*$'
)
RENT_DEPOSIT_RE = re.compile(r'^Rent:\s*(' + AMOUNT_RE + r')(?:\s+Deposit:\s*(' + AMOUNT_RE + r'))?')
DEPOSIT_ONLY_RE = re.compile(r'Deposit:\s*(' + AMOUNT_RE + r')')
SECTION_WORDS = {'Income': 'income', 'Expenses': 'expense', 'Asset': 'asset', 'Assets': 'asset', 'Equity': 'equity'}
PROPERTY_TOTAL_RE = re.compile(r'^Total (Income|Expenses|Assets|Equity) for (.+?)\s{2,}(' + AMOUNT_RE + r')\s*$')
CATEGORY_TOTAL_RE = re.compile(r'^Total (.+?)\s{2,}(' + AMOUNT_RE + r')\s*$')
NOI_RE = re.compile(r'^Net Operating Income\s+(' + AMOUNT_RE + r')\s*$')
COMPANY_LINES = ('Mid South Best Rentals', '46 N. Flicker', 'Memphis , TN', 'ph. (901)', 'www.midsouthbestrentals')


@dataclass
class _Row:
    line_no: int
    txn_type: str
    date: str
    name: str
    inline_comment: str
    amount: str
    section: str
    category: str
    leading: List[str] = field(default_factory=list)
    trailing: List[str] = field(default_factory=list)


def split_statements(text: str) -> List[List[str]]:
    """Split a PDF's text into one block of lines per statement copy."""
    lines = [l.replace('\f', '') for l in text.splitlines()]
    starts = [i for i, l in enumerate(lines) if 'OWNER STATEMENT' in l]
    if not starts:
        return []
    blocks = []
    for n, start in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(lines)
        # The company header sits a few lines above OWNER STATEMENT; it
        # belongs to this block, not to the end of the previous one.
        blocks.append(lines[start:end])
    # Trim the next block's company header off the end of each block.
    for b in blocks:
        while b and (not b[-1].strip() or b[-1].strip().startswith(COMPANY_LINES)):
            b.pop()
    return blocks


def _is_footer_or_noise(stripped: str) -> bool:
    return (not stripped or PAGE_FOOTER_RE.match(stripped) is not None
            or stripped.startswith(COMPANY_LINES))


def _next_content(lines: List[str], i: int) -> str:
    for j in range(i + 1, min(i + 8, len(lines))):
        s = lines[j].strip()
        if s and not _is_footer_or_noise(s):
            return s
    return ''


def parse_block(block: List[str]) -> ParsedStatement:
    header = block[0]
    recipient = header.split('OWNER STATEMENT')[0].strip()
    period = None
    generated = None
    summary = {}
    body_start = None
    for i, line in enumerate(block):
        if period is None:
            m = PERIOD_RE.search(line)
            if m:
                period = (mdy(m.group(1)), mdy(m.group(2)))
        m = SUMMARY_RE.match(line)
        if m and body_start is None:
            summary[SUMMARY_FIELDS[m.group(1)]] = money(m.group(2))
        if m and m.group(1) == 'Due To Owner' and body_start is None:
            body_start = i + 1
        if generated is None:
            g = GENERATED_RE.search(line)
            if g:
                generated = datetime.strptime(f"{g.group(1)} {g.group(2).replace(' ', '')}", '%m/%d/%Y %I:%M%p')
    if period is None:
        raise ParseError("No report period found")
    if body_start is None:
        body_start = len(block)

    st = ParsedStatement(format='detail', recipient=recipient,
                         period_start=period[0], period_end=period[1], generated_at=generated)
    for k, v in summary.items():
        setattr(st, k, v)
    # "Draws  -  -$2,587.50": the statement shows payouts as a negative draw.
    st.draws = -st.draws if st.draws < 0 else st.draws
    _parse_body(block[body_start:], st)
    _reconcile(st)
    return st


def _parse_body(lines: List[str], st: ParsedStatement) -> None:
    prop: Optional[PropertyPage] = None
    section = ''
    category = ''
    rows: List[_Row] = []
    pending: List[str] = []        # comment lines not yet given to a row
    last_row: Optional[_Row] = None
    blank_since_row = False
    in_unpaid = False

    def flush_pending_to_last():
        nonlocal pending
        if last_row is not None and pending:
            last_row.trailing.extend(pending)
        pending = []

    for i, raw in enumerate(lines):
        stripped = raw.strip()
        if _is_footer_or_noise(stripped):
            if not stripped and last_row is not None and not pending:
                blank_since_row = True
            continue
        if in_unpaid:
            continue
        indent = len(raw) - len(raw.lstrip(' '))

        if stripped.startswith('Unpaid Bills') and indent == 0:
            flush_pending_to_last()
            in_unpaid = True
            continue
        if stripped.startswith('Type ') and 'Date' in stripped and 'Amount' in stripped:
            continue
        if stripped.startswith('Current') and 'Security' in stripped:
            continue
        m = RENT_DEPOSIT_RE.match(stripped)
        if m and prop is not None:
            prop.current_rent = money(m.group(1))
            if m.group(2):
                prop.deposit = money(m.group(2))
            continue
        if stripped.startswith('Deposit:') and prop is not None:
            d = DEPOSIT_ONLY_RE.search(stripped)
            if d:
                prop.deposit = money(d.group(1))
            continue

        t = TXN_RE.match(raw)
        if t and prop is not None:
            # Hand the comment lines in the gap: the first part belongs below
            # the previous row (its comment is centred on it), the rest above
            # this one.
            if last_row is not None and pending and not blank_since_row:
                want = max(len(last_row.leading) - len(last_row.trailing), 0)
                if last_row.leading and not last_row.inline_comment:
                    want = len(last_row.leading)
                take = min(want, len(pending))
                last_row.trailing.extend(pending[:take])
                pending = pending[take:]
            middle = t.group(3)
            parts = re.split(r'\s{2,}', middle.strip(), maxsplit=1)
            row = _Row(line_no=i, txn_type=t.group(1), date=t.group(2), name=parts[0],
                       inline_comment=parts[1] if len(parts) > 1 else '', amount=t.group(4),
                       section=section, category=category, leading=pending)
            pending = []
            rows.append(row)
            last_row = row
            blank_since_row = False
            prop.lines.append(row)   # replaced by LedgerLine below
            continue

        if indent >= 20 and not re.search(AMOUNT_RE + r'\s*$', stripped):
            pending.append(stripped)
            continue

        # Anything else at the left margin ends the current run of rows.
        flush_pending_to_last()
        last_row = None
        blank_since_row = False

        pt = PROPERTY_TOTAL_RE.match(stripped)
        if pt and prop is not None:
            kind, value = pt.group(1), money(pt.group(3))
            if kind == 'Income':
                prop.total_income = value
            elif kind == 'Expenses':
                prop.total_expenses = value
            elif kind == 'Equity':
                pass   # owner draws; the summary block already carries them
            else:
                prop.total_assets = value
            continue
        n = NOI_RE.match(stripped)
        if n and prop is not None:
            prop.noi = money(n.group(1))
            continue
        if stripped.startswith(('Total Net Income', 'Total Amount Due')):
            continue
        if CATEGORY_TOTAL_RE.match(stripped):
            continue
        if stripped in SECTION_WORDS:
            section = SECTION_WORDS[stripped]
            category = ''
            continue
        if indent == 0 and not re.search(r'\$[\d,]+\.\d\d', stripped):
            nxt = _next_content(lines, i)
            if nxt.startswith(('Current', 'Rent:')) or nxt in SECTION_WORDS:
                prop = PropertyPage(address=stripped)
                st.properties.append(prop)
                section, category = '', ''
                continue
            category = stripped
            continue

    flush_pending_to_last()

    for p in st.properties:
        converted = []
        for r in p.lines:
            if isinstance(r, _Row):
                comment = ' '.join(x for x in (r.leading + ([r.inline_comment] if r.inline_comment else []) + r.trailing))
                converted.append(LedgerLine(
                    section=r.section or 'income', category=r.category, txn_type=r.txn_type,
                    date=mdy(r.date), name=r.name, comment=comment, amount=money(r.amount)))
            else:
                converted.append(r)
        p.lines = [l for l in converted if l.section != 'equity']
        p.draws_only = len(p.lines) < len(converted) and not p.lines
    # Since mid-2026 a page named after the portfolio lists only the owner draw
    # checks (Equity). It is not a house.
    st.properties = [p for p in st.properties if not getattr(p, 'draws_only', False)
                     and (p.lines or p.address[:1].isdigit())]


def _reconcile(st: ParsedStatement) -> None:
    """Check the line items add up to the printed totals."""
    tol = Decimal('0.01')
    income_sum = Decimal('0')
    expense_sum = Decimal('0')
    asset_sum = Decimal('0')
    for p in st.properties:
        inc = sum((l.amount for l in p.lines if l.section == 'income'), Decimal('0'))
        exp = sum((l.amount for l in p.lines if l.section == 'expense'), Decimal('0'))
        ast = sum((l.amount for l in p.lines if l.section == 'asset'), Decimal('0'))
        income_sum += inc
        expense_sum += exp
        asset_sum += ast
        if p.total_income is not None and abs(inc - p.total_income) > tol:
            st.problems.append(f"{p.address}: income lines {inc} != total {p.total_income}")
        if p.total_expenses is not None and abs(exp - p.total_expenses) > tol:
            st.problems.append(f"{p.address}: expense lines {exp} != total {p.total_expenses}")
        if p.total_assets is not None and abs(ast - p.total_assets) > tol:
            st.problems.append(f"{p.address}: asset lines {ast} != total {p.total_assets}")
    if not st.properties and (st.income or st.expenses or st.mgmt_fees):
        st.problems.append("no property pages found although the summary shows activity")
    if st.properties:
        if abs(income_sum - st.income) > tol:
            st.problems.append(f"income lines {income_sum} != summary income {st.income}")
        if abs(expense_sum - (st.expenses + st.mgmt_fees)) > tol:
            st.problems.append(f"expense lines {expense_sum} != summary expenses+fees {st.expenses + st.mgmt_fees}")
    roll = (st.previous_balance + st.income - st.expenses - st.mgmt_fees - st.assets
            + st.contributions - st.draws)
    if abs(roll - st.ending_balance) > tol:
        st.problems.append(f"balance roll-forward {roll} != ending balance {st.ending_balance}")


def parse_detail_text(text: str) -> List[ParsedStatement]:
    """Every distinct statement in the text (repeated copies collapse to one)."""
    out: List[ParsedStatement] = []
    seen = set()
    for block in split_statements(text):
        st = parse_block(block)
        key = (st.period_start, st.period_end, st.previous_balance, st.ending_balance,
               st.income, tuple((p.address, len(p.lines)) for p in st.properties))
        if key in seen:
            continue
        seen.add(key)
        out.append(st)
    return out
