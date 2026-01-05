"""
PDF Parser for Mid South Best Rentals Owner Statements

Extracts portfolio summaries and property-level detail from PDF statements
using deterministic text parsing. For non-standard formats, see llm_parser.py.
"""

import subprocess
import re
from datetime import datetime
from pathlib import Path
from typing import Optional


class ParserError(Exception):
    """Raised when PDF parsing fails."""
    pass


def extract_text_from_pdf(pdf_path: str) -> str:
    """
    Extract text from PDF using pdftotext with layout preservation.
    
    Args:
        pdf_path: Path to PDF file
        
    Returns:
        Extracted text with layout preserved
        
    Raises:
        ParserError: If pdftotext fails or file not found
    """
    path = Path(pdf_path)
    if not path.exists():
        raise ParserError(f"PDF file not found: {pdf_path}")
    
    result = subprocess.run(
        ['pdftotext', '-layout', str(path), '-'],
        capture_output=True,
        text=True
    )
    
    if result.returncode != 0:
        raise ParserError(f"pdftotext failed: {result.stderr}")
    
    return result.stdout


def parse_dollar_amount(text: str) -> float:
    """
    Parse dollar amount string to float.
    
    Handles formats like: $1,234.56, -$1,234.56, ($1,234.56), 1234.56
    
    Args:
        text: Dollar amount string
        
    Returns:
        Float value
    """
    if not text:
        return 0.0
    
    cleaned = text.replace('$', '').replace(',', '').strip()
    
    if cleaned == '' or cleaned == '-':
        return 0.0
    
    # Handle parentheses for negative numbers
    if cleaned.startswith('(') and cleaned.endswith(')'):
        cleaned = '-' + cleaned[1:-1]
    
    # Handle leading minus with dollar sign like -$1,010.29
    if text.strip().startswith('-'):
        cleaned = '-' + cleaned.lstrip('-')
    
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def parse_portfolio_summary(text_block: str) -> dict:
    """
    Parse the portfolio summary section of an owner statement.
    
    Args:
        text_block: Text containing the portfolio summary
        
    Returns:
        Dictionary with owner info and financial metrics
    """
    data = {}
    
    # Extract owner name - appears on same line as OWNER STATEMENT
    owner_match = re.search(
        r'^([A-Z][a-z]+ [A-Z][a-z]+)\s+OWNER STATEMENT',
        text_block,
        re.MULTILINE
    )
    if owner_match:
        data['owner_name'] = owner_match.group(1).strip()
    else:
        # Fallback: look for name on its own line
        owner_match = re.search(r'^([A-Z][a-z]+ [A-Z][a-z]+)\s*$', text_block, re.MULTILINE)
        if owner_match:
            data['owner_name'] = owner_match.group(1).strip()
    
    # Extract report period
    period_match = re.search(
        r'Report Period:\s*(\d{2}/\d{2}/\d{4})\s*-\s*(\d{2}/\d{2}/\d{4})',
        text_block
    )
    if period_match:
        data['period_start'] = period_match.group(1)
        data['period_end'] = period_match.group(2)
    
    # Extract financial metrics
    metrics = {
        'previous_balance': r'Previous Balance\s+(-?\$?[\d,.-]+)',
        'income': r'Income\s+\+\s+(-?\$?[\d,.-]+)',
        'expenses': r'Expenses\s+-\s+(-?\$?[\d,.-]+)',
        'mgmt_fees': r'Mgmt Fees\s+-\s+(-?\$?[\d,.-]+)',
        'total': r'Total\s+(-?\$?[\d,.-]+)',
        'contributions': r'Contributions\s+\+\s+(-?\$?[\d,.-]+)',
        'draws': r'Draws\s+-\s+(-?\$?[\d,.-]+)',
        'ending_balance': r'Ending Balance\s+(-?\$?[\d,.-]+)',
        'portfolio_minimum': r'Portfolio Minimum\s+-\s+(-?\$?[\d,.-]+)',
        'unpaid_bills_total': r'Unpaid Bills\s+-\s+(-?\$?[\d,.-]+)',
        'due_to_owner': r'Due To Owner\s+(-?\$?[\d,.-]+)',
    }
    
    for key, pattern in metrics.items():
        match = re.search(pattern, text_block)
        data[key] = parse_dollar_amount(match.group(1)) if match else 0.0
    
    # Extract generation timestamp
    gen_match = re.search(
        r'Generated\s+(\d{2}/\d{2}/\d{4}),\s+(\d{1,2}:\d{2}\s+[AP]M)',
        text_block
    )
    if gen_match:
        data['generated_date'] = gen_match.group(1)
        data['generated_time'] = gen_match.group(2)
    
    return data


def parse_property_section(property_text: str) -> dict:
    """
    Parse a single property's detail section.
    
    Args:
        property_text: Text block for one property
        
    Returns:
        Dictionary with property financials and expense details
    """
    data = {}
    
    # Extract property address (first non-empty line)
    lines = property_text.strip().split('\n')
    if lines:
        data['address'] = lines[0].strip()
    
    # Extract current rent
    rent_match = re.search(r'Rent:\s*\$?([\d,.-]+)', property_text)
    if rent_match:
        data['current_rent'] = parse_dollar_amount(rent_match.group(1))
    
    # Extract security deposit
    deposit_match = re.search(r'Deposit:\s*\$?([\d,.-]+)', property_text)
    if deposit_match:
        data['security_deposit'] = parse_dollar_amount(deposit_match.group(1))
    
    # Extract totals
    income_match = re.search(r'Total Income for [^\$]+\$?([\d,.-]+)', property_text)
    if income_match:
        data['total_income'] = parse_dollar_amount(income_match.group(1))
    
    expenses_match = re.search(r'Total Expenses for [^\$]+\$?([\d,.-]+)', property_text)
    if expenses_match:
        data['total_expenses'] = parse_dollar_amount(expenses_match.group(1))
    
    mgmt_match = re.search(r'Total Management Fees\s+\$?([\d,.-]+)', property_text)
    if mgmt_match:
        data['mgmt_fees'] = parse_dollar_amount(mgmt_match.group(1))
    
    repairs_match = re.search(r'Total Repairs\s+\$?([\d,.-]+)', property_text)
    data['repairs'] = parse_dollar_amount(repairs_match.group(1)) if repairs_match else 0.0
    
    noi_match = re.search(r'Net Operating Income\s+\$?([\d,.-]+)', property_text)
    if noi_match:
        data['noi'] = parse_dollar_amount(noi_match.group(1))
    
    # Parse individual expense line items
    data['expense_details'] = []
    expense_lines = re.findall(
        r'Bill\s+(\d{2}/\d{2}/\d{4})\s+([^\$]+?)\s+([^\$]*?)\s+\$?([\d,.-]+)',
        property_text
    )
    for date, vendor, comment, amount in expense_lines:
        data['expense_details'].append({
            'date': date.strip(),
            'vendor': vendor.strip(),
            'comment': comment.strip(),
            'amount': parse_dollar_amount(amount)
        })
    
    return data


def parse_pdf(pdf_path: str) -> dict:
    """
    Parse a complete owner statement PDF.
    
    Args:
        pdf_path: Path to the PDF file
        
    Returns:
        Dictionary with structure:
        {
            'source_file': str,
            'extraction_timestamp': str,
            'owners': [
                {
                    'owner_name': str,
                    'period_start': str,
                    'period_end': str,
                    ... financial metrics ...,
                    'properties': [
                        {
                            'address': str,
                            ... property metrics ...,
                            'expense_details': [...]
                        }
                    ]
                }
            ]
        }
    """
    text = extract_text_from_pdf(pdf_path)
    
    results = {
        'source_file': str(pdf_path),
        'extraction_timestamp': datetime.now().isoformat(),
        'owners': []
    }
    
    # Split by form feed to get individual pages
    pages = text.split('\f')
    
    current_owner = None
    
    for page in pages:
        page = page.strip()
        if not page:
            continue
        
        # Check if this is an owner statement header page
        if 'OWNER STATEMENT' in page and 'Portfolio Summary' in page:
            if current_owner:
                results['owners'].append(current_owner)
            
            current_owner = parse_portfolio_summary(page)
            current_owner['properties'] = []
        
        # Check if this is a property detail page
        elif current_owner and 'Current' in page[:200] and 'Rent:' in page[:300]:
            property_data = parse_property_section(page)
            if property_data.get('address'):
                current_owner['properties'].append(property_data)
    
    # Don't forget the last owner
    if current_owner:
        results['owners'].append(current_owner)

    # Filter out David Mascari if there are multiple owners with duplicate data
    # (PDFs sometimes repeat the same statement with different owner names)
    if len(results['owners']) > 1:
        owner_names = [o.get('owner_name', '') for o in results['owners']]
        if 'David Mascari' in owner_names:
            # Remove David Mascari and keep the other owner(s)
            results['owners'] = [
                o for o in results['owners']
                if o.get('owner_name') != 'David Mascari'
            ]

    return results


def is_standard_format(pdf_path: str) -> bool:
    """
    Check if a PDF matches the expected Mid South Best Rentals format.
    
    Used by classifier to decide whether to use deterministic parsing
    or fall back to LLM parsing.
    
    Args:
        pdf_path: Path to PDF file
        
    Returns:
        True if format is recognized, False otherwise
    """
    try:
        text = extract_text_from_pdf(pdf_path)
        
        has_header = 'Mid South Best Rentals' in text
        has_statement = 'OWNER STATEMENT' in text
        has_summary = 'Portfolio Summary' in text
        
        return has_header and has_statement and has_summary
    except ParserError:
        return False


# CLI entry point for testing
if __name__ == '__main__':
    import sys
    import json
    
    if len(sys.argv) < 2:
        print("Usage: python pdf_parser.py <pdf_file>")
        sys.exit(1)
    
    result = parse_pdf(sys.argv[1])
    print(json.dumps(result, indent=2))
