"""Tests for the v2 tracker (tracker/). Fixtures are made-up statements in
Propertyware's layout; no real tenant data lives in the repo."""
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from tracker import db
from tracker.parsing import detect_format, parse_text
from tracker.parsing.detail import parse_detail_text
from tracker.portfolios import portfolio_for, property_key

FIXTURES = Path(__file__).parent / 'fixtures'
DETAIL = (FIXTURES / 'detail_month.txt').read_text()

SUMMARY = """
                                                          Mid South Best Rentals, Inc
                                                          46 N. Flicker Street                                   Owner Statement
                                                          Memphis , TN 38104                                    Property Summary

             Jane Owner                                                                      This report reflects all transactions between
             1 Main St                                                                       12/01/2016 and 11/30/2017

                                   Starting
                                                          Income Management Fees             Expenses        Owner Draws        Ending Balance
                                   Balance
12/01/2016 -
                                $1,000.00 +           $16,000.00 -        $1,600.00 -       $1,300.00 -        $13,100.00 =           $1,000.00
11/30/2017

Scheduled Rent by Unit

Property/Unit                                         Lease Name                                                                        Amount
Argonne3934                                           Doe - Roe                                                                         $725.00
Warner1743                                            Poe, A.                                                                           $675.00
Total                                                                                                                                 $1,400.00

Operating Income

Lease                                              Description             Total Paid             Management Fees           Amount To Owner
Argonne3934 / 10/01/2013                           Rent                     $8,700.00                     $870.00                     $7,830.00
Warner1743 / 06/13/2014                            Rent                     $7,300.00                     $730.00                     $6,570.00

Operating Expenses

Date           Property/Unit Description                      Payee                   Comments                                 Amount
01/27/2017 Argonne3934 Repairs                                Midsouth Renovations    Plumbing invoice                       $1,100.82
                                                                                                     Total for Argonne3934   $1,100.82
                                                              Midsouth Homebuyers
11/17/2017 Warner1743               Legal and Professional                            1743 Warner - eviction filling fee       $199.18
                                                              Inc
                                                                                                      Total for Warner1743     $199.18
Total Operating Expenses                                                                                                      $1,300.00

Payments to Owner

Date                                  Transaction                                                                              Amount
12/06/2016                            EPay Payment to Jane Owner                                                              $6,000.00
06/06/2017                            EPay Payment to Jane Owner                                                              $7,100.00
Total                                                                                                                        $13,100.00
"""


@pytest.fixture
def database(tmp_path, monkeypatch):
    monkeypatch.delenv('BLOB_DIR', raising=False)
    db.reset_engine(f"sqlite:///{tmp_path / 'test.db'}")
    yield
    db.reset_engine()


# -- parsing ----------------------------------------------------------------------

def test_detail_statement_reconciles():
    (st,) = parse_detail_text(DETAIL)
    assert st.reconciled, st.problems
    assert (st.period_start, st.period_end) == (date(2025, 8, 1), date(2025, 8, 31))
    assert st.draws == Decimal('1000.00')          # printed as "- -$1,000.00"
    assert st.ending_balance == Decimal('1355.01')
    assert [p.address for p in st.properties] == ['3642 Windermere', '3403 Ladue St']
    assert st.properties[0].current_rent == Decimal('900.00')


def test_wrapped_comments_belong_to_their_row():
    (st,) = parse_detail_text(DETAIL)
    rows = st.properties[0].lines
    returned = [l for l in rows if l.txn_type == 'Journal Entry']
    assert all(l.comment == 'Returned Payment Adjustment' for l in returned)
    paid = [l for l in rows if l.category == 'Rent' and l.txn_type == 'Charge']
    assert [l.comment for l in paid] == ['', 'RentMoney - Jane Doe']
    assert paid[0].tenant_key == 'Doe, J._1'


def test_rows_continue_across_a_page_break():
    (st,) = parse_detail_text(DETAIL)
    ladue = st.properties[1]
    assert [l.amount for l in ladue.lines if l.section == 'income'] == [Decimal('100.00'), Decimal('903.00')]
    assert ladue.lines[-1].category == 'Repairs - Get Ready'


def test_repeated_copies_collapse_to_one():
    doubled = DETAIL + '\n' + DETAIL.replace('Jane Owner', 'Other Recipient - T')
    assert len(parse_detail_text(doubled)) == 1


def test_a_wrong_total_is_reported():
    broken = DETAIL.replace('Total Income for 3642 Windermere                                                                  $884.50',
                            'Total Income for 3642 Windermere                                                                  $984.50')
    (st,) = parse_detail_text(broken)
    assert not st.reconciled
    assert any('3642 Windermere' in p for p in st.problems)


def test_summary_format():
    assert detect_format(SUMMARY) == 'summary'
    fmt, (st,) = parse_text(SUMMARY)
    assert st.reconciled, st.problems
    assert st.income == Decimal('16000.00') and st.draws == Decimal('13100.00')
    assert st.lease_starts['Argonne3934'] == date(2013, 10, 1)
    assert st.tenants_by_unit['Warner1743'] == ('Poe, A.', Decimal('675.00'))
    warner = next(p for p in st.properties if p.address == 'Warner1743')
    legal = [l for l in warner.lines if l.txn_type == 'Bill']
    assert legal[0].category == 'Legal and Professional' and 'eviction' in legal[0].comment
    assert len(st.owner_payments) == 2


def test_property_keys_and_portfolios():
    for a in ('3403 Ladue St', 'Ladue3403', '3403LADUEST'):
        assert property_key(a) == '3403-ladue'
    assert property_key('3642WINDERME') == '3642-windermere'
    assert property_key('1166 S.Barksdale') == '1166-barksdale'
    assert portfolio_for(['3642-windermere', '3403-ladue']) == 'torgo'
    assert portfolio_for(['3403-ladue', '4333-melwood']) == 'walter'
    assert portfolio_for([], 'Walter Mascari - T') == 'torgo'


# -- ingest and derivation ------------------------------------------------------------

def test_ingest_dedupes_and_derives_events(database):
    from tracker.derive import build_world
    from tracker.ingest import ingest_text

    first = ingest_text(DETAIL, 'a.txt')
    again = ingest_text(DETAIL + '\n', 'b.txt')          # same statement, different file
    assert first.status == 'parsed'
    assert again.status == 'duplicate'

    w = build_world()
    assert w.properties['3642-windermere']['portfolio'] == 'torgo'
    types = {(e.property_key, e.type) for e in w.events}
    assert ('3642-windermere', 'returned') in types
    assert ('3403-ladue', 'make_ready') in types
    returned = [e for e in w.events if e.type == 'returned']
    assert len(returned) == 1 and returned[0].amount == Decimal('1000.50')
    assert w.balances['torgo'][-1] == (date(2025, 8, 31), Decimal('1355.01'))
    assert [d.amount for d in w.distributions['torgo']] == [Decimal('1000.00')]
    tenants = {t.property_key: t.tenant for ts in w.tenancies.values() for t in ts}
    assert tenants['3642-windermere'] == 'Doe, J.'


def test_views_build(database):
    from tracker import views
    from tracker.derive import build_world
    from tracker.ingest import ingest_text

    ingest_text(DETAIL, 'a.txt')
    w = build_world()
    status = views.status(w, date(2025, 9, 10))
    (torgo,) = status['portfolios']
    assert torgo['balance'] == 1355.01
    assert {h['address'] for h in torgo['houses']} == {'3642 Windermere', '3403 Ladue St'}
    assert views.timeline(w, date(2025, 9, 10))['groups'][0]['key'] == 'torgo'
    facts = views.month_facts(w, '2025-08', ['torgo'])
    assert facts['portfolios'][0]['statement']['paid_out_to_owner'] == 1000.0


def test_mail_handling_without_claude(database, monkeypatch):
    from datetime import datetime
    from tracker import mailbox
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    monkeypatch.delenv('ANTHROPIC_AUTH_TOKEN', raising=False)

    def msg(subject, body='', to='torgoproperties@runbox.com'):
        return mailbox.Message(uid=b'1', message_id=f'<{subject}@x>', sender='connect@midsouthbestrentals.com',
                               recipients=to, subject=subject, date=datetime(2026, 3, 1), body=body)

    assert mailbox.handle(msg('Pending Deposit to Account for Torgo', 'Amount $1,297.75')) == mailbox.PROCESSED
    assert mailbox.handle(msg('Vandalism at 4333 Melwood', 'Back door broken')) == mailbox.NEEDS_REVIEW
    # The same message again is recognised by its Message-ID.
    assert mailbox.handle(msg('Vandalism at 4333 Melwood', 'Back door broken')) == mailbox.PROCESSED
    with db.session() as s:
        from sqlalchemy import select
        rows = {e.kind: e for e in s.scalars(select(db.Email))}
    assert rows['deposit_notice'].amount == Decimal('1297.75')
    assert rows['deposit_notice'].portfolio == 'torgo'
    assert rows['update'].status == 'needs_review'


def test_summary_copies_for_two_recipients_collapse():
    doubled = SUMMARY + '\n' + SUMMARY.replace('Jane Owner', 'Owner Properties LLC')
    fmt, sts = parse_text(doubled)
    assert len(sts) == 1 and sts[0].reconciled, sts[0].problems
    assert len(sts[0].owner_payments) == 2


def test_owner_draw_page_is_not_a_house():
    page = """
Example Properties LLC
Income
                                                                            Original
Type                              Date    Name                                                  Paid Amount
                                                                            Amount
Total Income for Example Properties LLC                                                               $0.00
Expenses
Total Expenses for Example Properties LLC                                                                 $0.00
Net Operating Income                                                                                      $0.00
 Equity
Owner Draw
  Check                           08/09/2025 Example Properties LLC          $1,000.00               -$1,000.00
Total Owner Draw                                                                                     -$1,000.00
Total Equity for Example Properties LLC                                                              -$1,000.00

"""
    marker = '3642 Windermere\n'
    text = DETAIL.replace(marker, page + marker, 1)
    (st,) = parse_detail_text(text)
    assert st.reconciled, st.problems
    assert [p.address for p in st.properties] == ['3642 Windermere', '3403 Ladue St']


# -- logins, follow-up checks and monthly emails ----------------------------------------

def test_second_login(database, monkeypatch):
    from fastapi.testclient import TestClient
    from tracker.app import app
    monkeypatch.setenv('APP_PASSWORD', 'first-pass')
    monkeypatch.setenv('APP_USERS', 'second:second-pass')
    c = TestClient(app)
    assert c.get('/api/emails/1', auth=('david', 'first-pass')).status_code != 401
    assert c.get('/api/emails/1', auth=('second', 'second-pass')).status_code != 401
    assert c.get('/api/emails/1', auth=('second', 'first-pass')).status_code == 401


def test_follow_up_checks(database):
    from tracker import views
    from tracker.derive import build_world
    from tracker.ingest import ingest_text
    ingest_text(DETAIL, 'a.txt')
    data = views.summary(build_world(), '2025-08', 'manager')
    assert any('Payment returned' in c for c in data['facts']['checks'])


def test_monthly_summaries_sent_once_when_complete(database, monkeypatch):
    from tracker import llm, notify
    from tracker.ingest import ingest_text
    ingest_text(DETAIL, 'a.txt')
    monkeypatch.setattr(llm, 'available', lambda: True)
    monkeypatch.setattr(llm, 'write_summary', lambda facts, audience: f"{audience} letter")
    sent = []
    fake = lambda to, subject, text: sent.append((to, subject, text))

    assert notify.run(date(2025, 9, 10), send=fake) == {'skipped': 'no recipients set'}
    monkeypatch.setenv('SUMMARY_OWNER_TO', 'owner@example.com')
    monkeypatch.setenv('SUMMARY_FAMILY_TO', 'family@example.com')
    assert notify.run(date(2025, 9, 10), send=fake) == {'sent': 2}
    assert sorted(sent) == [('family@example.com', 'Torgo houses, August 2025', 'family letter'),
                            ('owner@example.com', 'Rentals, August 2025', 'owner letter')]
    assert notify.run(date(2025, 9, 10), send=fake) == {}          # not sent twice
    assert notify.run(date(2025, 10, 10), send=fake) == {}         # September not complete
