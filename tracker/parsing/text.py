"""PDF to text, and small helpers shared by the parsers."""
from __future__ import annotations

import re
import subprocess
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional

AMOUNT_RE = r'-?\(?\$[\d,]+\.\d\d\)?'


class ParseError(Exception):
    pass


def pdf_to_text(path: str | Path) -> str:
    """Text of a PDF with its layout preserved (poppler's pdftotext)."""
    result = subprocess.run(
        ['pdftotext', '-layout', str(path), '-'],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise ParseError(f"pdftotext failed: {result.stderr.strip()}")
    return result.stdout


def money(text: Optional[str]) -> Decimal:
    """'$1,234.56', '-$3.00', '($5.00)' -> Decimal."""
    if not text:
        return Decimal('0')
    s = text.strip()
    negative = s.startswith('-') or (s.startswith('(') and s.endswith(')'))
    s = s.strip('()-').replace('$', '').replace(',', '').strip()
    try:
        value = Decimal(s)
    except InvalidOperation:
        raise ParseError(f"Not an amount: {text!r}")
    return -value if negative else value


def mdy(text: str) -> date:
    return datetime.strptime(text.strip(), '%m/%d/%Y').date()


def find_amount_at_end(line: str) -> Optional[str]:
    m = re.search(r'(' + AMOUNT_RE + r')\s*$', line)
    return m.group(1) if m else None
