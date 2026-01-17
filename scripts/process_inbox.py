#!/usr/bin/env python3
"""
Process Inbox

LLM-powered email inbox processor that:
1. Classifies emails as rental reports vs. other
2. Routes rental reports through the existing tracker pipeline
3. Generates synopses for other emails and sends a digest

Usage:
    python scripts/process_inbox.py
    python scripts/process_inbox.py --dry-run
    python scripts/process_inbox.py --verbose
"""

import os
import sys
import argparse
import tempfile
from datetime import datetime
from pathlib import Path
from typing import List, Tuple
from dataclasses import dataclass

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from src.gmail_agent import GmailAgent, Email
from src.llm_parser import LLMParser, LLMParserError
from src.classifier import Classifier
from src.data_loader import DataLoader
from src.database import Database


DIGEST_RECIPIENT = "mascari.david@gmail.com"


@dataclass
class DigestEntry:
    """Entry for the email digest."""
    date: datetime
    sender: str
    subject: str
    synopsis: str


def build_digest_html(entries: List[DigestEntry], max_entries: int = 50) -> str:
    """
    Build HTML email body for the digest.

    Args:
        entries: List of DigestEntry objects
        max_entries: Maximum entries to include in detail table (to avoid large emails)

    Returns:
        HTML string
    """
    if not entries:
        return "<p>No emails to summarize.</p>"

    # Truncate if too many entries
    truncated = len(entries) > max_entries
    display_entries = entries[:max_entries] if truncated else entries

    rows = []
    for entry in display_entries:
        date_str = entry.date.strftime("%Y-%m-%d %H:%M")
        # Escape HTML characters
        sender = entry.sender.replace("<", "&lt;").replace(">", "&gt;")
        subject = entry.subject.replace("<", "&lt;").replace(">", "&gt;")
        synopsis = entry.synopsis.replace("<", "&lt;").replace(">", "&gt;")

        rows.append(f"""
        <tr>
            <td style="padding: 8px; border: 1px solid #ddd;">{date_str}</td>
            <td style="padding: 8px; border: 1px solid #ddd;">{sender}</td>
            <td style="padding: 8px; border: 1px solid #ddd;">{subject}</td>
            <td style="padding: 8px; border: 1px solid #ddd;">{synopsis}</td>
        </tr>""")

    truncation_note = ""
    if truncated:
        truncation_note = f"<p><em>Showing {max_entries} of {len(entries)} emails. Older emails omitted for brevity.</em></p>"

    return f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        table {{ border-collapse: collapse; width: 100%; font-family: Arial, sans-serif; }}
        th {{ background-color: #4CAF50; color: white; padding: 12px 8px; text-align: left; }}
        tr:nth-child(even) {{ background-color: #f2f2f2; }}
    </style>
</head>
<body>
    <h2>Email Digest - {datetime.now().strftime("%Y-%m-%d")}</h2>
    <p>Processed {len(entries)} email(s) that were not rental reports:</p>
    {truncation_note}
    <table>
        <tr>
            <th>Date</th>
            <th>Sender</th>
            <th>Subject</th>
            <th>Synopsis</th>
        </tr>
        {''.join(rows)}
    </table>
</body>
</html>
"""


def process_inbox(dry_run: bool = False, verbose: bool = False) -> dict:
    """
    Process all unprocessed inbox emails.

    Args:
        dry_run: If True, don't modify anything
        verbose: If True, print detailed progress

    Returns:
        Dictionary with processing statistics
    """
    stats = {
        'emails_fetched': 0,
        'rental_reports': 0,
        'other_emails': 0,
        'properties_imported': 0,
        'digest_sent': False,
        'errors': []
    }

    def log(msg: str):
        if verbose:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

    # Initialize components
    log("Initializing...")

    try:
        gmail = GmailAgent()
        llm = LLMParser()
        classifier = Classifier(enable_llm=False)
        db = Database()
        loader = DataLoader(db)
    except Exception as e:
        stats['errors'].append(f"Initialization failed: {e}")
        return stats

    # Ensure database tables exist
    if not dry_run:
        db.create_tables()

    # Fetch all unprocessed inbox emails
    log("Fetching unprocessed inbox emails...")
    try:
        emails = gmail.fetch_inbox_emails()
        stats['emails_fetched'] = len(emails)
        log(f"Found {len(emails)} unprocessed emails")
    except Exception as e:
        stats['errors'].append(f"Failed to fetch emails: {e}")
        return stats

    if not emails:
        log("No emails to process")
        return stats

    digest_entries: List[DigestEntry] = []
    processed_emails: List[Email] = []

    # Process each email
    for email in emails:
        log(f"Processing: {email.subject[:50]}... from {email.sender}")

        # Use LLM to classify
        try:
            classification = llm.classify_email(
                sender=email.sender,
                subject=email.subject,
                body=email.body
            )
            is_rental = classification.get('is_rental_report', False)
            confidence = classification.get('confidence', 0.0)
            reason = classification.get('reason', 'No reason provided')

            log(f"  Classification: rental_report={is_rental}, confidence={confidence:.2f}")
            log(f"  Reason: {reason}")

        except LLMParserError as e:
            log(f"  LLM classification failed: {e}")
            stats['errors'].append(f"Classification failed for '{email.subject}': {e}")
            # Default to non-rental on classification failure
            is_rental = False
            confidence = 0.0

        if is_rental and confidence >= 0.7:
            # Process as rental report
            stats['rental_reports'] += 1

            if email.has_pdf_attachment:
                for pdf_attachment in email.pdf_attachments:
                    log(f"  Processing PDF: {pdf_attachment.filename}")

                    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
                        tmp.write(pdf_attachment.data)
                        tmp_path = tmp.name

                    try:
                        parsed_data = classifier.parse_document(tmp_path)

                        if not dry_run:
                            result = loader.load(parsed_data, email_id=email.id)
                            stats['properties_imported'] += result['properties_loaded']
                            log(f"  Loaded {result['properties_loaded']} properties")
                        else:
                            props = sum(len(o.get('properties', [])) for o in parsed_data.get('owners', []))
                            log(f"  [DRY RUN] Would load {props} properties")

                    except Exception as e:
                        log(f"  ERROR processing PDF: {e}")
                        stats['errors'].append(f"PDF processing failed for '{pdf_attachment.filename}': {e}")

                    finally:
                        os.unlink(tmp_path)
            else:
                log("  No PDF attachment found, skipping parse")
        else:
            # Generate synopsis for digest
            stats['other_emails'] += 1

            try:
                synopsis = llm.generate_synopsis(
                    sender=email.sender,
                    subject=email.subject,
                    body=email.body
                )
                log(f"  Synopsis: {synopsis[:60]}...")

                digest_entries.append(DigestEntry(
                    date=email.date,
                    sender=email.sender,
                    subject=email.subject,
                    synopsis=synopsis
                ))

            except LLMParserError as e:
                log(f"  Synopsis generation failed: {e}")
                stats['errors'].append(f"Synopsis failed for '{email.subject}': {e}")
                # Add entry with fallback synopsis
                digest_entries.append(DigestEntry(
                    date=email.date,
                    sender=email.sender,
                    subject=email.subject,
                    synopsis="[Synopsis generation failed]"
                ))

        processed_emails.append(email)

    # Send digest email if there are non-rental emails
    if digest_entries:
        log(f"Building digest with {len(digest_entries)} entries...")
        digest_html = build_digest_html(digest_entries)

        if not dry_run:
            try:
                subject = f"Email Digest - {datetime.now().strftime('%Y-%m-%d %H:%M')}"
                gmail.send_email(
                    to=DIGEST_RECIPIENT,
                    subject=subject,
                    body_html=digest_html
                )
                stats['digest_sent'] = True
                log(f"Digest email sent to {DIGEST_RECIPIENT}")
            except Exception as e:
                stats['errors'].append(f"Failed to send digest: {e}")
                log(f"ERROR sending digest: {e}")
        else:
            log(f"[DRY RUN] Would send digest to {DIGEST_RECIPIENT}")
            stats['digest_sent'] = True  # Mark as "would have sent"

    # Mark all processed emails with the label
    if not dry_run:
        log("Marking emails as processed...")
        for email in processed_emails:
            try:
                gmail.mark_as_processed(email)
            except Exception as e:
                stats['errors'].append(f"Failed to mark email as processed: {e}")
    else:
        log(f"[DRY RUN] Would mark {len(processed_emails)} emails as processed")

    return stats


def main():
    parser = argparse.ArgumentParser(
        description='Process inbox emails with LLM classification'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Classify emails but do not modify database, send emails, or mark as processed'
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Print detailed progress'
    )

    args = parser.parse_args()

    print("=" * 60)
    print("LLM Email Inbox Processor")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    if args.dry_run:
        print("MODE: Dry run (no changes will be made)")
    print("=" * 60)

    stats = process_inbox(dry_run=args.dry_run, verbose=args.verbose)

    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)
    print(f"  Emails fetched: {stats['emails_fetched']}")
    print(f"  Rental reports processed: {stats['rental_reports']}")
    print(f"  Other emails (digest): {stats['other_emails']}")
    print(f"  Properties imported: {stats['properties_imported']}")
    print(f"  Digest sent: {'Yes' if stats['digest_sent'] else 'No'}")

    if stats['errors']:
        print(f"\n  ERRORS ({len(stats['errors'])}):")
        for err in stats['errors']:
            print(f"    - {err}")

    sys.exit(1 if stats['errors'] else 0)


if __name__ == '__main__':
    main()
