"""Plain data structures produced by the statement parsers."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional


@dataclass
class LedgerLine:
    """One transaction row on a property page."""
    section: str              # income | expense | asset
    category: str             # Rent, Late Fee, Repairs, Management Fees, ...
    txn_type: str             # Charge, Bill, Journal Entry, Check, ...
    date: date
    name: str                 # ledger key for income ("3403LADUEST:Henderson, Q._1"), vendor for bills
    comment: str
    amount: Decimal

    @property
    def tenant_key(self) -> Optional[str]:
        """Tenant part of an income ledger key ("Henderson, Q._1"), if any."""
        if ':' in self.name:
            return self.name.split(':', 1)[1].strip()
        return None


@dataclass
class PropertyPage:
    address: str
    current_rent: Optional[Decimal] = None
    deposit: Optional[Decimal] = None
    total_income: Optional[Decimal] = None
    total_expenses: Optional[Decimal] = None
    total_assets: Optional[Decimal] = None
    noi: Optional[Decimal] = None
    lines: List[LedgerLine] = field(default_factory=list)


@dataclass
class OwnerPayment:
    """A dated payment to the owner (only the 2013-2017 summary format lists these)."""
    date: date
    amount: Decimal
    description: str = ''


@dataclass
class ParsedStatement:
    format: str                          # detail | summary | investor
    recipient: str
    period_start: date
    period_end: date
    generated_at: Optional[datetime] = None
    previous_balance: Decimal = Decimal('0')
    income: Decimal = Decimal('0')
    expenses: Decimal = Decimal('0')
    mgmt_fees: Decimal = Decimal('0')
    assets: Decimal = Decimal('0')
    total: Decimal = Decimal('0')
    contributions: Decimal = Decimal('0')
    draws: Decimal = Decimal('0')        # positive = paid out to the owner
    ending_balance: Decimal = Decimal('0')
    portfolio_minimum: Decimal = Decimal('0')
    unpaid_bills: Decimal = Decimal('0')
    due_to_owner: Decimal = Decimal('0')
    properties: List[PropertyPage] = field(default_factory=list)
    owner_payments: List[OwnerPayment] = field(default_factory=list)
    tenants_by_unit: dict = field(default_factory=dict)   # summary format: unit -> (lease name, rent)
    lease_starts: dict = field(default_factory=dict)      # summary format: unit -> lease start date
    problems: List[str] = field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        """An empty shell statement (Walter / Miskatonic after the transfers)."""
        return not self.properties and self.previous_balance == 0 and self.ending_balance == 0 \
            and self.income == 0 and self.draws == 0

    @property
    def reconciled(self) -> bool:
        return not self.problems
