"""Turn a statement PDF into ParsedStatement objects."""
from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

from .detail import parse_detail_text
from .model import ParsedStatement
from .summary import is_summary_format, parse_summary_text
from .text import ParseError, pdf_to_text

PARSER_VERSION = 2   # 2: repeated copies in summary-format PDFs


def detect_format(text: str) -> str:
    if 'OWNER STATEMENT' in text and 'Portfolio Summary' in text:
        return 'detail'
    if is_summary_format(text):
        return 'summary'
    if 'Year end Investor statement' in text:
        return 'investor'
    if 'Miscellaneous Income' in text or '1099' in text or 'Mortgage Interest Statement' in text:
        return 'tax_form'
    return 'unknown'


def parse_text(text: str) -> Tuple[str, List[ParsedStatement]]:
    fmt = detect_format(text)
    if fmt == 'detail':
        return fmt, parse_detail_text(text)
    if fmt == 'summary':
        return fmt, parse_summary_text(text)
    return fmt, []


def parse_pdf(path: str | Path) -> Tuple[str, List[ParsedStatement]]:
    return parse_text(pdf_to_text(path))


__all__ = ['ParseError', 'ParsedStatement', 'PARSER_VERSION', 'detect_format', 'parse_pdf', 'parse_text']
