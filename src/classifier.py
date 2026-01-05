"""
Document Classifier

Routes incoming documents and emails to the appropriate parser
based on format recognition.
"""

import os
from pathlib import Path
from typing import Tuple, Optional
from enum import Enum

from .pdf_parser import is_standard_format, parse_pdf, ParserError
from .llm_parser import LLMParser, LLMParserError


class DocumentType(Enum):
    """Types of documents the system can process."""
    OWNER_STATEMENT = "owner_statement"
    MAINTENANCE_REQUEST = "maintenance_request"
    LEASE_DOCUMENT = "lease_document"
    TENANT_COMMUNICATION = "tenant_communication"
    UNKNOWN = "unknown"


class EmailAction(Enum):
    """Actions the agent can take on an email."""
    PARSE_STATEMENT = "parse_statement"
    LOG_MAINTENANCE = "log_maintenance"
    FLAG_FOR_REVIEW = "flag_for_review"
    SKIP = "skip"


class Classifier:
    """
    Classifies documents and emails, routing them to appropriate handlers.
    
    The classifier first attempts deterministic classification based on
    known patterns. If that fails and LLM parsing is enabled, it falls
    back to Claude for classification.
    """
    
    def __init__(self, enable_llm: bool = False):
        """
        Initialize the classifier.
        
        Args:
            enable_llm: Whether to use LLM fallback for unknown formats.
                       Requires ANTHROPIC_API_KEY to be set.
        """
        self.enable_llm = enable_llm
        self._llm_parser = None
    
    @property
    def llm_parser(self) -> LLMParser:
        """Lazy initialization of LLM parser."""
        if self._llm_parser is None:
            self._llm_parser = LLMParser()
        return self._llm_parser
    
    def classify_pdf(self, pdf_path: str) -> Tuple[DocumentType, float]:
        """
        Classify a PDF document.
        
        Args:
            pdf_path: Path to PDF file
            
        Returns:
            Tuple of (DocumentType, confidence score 0-1)
        """
        # First, try deterministic classification
        if is_standard_format(pdf_path):
            return (DocumentType.OWNER_STATEMENT, 1.0)
        
        # TODO: Add more deterministic checks for other document types
        # - Lease documents often have "LEASE AGREEMENT" header
        # - Maintenance requests might have "WORK ORDER" or similar
        
        # If LLM is enabled, try classification with Claude
        if self.enable_llm:
            try:
                result = self.llm_parser.parse_document(pdf_path)
                doc_type = DocumentType(result.get('document_type', 'unknown'))
                confidence = result.get('confidence', 0.5)
                return (doc_type, confidence)
            except (LLMParserError, NotImplementedError):
                pass
        
        return (DocumentType.UNKNOWN, 0.0)
    
    def classify_email(
        self,
        sender: str,
        subject: str,
        body: str,
        has_attachment: bool
    ) -> Tuple[EmailAction, dict]:
        """
        Classify an email and determine appropriate action.
        
        Args:
            sender: Email sender address
            subject: Email subject line
            body: Email body text
            has_attachment: Whether email has PDF attachment
            
        Returns:
            Tuple of (EmailAction, metadata dict)
        """
        sender_lower = sender.lower()
        subject_lower = subject.lower()
        
        # Known property manager emails with attachments -> parse statement
        if 'midsouthbestrentals' in sender_lower or 'midsouth' in sender_lower:
            if has_attachment and ('statement' in subject_lower or 'report' in subject_lower):
                return (EmailAction.PARSE_STATEMENT, {
                    'reason': 'Known sender with statement attachment',
                    'confidence': 0.95
                })

        # Forwarded owner statements from mascari.david@gmail.com
        if 'mascari.david@gmail.com' in sender_lower:
            if has_attachment and 'owner statement' in subject_lower:
                return (EmailAction.PARSE_STATEMENT, {
                    'reason': 'Forwarded owner statement',
                    'confidence': 0.9
                })
        
        # Maintenance-related keywords
        maintenance_keywords = [
            'repair', 'maintenance', 'broken', 'leak', 'hvac',
            'plumbing', 'electrical', 'fix', 'work order'
        ]
        if any(kw in subject_lower or kw in body.lower() for kw in maintenance_keywords):
            return (EmailAction.LOG_MAINTENANCE, {
                'reason': 'Maintenance keywords detected',
                'confidence': 0.7
            })
        
        # If LLM is enabled, use it for unknown emails
        if self.enable_llm:
            try:
                result = self.llm_parser.classify_email(sender, subject, body)
                action = EmailAction(result.get('action', 'flag_for_review').lower())
                return (action, result)
            except (LLMParserError, NotImplementedError):
                pass
        
        # Default: flag for manual review
        return (EmailAction.FLAG_FOR_REVIEW, {
            'reason': 'Could not automatically classify',
            'confidence': 0.0
        })
    
    def parse_document(self, pdf_path: str) -> dict:
        """
        Parse a document using the appropriate parser.
        
        Args:
            pdf_path: Path to PDF file
            
        Returns:
            Parsed document data
            
        Raises:
            ParserError: If parsing fails
        """
        doc_type, confidence = self.classify_pdf(pdf_path)
        
        if doc_type == DocumentType.OWNER_STATEMENT and confidence > 0.8:
            # Use deterministic parser for known formats
            return parse_pdf(pdf_path)
        
        elif self.enable_llm:
            # Fall back to LLM parser
            return self.llm_parser.parse_document(pdf_path)
        
        else:
            raise ParserError(
                f"Unknown document format and LLM parsing not enabled. "
                f"Detected type: {doc_type.value}, confidence: {confidence}"
            )


# Convenience function for simple use cases
def parse_document(pdf_path: str, enable_llm: bool = False) -> dict:
    """
    Parse a document, automatically selecting the appropriate parser.
    
    Args:
        pdf_path: Path to PDF file
        enable_llm: Whether to use LLM fallback
        
    Returns:
        Parsed document data
    """
    classifier = Classifier(enable_llm=enable_llm)
    return classifier.parse_document(pdf_path)


# CLI entry point
if __name__ == '__main__':
    import sys
    import json
    
    if len(sys.argv) < 2:
        print("Usage: python classifier.py <pdf_file> [--llm]")
        sys.exit(1)
    
    pdf_path = sys.argv[1]
    enable_llm = '--llm' in sys.argv
    
    classifier = Classifier(enable_llm=enable_llm)
    
    doc_type, confidence = classifier.classify_pdf(pdf_path)
    print(f"Document type: {doc_type.value}")
    print(f"Confidence: {confidence:.2f}")
    
    if confidence > 0.5:
        print("\nParsing document...")
        result = classifier.parse_document(pdf_path)
        print(json.dumps(result, indent=2))
