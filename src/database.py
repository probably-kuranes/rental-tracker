"""
Database Models and Connection

Defines the database schema and provides connection management.
Uses SQLAlchemy for ORM and supports both SQLite (dev) and PostgreSQL (prod).
"""

import os
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    create_engine, Column, Integer, String, Float, DateTime,
    ForeignKey, Text, Boolean, Date
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker, Session
from sqlalchemy.pool import StaticPool


Base = declarative_base()


class Owner(Base):
    """Property owner record."""
    __tablename__ = 'owners'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False, unique=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    properties = relationship("Property", back_populates="owner")
    monthly_reports = relationship("MonthlyReport", back_populates="owner")
    
    def __repr__(self):
        return f"<Owner(id={self.id}, name='{self.name}')>"


class Property(Base):
    """Rental property record."""
    __tablename__ = 'properties'
    
    id = Column(Integer, primary_key=True)
    owner_id = Column(Integer, ForeignKey('owners.id'), nullable=False)
    address = Column(String(255), nullable=False)
    current_rent = Column(Float, default=0)
    security_deposit = Column(Float, default=0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    owner = relationship("Owner", back_populates="properties")
    monthly_records = relationship("PropertyMonth", back_populates="property")
    
    def __repr__(self):
        return f"<Property(id={self.id}, address='{self.address}')>"


class MonthlyReport(Base):
    """Portfolio-level monthly report."""
    __tablename__ = 'monthly_reports'
    
    id = Column(Integer, primary_key=True)
    owner_id = Column(Integer, ForeignKey('owners.id'), nullable=False)
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)
    
    # Financial summary
    previous_balance = Column(Float, default=0)
    income = Column(Float, default=0)
    expenses = Column(Float, default=0)
    mgmt_fees = Column(Float, default=0)
    total = Column(Float, default=0)
    contributions = Column(Float, default=0)
    draws = Column(Float, default=0)
    ending_balance = Column(Float, default=0)
    portfolio_minimum = Column(Float, default=0)
    unpaid_bills = Column(Float, default=0)
    due_to_owner = Column(Float, default=0)
    
    # Metadata
    source_file = Column(String(500))
    imported_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    owner = relationship("Owner", back_populates="monthly_reports")
    property_months = relationship("PropertyMonth", back_populates="monthly_report")
    
    def __repr__(self):
        return f"<MonthlyReport(id={self.id}, period={self.period_start} to {self.period_end})>"


class PropertyMonth(Base):
    """Property-level monthly record."""
    __tablename__ = 'property_months'
    
    id = Column(Integer, primary_key=True)
    property_id = Column(Integer, ForeignKey('properties.id'), nullable=False)
    monthly_report_id = Column(Integer, ForeignKey('monthly_reports.id'), nullable=False)
    
    # Financial data
    total_income = Column(Float, default=0)
    total_expenses = Column(Float, default=0)
    mgmt_fees = Column(Float, default=0)
    repairs = Column(Float, default=0)
    noi = Column(Float, default=0)
    
    # Calculated metrics (stored for convenience)
    noi_margin = Column(Float, default=0)  # NOI / Income
    expense_ratio = Column(Float, default=0)  # Expenses / Income
    
    # Relationships
    property = relationship("Property", back_populates="monthly_records")
    monthly_report = relationship("MonthlyReport", back_populates="property_months")
    expenses = relationship("Expense", back_populates="property_month")
    
    def __repr__(self):
        return f"<PropertyMonth(id={self.id}, property_id={self.property_id}, noi={self.noi})>"


class Expense(Base):
    """Individual expense line item."""
    __tablename__ = 'expenses'
    
    id = Column(Integer, primary_key=True)
    property_month_id = Column(Integer, ForeignKey('property_months.id'), nullable=False)
    
    date = Column(Date)
    vendor = Column(String(255))
    description = Column(Text)
    amount = Column(Float, nullable=False)
    category = Column(String(100))  # HVAC, Plumbing, Electrical, etc.
    
    # Relationships
    property_month = relationship("PropertyMonth", back_populates="expenses")
    
    def __repr__(self):
        return f"<Expense(id={self.id}, amount={self.amount}, category='{self.category}')>"


class ImportLog(Base):
    """Record of import operations."""
    __tablename__ = 'import_logs'
    
    id = Column(Integer, primary_key=True)
    email_id = Column(String(255))  # Gmail message ID
    filename = Column(String(500))
    status = Column(String(50))  # success, failed, skipped
    records_imported = Column(Integer, default=0)
    error_message = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f"<ImportLog(id={self.id}, status='{self.status}')>"


class Database:
    """
    Database connection manager.
    
    Usage:
        db = Database()
        with db.session() as session:
            owners = session.query(Owner).all()
    """
    
    def __init__(self, url: Optional[str] = None):
        """
        Initialize database connection.
        
        Args:
            url: Database URL. If not provided, reads from DATABASE_URL
                 environment variable. Defaults to SQLite if not set.
        """
        self.url = url or os.getenv('DATABASE_URL', 'sqlite:///rental_tracker.db')
        
        # SQLite needs special handling for concurrent access
        if self.url.startswith('sqlite'):
            self.engine = create_engine(
                self.url,
                connect_args={'check_same_thread': False},
                poolclass=StaticPool
            )
        else:
            self.engine = create_engine(self.url)
        
        self._SessionFactory = sessionmaker(bind=self.engine)
    
    def create_tables(self) -> None:
        """Create all tables in the database."""
        Base.metadata.create_all(self.engine)
    
    def drop_tables(self) -> None:
        """Drop all tables. Use with caution!"""
        Base.metadata.drop_all(self.engine)
    
    def session(self) -> Session:
        """
        Get a new database session.
        
        Usage:
            with db.session() as session:
                # do work
                session.commit()
        """
        return self._SessionFactory()


# Convenience function for getting a database instance
_default_db: Optional[Database] = None


def get_database() -> Database:
    """Get the default database instance."""
    global _default_db
    if _default_db is None:
        _default_db = Database()
    return _default_db


# CLI entry point for testing
if __name__ == '__main__':
    import sys
    
    db = Database()
    
    if len(sys.argv) > 1 and sys.argv[1] == '--create':
        print(f"Creating tables in: {db.url}")
        db.create_tables()
        print("Tables created successfully!")
    elif len(sys.argv) > 1 and sys.argv[1] == '--drop':
        confirm = input("This will DELETE ALL DATA. Type 'yes' to confirm: ")
        if confirm == 'yes':
            db.drop_tables()
            print("Tables dropped.")
        else:
            print("Cancelled.")
    else:
        print("Database module")
        print(f"URL: {db.url}")
        print("\nTables defined:")
        for table in Base.metadata.tables:
            print(f"  - {table}")
        print("\nUsage:")
        print("  python database.py --create  # Create tables")
        print("  python database.py --drop    # Drop tables (DESTRUCTIVE)")
