"""
Tests for the PDF parser module.

Run with: pytest tests/test_parser.py -v
"""

import pytest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.pdf_parser import (
    parse_dollar_amount,
    parse_portfolio_summary,
    parse_property_section,
    parse_pdf,
    is_standard_format,
    ParserError
)


class TestParseDollarAmount:
    """Tests for dollar amount parsing."""
    
    def test_simple_amount(self):
        assert parse_dollar_amount("$1,234.56") == 1234.56
    
    def test_no_dollar_sign(self):
        assert parse_dollar_amount("1234.56") == 1234.56
    
    def test_negative_with_minus(self):
        assert parse_dollar_amount("-$1,010.29") == -1010.29
    
    def test_negative_with_parentheses(self):
        assert parse_dollar_amount("($500.00)") == -500.00
    
    def test_zero(self):
        assert parse_dollar_amount("$0.00") == 0.0
    
    def test_empty_string(self):
        assert parse_dollar_amount("") == 0.0
    
    def test_dash_only(self):
        assert parse_dollar_amount("-") == 0.0
    
    def test_none(self):
        assert parse_dollar_amount(None) == 0.0
    
    def test_large_amount(self):
        assert parse_dollar_amount("$1,234,567.89") == 1234567.89


class TestParsePortfolioSummary:
    """Tests for portfolio summary parsing."""
    
    def test_extracts_owner_name(self):
        text = """David Mascari                             OWNER STATEMENT
        Report Period: 11/01/2025 - 11/30/2025
        Portfolio Summary
        Previous Balance                                $1,000.00"""
        
        result = parse_portfolio_summary(text)
        assert result['owner_name'] == 'David Mascari'
    
    def test_extracts_period(self):
        text = """Owner Name                             OWNER STATEMENT
        Report Period: 11/01/2025 - 11/30/2025
        Portfolio Summary"""
        
        result = parse_portfolio_summary(text)
        assert result['period_start'] == '11/01/2025'
        assert result['period_end'] == '11/30/2025'
    
    def test_extracts_financial_metrics(self):
        text = """Test Owner                             OWNER STATEMENT
        Report Period: 01/01/2025 - 01/31/2025
        Portfolio Summary
        Previous Balance                                $1,000.00
        Income                                     +    $5,000.00
        Expenses                                   -    $1,500.00
        Mgmt Fees                                  -      $500.00
        Total                                           $4,000.00
        Draws                                      -   -$3,000.00
        Ending Balance                                  $1,000.00
        Due To Owner                                    $1,000.00"""
        
        result = parse_portfolio_summary(text)
        assert result['previous_balance'] == 1000.00
        assert result['income'] == 5000.00
        assert result['expenses'] == 1500.00
        assert result['mgmt_fees'] == 500.00
        assert result['draws'] == -3000.00
        assert result['ending_balance'] == 1000.00
        assert result['due_to_owner'] == 1000.00


class TestParsePropertySection:
    """Tests for property section parsing."""
    
    def test_extracts_address(self):
        text = """1743 Warner
        Current                  Security
        Rent: $895.00            Deposit: $500.00"""
        
        result = parse_property_section(text)
        assert result['address'] == '1743 Warner'
    
    def test_extracts_rent_and_deposit(self):
        text = """123 Main St
        Current                  Security
        Rent: $1,200.00          Deposit: $1,200.00"""
        
        result = parse_property_section(text)
        assert result['current_rent'] == 1200.00
        assert result['security_deposit'] == 1200.00
    
    def test_extracts_totals(self):
        text = """123 Main St
        Rent: $900.00
        Total Income for 123 Main St                    $900.00
        Total Management Fees                            $90.00
        Total Repairs                                   $150.00
        Total Expenses for 123 Main St                  $240.00
        Net Operating Income                            $660.00"""
        
        result = parse_property_section(text)
        assert result['total_income'] == 900.00
        assert result['total_expenses'] == 240.00
        assert result['mgmt_fees'] == 90.00
        assert result['repairs'] == 150.00
        assert result['noi'] == 660.00
    
    def test_zero_repairs_when_not_present(self):
        text = """123 Main St
        Rent: $900.00
        Total Management Fees                            $90.00
        Total Expenses for 123 Main St                   $90.00"""
        
        result = parse_property_section(text)
        assert result['repairs'] == 0.0


class TestIntegration:
    """Integration tests using sample PDFs."""
    
    @pytest.fixture
    def sample_pdf_path(self):
        """Path to sample PDF for testing."""
        path = Path(__file__).parent / 'fixtures' / 'sample_statement.pdf'
        if not path.exists():
            pytest.skip("Sample PDF not found. Add a test PDF to tests/fixtures/")
        return str(path)
    
    def test_is_standard_format_with_valid_pdf(self, sample_pdf_path):
        """Test format detection with a valid statement."""
        assert is_standard_format(sample_pdf_path) == True
    
    def test_parse_pdf_returns_expected_structure(self, sample_pdf_path):
        """Test that parsed data has expected structure."""
        result = parse_pdf(sample_pdf_path)
        
        assert 'source_file' in result
        assert 'extraction_timestamp' in result
        assert 'owners' in result
        assert isinstance(result['owners'], list)
        
        if result['owners']:
            owner = result['owners'][0]
            assert 'owner_name' in owner
            assert 'properties' in owner
    
    def test_parse_pdf_extracts_properties(self, sample_pdf_path):
        """Test that properties are extracted correctly."""
        result = parse_pdf(sample_pdf_path)
        
        # Assuming the sample has at least one owner with properties
        if result['owners'] and result['owners'][0]['properties']:
            prop = result['owners'][0]['properties'][0]
            assert 'address' in prop
            assert 'current_rent' in prop
            assert 'noi' in prop


class TestEdgeCases:
    """Tests for edge cases and error handling."""
    
    def test_parse_pdf_nonexistent_file(self):
        """Test that parsing a nonexistent file raises ParserError."""
        with pytest.raises(ParserError):
            parse_pdf('/nonexistent/file.pdf')
    
    def test_is_standard_format_nonexistent_file(self):
        """Test format check on nonexistent file returns False."""
        assert is_standard_format('/nonexistent/file.pdf') == False


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
