"""Database schema.

Source tables (documents, statements, ledger_lines, emails, manual events)
hold what was received. Tenancies, payment problems, vacancies, balances and
distributions are derived from them in memory by tracker.derive, so
improving a rule never needs a re-extraction.
"""
from __future__ import annotations

import os
from datetime import datetime

from sqlalchemy import (Boolean, Date, DateTime, ForeignKey, Integer, LargeBinary, Numeric, String, Text,
                        UniqueConstraint, create_engine)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

Money = Numeric(12, 2)


class Base(DeclarativeBase):
    pass


class Document(Base):
    __tablename__ = 'documents'
    id: Mapped[int] = mapped_column(primary_key=True)
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    filename: Mapped[str] = mapped_column(String(500))
    source: Mapped[str] = mapped_column(String(50))            # email | folder | upload
    source_ref: Mapped[str | None] = mapped_column(String(500))
    received_at: Mapped[datetime | None] = mapped_column(DateTime)
    size: Mapped[int] = mapped_column(Integer, default=0)
    format: Mapped[str | None] = mapped_column(String(30))     # detail | summary | investor | tax_form | unknown
    status: Mapped[str] = mapped_column(String(30))            # parsed | unreconciled | empty | duplicate | unsupported | error
    problems: Mapped[str | None] = mapped_column(Text)
    parser_version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    statements = relationship('Statement', back_populates='document')


class Statement(Base):
    __tablename__ = 'statements'
    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey('documents.id'))
    fingerprint: Mapped[str] = mapped_column(String(64), unique=True)
    portfolio: Mapped[str | None] = mapped_column(String(30), index=True)
    recipient: Mapped[str] = mapped_column(String(200), default='')
    format: Mapped[str] = mapped_column(String(20))
    period_start: Mapped[datetime] = mapped_column(Date)
    period_end: Mapped[datetime] = mapped_column(Date)
    generated_at: Mapped[datetime | None] = mapped_column(DateTime)
    previous_balance = mapped_column(Money)
    income = mapped_column(Money)
    expenses = mapped_column(Money)
    mgmt_fees = mapped_column(Money)
    assets = mapped_column(Money)
    contributions = mapped_column(Money)
    draws = mapped_column(Money)
    ending_balance = mapped_column(Money)
    unpaid_bills = mapped_column(Money)
    reconciled: Mapped[bool] = mapped_column(Boolean, default=True)
    problems: Mapped[str | None] = mapped_column(Text)
    document = relationship('Document', back_populates='statements')
    properties = relationship('StatementProperty', back_populates='statement', cascade='all, delete-orphan')

    @property
    def days(self) -> int:
        return (self.period_end - self.period_start).days + 1


class StatementProperty(Base):
    __tablename__ = 'statement_properties'
    id: Mapped[int] = mapped_column(primary_key=True)
    statement_id: Mapped[int] = mapped_column(ForeignKey('statements.id'), index=True)
    property_key: Mapped[str] = mapped_column(String(60), index=True)
    address: Mapped[str] = mapped_column(String(200))
    current_rent = mapped_column(Money, nullable=True)
    deposit = mapped_column(Money, nullable=True)
    total_income = mapped_column(Money, nullable=True)
    total_expenses = mapped_column(Money, nullable=True)
    lease_name: Mapped[str | None] = mapped_column(String(200))   # summary format
    lease_start = mapped_column(Date, nullable=True)                # summary format
    statement = relationship('Statement', back_populates='properties')


class LedgerLine(Base):
    __tablename__ = 'ledger_lines'
    id: Mapped[int] = mapped_column(primary_key=True)
    statement_id: Mapped[int] = mapped_column(ForeignKey('statements.id'), index=True)
    portfolio: Mapped[str | None] = mapped_column(String(30), index=True)
    property_key: Mapped[str] = mapped_column(String(60), index=True)
    section: Mapped[str] = mapped_column(String(10))
    category: Mapped[str] = mapped_column(String(100), default='')
    txn_type: Mapped[str] = mapped_column(String(40))
    date = mapped_column(Date, index=True)
    name: Mapped[str] = mapped_column(String(200), default='')
    tenant_key: Mapped[str | None] = mapped_column(String(120))
    comment: Mapped[str] = mapped_column(Text, default='')
    amount = mapped_column(Money)
    # Same transaction on a monthly and an annual statement -> same fingerprint.
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)


class OwnerPayment(Base):
    __tablename__ = 'owner_payments'
    id: Mapped[int] = mapped_column(primary_key=True)
    statement_id: Mapped[int] = mapped_column(ForeignKey('statements.id'), index=True)
    portfolio: Mapped[str | None] = mapped_column(String(30))
    date = mapped_column(Date)
    amount = mapped_column(Money)


class Email(Base):
    __tablename__ = 'emails'
    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[str] = mapped_column(String(300), unique=True)
    sender: Mapped[str] = mapped_column(String(300), default='')
    recipients: Mapped[str] = mapped_column(Text, default='')
    subject: Mapped[str] = mapped_column(String(500), default='')
    date: Mapped[datetime | None] = mapped_column(DateTime)
    kind: Mapped[str] = mapped_column(String(30))   # statement | published_notice | deposit_notice | update | other
    status: Mapped[str] = mapped_column(String(30))  # done | needs_review | error
    summary: Mapped[str | None] = mapped_column(Text)
    body: Mapped[str | None] = mapped_column(Text)
    portfolio: Mapped[str | None] = mapped_column(String(30))
    amount = mapped_column(Money, nullable=True)


class Event(Base):
    """Something that happened at a property, taken from an email or added by
    hand. (Events read off the ledger are derived in tracker.derive.)"""
    __tablename__ = 'events'
    id: Mapped[int] = mapped_column(primary_key=True)
    property_key: Mapped[str | None] = mapped_column(String(60), index=True)
    portfolio: Mapped[str | None] = mapped_column(String(30))
    date = mapped_column(Date, index=True)
    type: Mapped[str] = mapped_column(String(30))
    title: Mapped[str] = mapped_column(String(300))
    detail: Mapped[str | None] = mapped_column(Text)
    amount = mapped_column(Money, nullable=True)
    source_type: Mapped[str] = mapped_column(String(20))   # ledger | statement | email | manual
    source_id: Mapped[int | None] = mapped_column(Integer)


class Blob(Base):
    """Original PDF bytes (the default store; see tracker.storage)."""
    __tablename__ = 'blobs'
    sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    data: Mapped[bytes] = mapped_column(LargeBinary)


class Summary(Base):
    """A monthly letter written by Claude, kept so it is not rewritten on every view."""
    __tablename__ = 'summaries'
    id: Mapped[int] = mapped_column(primary_key=True)
    month: Mapped[str] = mapped_column(String(7), index=True)
    audience: Mapped[str] = mapped_column(String(20))
    facts_hash: Mapped[str] = mapped_column(String(64))
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Property(Base):
    __tablename__ = 'houses'   # not 'properties': the v1 tables may share the database
    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    address: Mapped[str] = mapped_column(String(200))
    __table_args__ = (UniqueConstraint('key'),)


def database_url() -> str:
    url = os.getenv('DATABASE_URL', 'sqlite:///data/tracker.db')
    # SQLAlchemy 2.1 defaults postgresql:// to psycopg 3; requirements ship psycopg2.
    for prefix in ('postgres://', 'postgresql://'):
        if url.startswith(prefix):
            url = 'postgresql+psycopg2://' + url[len(prefix):]
    return url


_engine = None
_Session = None


def engine():
    global _engine, _Session
    if _engine is None:
        url = database_url()
        if url.startswith('sqlite:///'):
            os.makedirs(os.path.dirname(url[len('sqlite:///'):]) or '.', exist_ok=True)
        _engine = create_engine(url, future=True)
        Base.metadata.create_all(_engine)
        _Session = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def session():
    engine()
    return _Session()


def reset_engine(url: str | None = None):
    """Point the module at another database (tests)."""
    global _engine, _Session
    if url:
        os.environ['DATABASE_URL'] = url
    _engine = None
    _Session = None
    return engine()
