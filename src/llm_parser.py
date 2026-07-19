"""
LLM Parser

Uses the Claude API for the pieces deterministic code can't do:
- classify_email: is an email a rental statement or not
- generate_synopsis: one-line summary for the inbox digest
- parse_document: extract statement data from PDFs that don't match the
  standard Mid South Best Rentals format (fallback to pdf_parser.py)
"""

import base64
import json
from pathlib import Path
from typing import Optional

import anthropic

from . import config


class LLMParserError(Exception):
    """Raised when LLM parsing fails."""
    pass


# Matches the output of pdf_parser.parse_pdf(), which is what
# data_loader.DataLoader.load() expects.
EXTRACTION_PROMPT = """Extract rental property owner-statement data from this document.

Return ONLY valid JSON (no markdown fences, no commentary) with this structure:
{
    "owners": [
        {
            "owner_name": "string",
            "period_start": "MM/DD/YYYY",
            "period_end": "MM/DD/YYYY",
            "previous_balance": 0.00,
            "income": 0.00,
            "expenses": 0.00,
            "mgmt_fees": 0.00,
            "total": 0.00,
            "contributions": 0.00,
            "draws": 0.00,
            "ending_balance": 0.00,
            "portfolio_minimum": 0.00,
            "unpaid_bills_total": 0.00,
            "due_to_owner": 0.00,
            "properties": [
                {
                    "address": "string",
                    "current_rent": 0.00,
                    "security_deposit": 0.00,
                    "total_income": 0.00,
                    "total_expenses": 0.00,
                    "mgmt_fees": 0.00,
                    "repairs": 0.00,
                    "noi": 0.00,
                    "expense_details": [
                        {"date": "MM/DD/YYYY", "vendor": "string", "comment": "string", "amount": 0.00}
                    ]
                }
            ]
        }
    ]
}

Use 0 for financial values you cannot find. Use the street address as written
but omit trailing unit suffixes like "_1". If the document repeats the same
statement more than once, extract it only once. Simple year-end or investor
statements with only monthly/annual totals and no per-property pages still
count: use the calendar year (01/01/YYYY - 12/31/YYYY) as the period, put the
annual totals in the owner-level fields, and leave "properties" empty. Only
return {"owners": []} if the document is not a rental income statement at all."""


def _text_of(message) -> str:
    """First text block of a response (skips thinking blocks)."""
    for block in message.content:
        if block.type == 'text':
            return block.text
    raise LLMParserError("No text block in model response")


class LLMParser:
    """
    Claude-based email classification, summarization, and document parsing.
    """

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key
        self.model = model or config.LLM_MODEL
        self._client = None

    @property
    def client(self):
        """Lazy initialization of Anthropic client."""
        if self._client is None:
            key = self.api_key or config.ANTHROPIC_API_KEY()
            self._client = anthropic.Anthropic(api_key=key)
        return self._client

    def parse_document(self, pdf_path: str, context: Optional[str] = None) -> dict:
        """
        Parse a statement PDF with Claude (fallback for non-standard formats).

        Returns the same structure as pdf_parser.parse_pdf() so the result
        can be fed straight into DataLoader.load().

        Raises:
            LLMParserError: If parsing fails
        """
        path = Path(pdf_path)
        if not path.exists():
            raise LLMParserError(f"File not found: {pdf_path}")

        pdf_base64 = base64.standard_b64encode(path.read_bytes()).decode('utf-8')

        prompt = EXTRACTION_PROMPT
        if context:
            prompt = f"{context}\n\n{prompt}"

        try:
            message = self.client.messages.create(
                model=self.model,
                max_tokens=16000,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "document",
                            "source": {
                                "type": "base64",
                                "media_type": "application/pdf",
                                "data": pdf_base64,
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                }],
            )
        except anthropic.APIError as e:
            raise LLMParserError(f"API call failed: {e}")

        result = self._parse_response(_text_of(message))
        result['source_file'] = str(pdf_path)
        result.setdefault('owners', [])
        # Statement PDFs often repeat the same statement addressed to
        # different family members; keep the non-David copy (same rule as
        # pdf_parser.parse_pdf).
        if len(result['owners']) > 1:
            names = [o.get('owner_name') for o in result['owners']]
            if 'David Mascari' in names:
                result['owners'] = [
                    o for o in result['owners']
                    if o.get('owner_name') != 'David Mascari'
                ]
        result['document_type'] = (
            'owner_statement' if result['owners'] else 'other'
        )
        result.setdefault('confidence', 0.9 if result['owners'] else 0.1)
        return result

    def _parse_response(self, response_text: str) -> dict:
        """Parse and validate Claude's response."""
        text = response_text.strip()
        if text.startswith('```'):
            text = text.split('```')[1]
            if text.startswith('json'):
                text = text[4:]
        text = text.strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise LLMParserError(f"Failed to parse LLM response as JSON: {e}")

    def classify_email(self, sender: str, subject: str, body: str) -> dict:
        """
        Classify an email to determine if it's a rental property report.

        Returns dict with is_rental_report, confidence, reason.

        Raises:
            LLMParserError: If API call fails
        """
        max_body_length = 4000
        truncated_body = body[:max_body_length]

        prompt = f"""Analyze this email and determine if it contains a rental property owner statement
or rental income/expense report from a property management company.

Sender: {sender}
Subject: {subject}
Body: {truncated_body}

Respond with ONLY valid JSON (no markdown, no explanation):
{{"is_rental_report": true/false, "confidence": 0.0-1.0, "reason": "brief explanation"}}"""

        try:
            message = self.client.messages.create(
                model=self.model,
                max_tokens=256,
                messages=[{"role": "user", "content": prompt}],
            )
            return self._parse_response(_text_of(message).strip())
        except anthropic.APIError as e:
            raise LLMParserError(f"API call failed: {e}")
        except Exception as e:
            raise LLMParserError(f"Classification failed: {e}")

    def generate_synopsis(self, sender: str, subject: str, body: str) -> str:
        """
        Generate a concise (<=30 word) synopsis of an email for the digest.

        Raises:
            LLMParserError: If API call fails
        """
        max_body_length = 4000
        truncated_body = body[:max_body_length]

        prompt = f"""Summarize this email in exactly 30 words or less. Be factual and concise.
Focus on the key action or information being communicated.

From: {sender}
Subject: {subject}

{truncated_body}

Provide ONLY the summary, no quotes or explanation."""

        try:
            message = self.client.messages.create(
                model=self.model,
                max_tokens=100,
                messages=[{"role": "user", "content": prompt}],
            )
            return _text_of(message).strip()
        except anthropic.APIError as e:
            raise LLMParserError(f"API call failed: {e}")
        except Exception as e:
            raise LLMParserError(f"Synopsis generation failed: {e}")


# CLI entry point for testing
if __name__ == '__main__':
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m src.llm_parser <pdf_file>")
        sys.exit(1)

    parser = LLMParser()
    print(json.dumps(parser.parse_document(sys.argv[1]), indent=2))
