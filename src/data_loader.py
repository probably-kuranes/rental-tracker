"""
Data Loader

Takes parsed PDF data and writes it to the database.
Handles deduplication, owner/property lookup, and transaction management.
"""

from datetime import datetime
from typing import Optional

from .database import (
    Database, get_database, Owner, Property, MonthlyReport,
    PropertyMonth, Expense, ImportLog
)


def categorize_expense(description: str) -> str:
    """
    Categorize an expense based on its description.
    
    Args:
        description: Expense description text
        
    Returns:
        Category string
    """
    desc_lower = description.lower()
    
    if 'plumbing' in desc_lower or 'pipe' in desc_lower or 'drain' in desc_lower:
        return 'Plumbing'
    elif 'hvac' in desc_lower or 'heat' in desc_lower or 'air condition' in desc_lower or 'ac ' in desc_lower:
        return 'HVAC'
    elif 'electric' in desc_lower or 'wiring' in desc_lower:
        return 'Electrical'
    elif 'roof' in desc_lower or 'gutter' in desc_lower:
        return 'Roofing'
    elif 'management' in desc_lower or 'best rentals' in desc_lower:
        return 'Management Fee'
    elif 'general' in desc_lower:
        return 'General Repair'
    elif 'appliance' in desc_lower or 'refrigerator' in desc_lower or 'stove' in desc_lower:
        return 'Appliance'
    elif 'lawn' in desc_lower or 'landscap' in desc_lower or 'tree' in desc_lower:
        return 'Landscaping'
    elif 'pest' in desc_lower or 'termite' in desc_lower:
        return 'Pest Control'
    else:
        return 'Other'


def parse_date(date_str: str) -> Optional[datetime]:
    """Parse date string to datetime."""
    if not date_str:
        return None
    
    for fmt in ['%m/%d/%Y', '%Y-%m-%d', '%d/%m/%Y']:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    
    return None


class DataLoader:
    """
    Loads parsed PDF data into the database.
    
    Usage:
        loader = DataLoader()
        result = loader.load(parsed_data)
        print(f"Imported {result['properties_loaded']} properties")
    """
    
    def __init__(self, db: Optional[Database] = None):
        """
        Initialize data loader.
        
        Args:
            db: Database instance. Uses default if not provided.
        """
        self.db = db or get_database()
    
    def _get_or_create_owner(self, session, name: str) -> Owner:
        """Get existing owner or create new one."""
        owner = session.query(Owner).filter(Owner.name == name).first()
        if not owner:
            owner = Owner(name=name)
            session.add(owner)
            session.flush()  # Get the ID
        return owner
    
    def _get_or_create_property(
        self,
        session,
        owner: Owner,
        address: str,
        current_rent: float = 0,
        security_deposit: float = 0
    ) -> Property:
        """Get existing property or create new one."""
        prop = session.query(Property).filter(
            Property.owner_id == owner.id,
            Property.address == address
        ).first()
        
        if not prop:
            prop = Property(
                owner_id=owner.id,
                address=address,
                current_rent=current_rent,
                security_deposit=security_deposit
            )
            session.add(prop)
            session.flush()
        else:
            # Update rent/deposit if they've changed
            if current_rent > 0:
                prop.current_rent = current_rent
            if security_deposit > 0:
                prop.security_deposit = security_deposit
        
        return prop
    
    def _check_duplicate_report(
        self,
        session,
        owner: Owner,
        period_start: datetime,
        period_end: datetime
    ) -> bool:
        """Check if this report has already been imported."""
        existing = session.query(MonthlyReport).filter(
            MonthlyReport.owner_id == owner.id,
            MonthlyReport.period_start == period_start.date(),
            MonthlyReport.period_end == period_end.date()
        ).first()
        return existing is not None
    
    def load(
        self,
        parsed_data: dict,
        email_id: Optional[str] = None,
        skip_duplicates: bool = True
    ) -> dict:
        """
        Load parsed PDF data into the database.
        
        Args:
            parsed_data: Output from pdf_parser.parse_pdf()
            email_id: Gmail message ID for tracking
            skip_duplicates: If True, skip reports that already exist
            
        Returns:
            Dictionary with import statistics
        """
        source_file = parsed_data.get('source_file', 'unknown')
        
        stats = {
            'owners_processed': 0,
            'reports_created': 0,
            'reports_skipped': 0,
            'properties_loaded': 0,
            'expenses_loaded': 0,
            'errors': []
        }
        
        session = self.db.session()
        
        try:
            for owner_data in parsed_data.get('owners', []):
                owner_name = owner_data.get('owner_name')
                if not owner_name:
                    stats['errors'].append("Owner data missing name")
                    continue
                
                owner = self._get_or_create_owner(session, owner_name)
                stats['owners_processed'] += 1
                
                # Parse period dates
                period_start = parse_date(owner_data.get('period_start'))
                period_end = parse_date(owner_data.get('period_end'))
                
                if not period_start or not period_end:
                    stats['errors'].append(f"Invalid period dates for {owner_name}")
                    continue
                
                # Check for duplicate
                if skip_duplicates and self._check_duplicate_report(
                    session, owner, period_start, period_end
                ):
                    stats['reports_skipped'] += 1
                    continue
                
                # Create monthly report
                report = MonthlyReport(
                    owner_id=owner.id,
                    period_start=period_start.date(),
                    period_end=period_end.date(),
                    previous_balance=owner_data.get('previous_balance', 0),
                    income=owner_data.get('income', 0),
                    expenses=owner_data.get('expenses', 0),
                    mgmt_fees=owner_data.get('mgmt_fees', 0),
                    total=owner_data.get('total', 0),
                    contributions=owner_data.get('contributions', 0),
                    draws=owner_data.get('draws', 0),
                    ending_balance=owner_data.get('ending_balance', 0),
                    portfolio_minimum=owner_data.get('portfolio_minimum', 0),
                    unpaid_bills=owner_data.get('unpaid_bills_total', 0),
                    due_to_owner=owner_data.get('due_to_owner', 0),
                    source_file=source_file
                )
                session.add(report)
                session.flush()
                stats['reports_created'] += 1
                
                # Process properties
                for prop_data in owner_data.get('properties', []):
                    address = prop_data.get('address')
                    if not address:
                        continue
                    
                    prop = self._get_or_create_property(
                        session,
                        owner,
                        address,
                        current_rent=prop_data.get('current_rent', 0),
                        security_deposit=prop_data.get('security_deposit', 0)
                    )
                    
                    # Calculate metrics
                    income = prop_data.get('total_income', 0)
                    expenses = prop_data.get('total_expenses', 0)
                    noi = prop_data.get('noi', 0)
                    
                    noi_margin = noi / income if income > 0 else 0
                    expense_ratio = expenses / income if income > 0 else 0
                    
                    # Create property month record
                    prop_month = PropertyMonth(
                        property_id=prop.id,
                        monthly_report_id=report.id,
                        total_income=income,
                        total_expenses=expenses,
                        mgmt_fees=prop_data.get('mgmt_fees', 0),
                        repairs=prop_data.get('repairs', 0),
                        noi=noi,
                        noi_margin=noi_margin,
                        expense_ratio=expense_ratio
                    )
                    session.add(prop_month)
                    session.flush()
                    stats['properties_loaded'] += 1
                    
                    # Process expense details
                    for exp_data in prop_data.get('expense_details', []):
                        expense = Expense(
                            property_month_id=prop_month.id,
                            date=parse_date(exp_data.get('date')),
                            vendor=exp_data.get('vendor', ''),
                            description=exp_data.get('comment', ''),
                            amount=exp_data.get('amount', 0),
                            category=categorize_expense(exp_data.get('comment', ''))
                        )
                        session.add(expense)
                        stats['expenses_loaded'] += 1
            
            # Log the import
            import_log = ImportLog(
                email_id=email_id,
                filename=source_file,
                status='success' if not stats['errors'] else 'partial',
                records_imported=stats['properties_loaded'],
                error_message='; '.join(stats['errors']) if stats['errors'] else None
            )
            session.add(import_log)
            
            session.commit()
            
        except Exception as e:
            session.rollback()
            stats['errors'].append(str(e))
            
            # Log failed import
            try:
                import_log = ImportLog(
                    email_id=email_id,
                    filename=source_file,
                    status='failed',
                    error_message=str(e)
                )
                session.add(import_log)
                session.commit()
            except:
                pass
            
            raise
        
        finally:
            session.close()
        
        return stats


# Convenience function
def load_parsed_data(parsed_data: dict, email_id: Optional[str] = None) -> dict:
    """
    Load parsed PDF data into the database.
    
    Args:
        parsed_data: Output from pdf_parser.parse_pdf()
        email_id: Gmail message ID for tracking
        
    Returns:
        Dictionary with import statistics
    """
    loader = DataLoader()
    return loader.load(parsed_data, email_id=email_id)


# CLI entry point
if __name__ == '__main__':
    import sys
    import json
    
    if len(sys.argv) < 2:
        print("Usage: python data_loader.py <parsed_data.json>")
        print("\nLoads parsed PDF data into the database.")
        sys.exit(1)
    
    with open(sys.argv[1]) as f:
        parsed_data = json.load(f)
    
    result = load_parsed_data(parsed_data)
    print(f"Import complete:")
    print(f"  Owners processed: {result['owners_processed']}")
    print(f"  Reports created: {result['reports_created']}")
    print(f"  Reports skipped (duplicates): {result['reports_skipped']}")
    print(f"  Properties loaded: {result['properties_loaded']}")
    print(f"  Expenses loaded: {result['expenses_loaded']}")
    if result['errors']:
        print(f"  Errors: {result['errors']}")
