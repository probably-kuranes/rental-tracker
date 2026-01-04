"""
LLM Parser for Non-Standard Documents

Uses Claude API to extract data from documents that don't match
the expected format for deterministic parsing.

This is a PLACEHOLDER for future implementation.
"""

import os
import base64
import json
from pathlib import Path
from typing import Optional

# Uncomment when implementing:
# import anthropic


class LLMParserError(Exception):
    """Raised when LLM parsing fails."""
    pass


class LLMParser:
    """
    Claude-based document parser for non-standard formats.
    
    Usage:
        parser = LLMParser()
        result = parser.parse_document(pdf_path)
    """
    
    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize the LLM parser.
        
        Args:
            api_key: Anthropic API key. If not provided, reads from
                     ANTHROPIC_API_KEY environment variable.
        """
        self.api_key = api_key or os.getenv('ANTHROPIC_API_KEY')
        self._client = None
    
    @property
    def client(self):
        """Lazy initialization of Anthropic client."""
        if self._client is None:
            if not self.api_key:
                raise LLMParserError(
                    "ANTHROPIC_API_KEY not set. "
                    "Set environment variable or pass api_key to constructor."
                )
            # Uncomment when implementing:
            # self._client = anthropic.Anthropic(api_key=self.api_key)
            raise NotImplementedError("LLM parser not yet implemented")
        return self._client
    
    def parse_document(self, pdf_path: str, context: Optional[str] = None) -> dict:
        """
        Parse a document using Claude's vision capabilities.
        
        Args:
            pdf_path: Path to PDF file
            context: Optional context about what to extract
            
        Returns:
            Structured data extracted from document
            
        Raises:
            LLMParserError: If parsing fails
            NotImplementedError: Until this module is implemented
        """
        # TODO: Implement when ready to add LLM capabilities
        #
        # Implementation outline:
        # 1. Read PDF file as bytes
        # 2. Convert to base64
        # 3. Send to Claude with structured extraction prompt
        # 4. Parse JSON response
        # 5. Validate against expected schema
        #
        # Example implementation:
        #
        # path = Path(pdf_path)
        # if not path.exists():
        #     raise LLMParserError(f"File not found: {pdf_path}")
        #
        # with open(path, 'rb') as f:
        #     pdf_bytes = f.read()
        #
        # pdf_base64 = base64.standard_b64encode(pdf_bytes).decode('utf-8')
        #
        # message = self.client.messages.create(
        #     model="claude-sonnet-4-20250514",
        #     max_tokens=4096,
        #     messages=[
        #         {
        #             "role": "user",
        #             "content": [
        #                 {
        #                     "type": "document",
        #                     "source": {
        #                         "type": "base64",
        #                         "media_type": "application/pdf",
        #                         "data": pdf_base64
        #                     }
        #                 },
        #                 {
        #                     "type": "text",
        #                     "text": self._build_extraction_prompt(context)
        #                 }
        #             ]
        #         }
        #     ]
        # )
        #
        # return self._parse_response(message.content[0].text)
        
        raise NotImplementedError(
            "LLM parser not yet implemented. "
            "Use pdf_parser.py for standard Mid South Best Rentals statements."
        )
    
    def _build_extraction_prompt(self, context: Optional[str] = None) -> str:
        """Build the extraction prompt for Claude."""
        base_prompt = """Extract rental property data from this document.

Return ONLY valid JSON with this structure:
{
    "document_type": "owner_statement|lease|maintenance_request|other",
    "confidence": 0.0 to 1.0,
    "owner_name": "string or null",
    "period_start": "MM/DD/YYYY or null",
    "period_end": "MM/DD/YYYY or null",
    "properties": [
        {
            "address": "string",
            "income": 0.00,
            "expenses": 0.00,
            "noi": 0.00,
            "notes": "any relevant details"
        }
    ],
    "summary": {
        "total_income": 0.00,
        "total_expenses": 0.00,
        "ending_balance": 0.00
    },
    "raw_notes": "any other relevant information from the document"
}

If you cannot determine a value, use null. Do not include any text outside the JSON."""
        
        if context:
            base_prompt = f"{context}\n\n{base_prompt}"
        
        return base_prompt
    
    def _parse_response(self, response_text: str) -> dict:
        """Parse and validate Claude's response."""
        # Strip any markdown code blocks if present
        text = response_text.strip()
        if text.startswith('```'):
            text = text.split('```')[1]
            if text.startswith('json'):
                text = text[4:]
        text = text.strip()
        
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise LLMParserError(f"Failed to parse LLM response as JSON: {e}")
        
        return data
    
    def classify_email(self, sender: str, subject: str, body: str) -> dict:
        """
        Classify an email and determine appropriate action.
        
        Args:
            sender: Email sender address
            subject: Email subject line
            body: Email body text
            
        Returns:
            Dictionary with:
            - action: PARSE_STATEMENT|MAINTENANCE_REQUEST|TENANT_COMMUNICATION|etc
            - confidence: 0.0 to 1.0
            - details: Additional context
            
        Raises:
            NotImplementedError: Until this module is implemented
        """
        # TODO: Implement email classification
        #
        # This would allow the agent to handle varied email types:
        # - Standard owner statements -> deterministic parser
        # - Maintenance requests -> extract property + issue
        # - Tenant communications -> flag for review
        # - Lease documents -> extract terms
        # - Unknown -> flag for manual review
        
        raise NotImplementedError("Email classification not yet implemented")


# CLI entry point for testing
if __name__ == '__main__':
    print("LLM Parser - Not Yet Implemented")
    print()
    print("This module will provide Claude-based parsing for documents")
    print("that don't match the standard Mid South Best Rentals format.")
    print()
    print("To implement:")
    print("1. Set ANTHROPIC_API_KEY environment variable")
    print("2. Uncomment the anthropic import")
    print("3. Implement the parse_document method")
