"""
Reports Module

Queries the database and generates summary reports.
"""

from datetime import datetime, date
from typing import List, Optional, Dict, Any
from dataclasses import dataclass

from sqlalchemy import func, desc

from .database import (
    Database, get_database, Owner, Property, MonthlyReport,
    PropertyMonth, Expense
)


@dataclass
class PropertySummary:
    """Summary of a property's performance."""
    address: str
    owner_name: str
    current_rent: float
    total_income: float
    total_expenses: float
    total_repairs: float
    noi: float
    noi_margin: float
    months_tracked: int


@dataclass
class PortfolioSummary:
    """Summary of entire portfolio."""
    total_properties: int
    total_income: float
    total_expenses: float
    total_noi: float
    average_noi_margin: float
    total_repairs: float
    properties_with_repairs: int


class ReportGenerator:
    """
    Generates reports from the rental property database.
    
    Usage:
        reports = ReportGenerator()
        summary = reports.get_current_month_summary()
        print(f"Total NOI: ${summary.total_noi:,.2f}")
    """
    
    def __init__(self, db: Optional[Database] = None):
        """
        Initialize report generator.
        
        Args:
            db: Database instance. Uses default if not provided.
        """
        self.db = db or get_database()
    
    def get_latest_report_period(self) -> Optional[tuple]:
        """Get the most recent report period (start, end)."""
        session = self.db.session()
        try:
            report = session.query(MonthlyReport).order_by(
                desc(MonthlyReport.period_end)
            ).first()
            
            if report:
                return (report.period_start, report.period_end)
            return None
        finally:
            session.close()
    
    def get_portfolio_summary(
        self,
        period_start: Optional[date] = None,
        period_end: Optional[date] = None
    ) -> PortfolioSummary:
        """
        Get portfolio-level summary for a period.
        
        Args:
            period_start: Start of period (defaults to latest)
            period_end: End of period (defaults to latest)
            
        Returns:
            PortfolioSummary dataclass
        """
        session = self.db.session()
        try:
            # Get period if not specified
            if not period_start or not period_end:
                latest = self.get_latest_report_period()
                if latest:
                    period_start, period_end = latest
                else:
                    return PortfolioSummary(0, 0, 0, 0, 0, 0, 0)
            
            # Query property months for this period
            query = session.query(PropertyMonth).join(MonthlyReport).filter(
                MonthlyReport.period_start == period_start,
                MonthlyReport.period_end == period_end
            )
            
            property_months = query.all()
            
            if not property_months:
                return PortfolioSummary(0, 0, 0, 0, 0, 0, 0)
            
            total_income = sum(pm.total_income for pm in property_months)
            total_expenses = sum(pm.total_expenses for pm in property_months)
            total_noi = sum(pm.noi for pm in property_months)
            total_repairs = sum(pm.repairs for pm in property_months)
            
            avg_margin = total_noi / total_income if total_income > 0 else 0
            props_with_repairs = sum(1 for pm in property_months if pm.repairs > 0)
            
            return PortfolioSummary(
                total_properties=len(property_months),
                total_income=total_income,
                total_expenses=total_expenses,
                total_noi=total_noi,
                average_noi_margin=avg_margin,
                total_repairs=total_repairs,
                properties_with_repairs=props_with_repairs
            )
        finally:
            session.close()
    
    def get_property_summaries(
        self,
        period_start: Optional[date] = None,
        period_end: Optional[date] = None,
        order_by: str = 'noi'
    ) -> List[PropertySummary]:
        """
        Get summaries for all properties in a period.
        
        Args:
            period_start: Start of period
            period_end: End of period
            order_by: Sort field ('noi', 'income', 'expenses', 'repairs')
            
        Returns:
            List of PropertySummary dataclasses
        """
        session = self.db.session()
        try:
            if not period_start or not period_end:
                latest = self.get_latest_report_period()
                if latest:
                    period_start, period_end = latest
                else:
                    return []
            
            query = session.query(
                PropertyMonth, Property, Owner
            ).join(
                Property, PropertyMonth.property_id == Property.id
            ).join(
                Owner, Property.owner_id == Owner.id
            ).join(
                MonthlyReport, PropertyMonth.monthly_report_id == MonthlyReport.id
            ).filter(
                MonthlyReport.period_start == period_start,
                MonthlyReport.period_end == period_end
            )
            
            results = query.all()
            
            summaries = []
            for pm, prop, owner in results:
                summaries.append(PropertySummary(
                    address=prop.address,
                    owner_name=owner.name,
                    current_rent=prop.current_rent,
                    total_income=pm.total_income,
                    total_expenses=pm.total_expenses,
                    total_repairs=pm.repairs,
                    noi=pm.noi,
                    noi_margin=pm.noi_margin,
                    months_tracked=1  # Could calculate historical
                ))
            
            # Sort
            sort_key = {
                'noi': lambda x: x.noi,
                'income': lambda x: x.total_income,
                'expenses': lambda x: x.total_expenses,
                'repairs': lambda x: x.total_repairs,
                'margin': lambda x: x.noi_margin
            }.get(order_by, lambda x: x.noi)
            
            return sorted(summaries, key=sort_key, reverse=True)
        finally:
            session.close()
    
    def get_high_expense_properties(
        self,
        expense_threshold: float = 0.3,
        period_start: Optional[date] = None,
        period_end: Optional[date] = None
    ) -> List[PropertySummary]:
        """
        Get properties with expense ratios above threshold.
        
        Args:
            expense_threshold: Expense/Income ratio threshold (default 30%)
            period_start: Start of period
            period_end: End of period
            
        Returns:
            List of properties exceeding threshold
        """
        all_props = self.get_property_summaries(period_start, period_end)
        return [p for p in all_props if p.noi_margin < (1 - expense_threshold)]
    
    def get_expense_breakdown(
        self,
        period_start: Optional[date] = None,
        period_end: Optional[date] = None
    ) -> Dict[str, float]:
        """
        Get expenses broken down by category.
        
        Args:
            period_start: Start of period
            period_end: End of period
            
        Returns:
            Dictionary of category -> total amount
        """
        session = self.db.session()
        try:
            if not period_start or not period_end:
                latest = self.get_latest_report_period()
                if latest:
                    period_start, period_end = latest
                else:
                    return {}
            
            query = session.query(
                Expense.category,
                func.sum(Expense.amount).label('total')
            ).join(
                PropertyMonth, Expense.property_month_id == PropertyMonth.id
            ).join(
                MonthlyReport, PropertyMonth.monthly_report_id == MonthlyReport.id
            ).filter(
                MonthlyReport.period_start == period_start,
                MonthlyReport.period_end == period_end
            ).group_by(Expense.category)
            
            return {row.category: row.total for row in query.all()}
        finally:
            session.close()
    
    def print_summary_report(self) -> None:
        """Print a formatted summary report to console."""
        period = self.get_latest_report_period()
        if not period:
            print("No data available.")
            return
        
        print("=" * 60)
        print(f"RENTAL PROPERTY SUMMARY REPORT")
        print(f"Period: {period[0]} to {period[1]}")
        print("=" * 60)
        
        summary = self.get_portfolio_summary()
        print(f"\nPORTFOLIO OVERVIEW")
        print(f"  Properties: {summary.total_properties}")
        print(f"  Total Income: ${summary.total_income:,.2f}")
        print(f"  Total Expenses: ${summary.total_expenses:,.2f}")
        print(f"  Total NOI: ${summary.total_noi:,.2f}")
        print(f"  Average NOI Margin: {summary.average_noi_margin:.1%}")
        print(f"  Total Repairs: ${summary.total_repairs:,.2f}")
        
        print(f"\nPROPERTY PERFORMANCE")
        print("-" * 60)
        properties = self.get_property_summaries()
        for prop in properties:
            status = "⚠️" if prop.noi_margin < 0.7 else "✓"
            print(f"  {status} {prop.address}")
            print(f"      Income: ${prop.total_income:,.2f}  "
                  f"Expenses: ${prop.total_expenses:,.2f}  "
                  f"NOI: ${prop.noi:,.2f} ({prop.noi_margin:.0%})")
        
        print(f"\nEXPENSE BREAKDOWN")
        print("-" * 60)
        expenses = self.get_expense_breakdown()
        for category, amount in sorted(expenses.items(), key=lambda x: -x[1]):
            print(f"  {category}: ${amount:,.2f}")
        
        high_expense = self.get_high_expense_properties()
        if high_expense:
            print(f"\n⚠️  ALERTS")
            print("-" * 60)
            print(f"  {len(high_expense)} properties with >30% expense ratio:")
            for prop in high_expense:
                print(f"    - {prop.address}: {1-prop.noi_margin:.0%} expense ratio")


# Convenience function
def print_summary() -> None:
    """Print summary report to console."""
    ReportGenerator().print_summary_report()


# CLI entry point
if __name__ == '__main__':
    print_summary()
