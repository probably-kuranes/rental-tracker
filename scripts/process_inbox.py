#!/usr/bin/env python3
"""
Process Inbox

LLM-powered email inbox processor that:
1. Classifies unprocessed inbox emails as rental reports vs. other
2. Routes rental reports through the existing tracker pipeline
3. Generates synopses for other emails and emails a digest via Resend

Usage:
    python scripts/process_inbox.py
    python scripts/process_inbox.py --dry-run
    python scripts/process_inbox.py --verbose
    python scripts/process_inbox.py --since 2025/01/01   # backfill window
"""

import os
import sys
import argparse
import tempfile
from datetime import datetime
from pathlib import Path
from typing import List
from dataclasses import dataclass

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src import config, emailer
from src.mailbox import GmailMailbox, Email
from src.llm_parser import LLMParser, LLMParserError
from src.classifier import Classifier
from src.data_loader import DataLoader
from src.database import Database


@dataclass
class DigestEntry:
    """Entry for the email digest."""
    date: datetime
    sender: str
    subject: str
    synopsis: str


def build_digest_text(entries: List[DigestEntry]) -> str:
    """Plain-text version of the digest."""
    lines = [f"Email digest - {datetime.now().strftime('%Y-%m-%d')}",
             f"{len(entries)} email(s) that were not rental statements:", ""]
    for e in entries:
        lines.append(f"- {e.date.strftime('%Y-%m-%d')}  {e.sender}")
        lines.append(f"  {e.subject}")
        lines.append(f"  {e.synopsis}")
        lines.append("")
    return "\n".join(lines)


def build_digest_html(entries: List[DigestEntry], max_entries: int = 200) -> str:
    """
    Build HTML email body for the digest.

    Args:
        entries: List of DigestEntry objects
        max_entries: Maximum entries to include in detail table (to avoid huge emails)

    Returns:
        HTML string
    """
    if not entries:
        return "<p>No emails to summarize.</p>"

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


def process_inbox(dry_run: bool = False, verbose: bool = False,
                  since: str = None) -> dict:
    """
    Process all unprocessed inbox emails in the lookback window.

    Args:
        dry_run: If True, don't modify anything
        verbose: If True, print detailed progress
        since: Gmail-syntax date (YYYY/MM/DD) overriding the lookback window

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
        mailbox = GmailMailbox()
        llm = LLMParser()
        enable_llm = bool(os.getenv('ANTHROPIC_API_KEY'))
        classifier = Classifier(enable_llm=enable_llm)
        db = Database()
        loader = DataLoader(db)
    except Exception as e:
        stats['errors'].append(f"Initialization failed: {e}")
        return stats

    # Ensure database tables exist
    if not dry_run:
        db.create_tables()

    # Fetch all unprocessed inbox emails in the window
    log(f"Fetching unprocessed inbox emails "
        f"(since {since or f'{config.INBOX_LOOKBACK_DAYS} days ago'})...")
    try:
        emails = mailbox.fetch_inbox_emails(since=since)
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
    for msg in emails:
        log(f"Processing: {msg.subject[:50]}... from {msg.sender}")
        email_had_error = False

        # Use LLM to classify
        try:
            classification = llm.classify_email(
                sender=msg.sender,
                subject=msg.subject,
                body=msg.body
            )
            is_rental = classification.get('is_rental_report', False)
            confidence = classification.get('confidence', 0.0)
            reason = classification.get('reason', 'No reason provided')

            log(f"  Classification: rental_report={is_rental}, confidence={confidence:.2f}")
            log(f"  Reason: {reason}")

        except LLMParserError as e:
            log(f"  LLM classification failed: {e}")
            stats['errors'].append(f"Classification failed for '{msg.subject}': {e}")
            # Default to non-rental on classification failure
            is_rental = False
            confidence = 0.0
            email_had_error = True

        if is_rental and confidence >= 0.7:
            # Process as rental report
            stats['rental_reports'] += 1

            if msg.has_pdf_attachment:
                for pdf_attachment in msg.pdf_attachments:
                    log(f"  Processing PDF: {pdf_attachment.filename}")

                    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
                        tmp.write(pdf_attachment.data)
                        tmp_path = tmp.name

                    try:
                        parsed_data = classifier.parse_document(tmp_path)

                        if not dry_run:
                            result = loader.load(parsed_data, email_id=msg.id)
                            stats['properties_imported'] += result['properties_loaded']
                            log(f"  Loaded {result['properties_loaded']} properties")
                        else:
                            props = sum(len(o.get('properties', [])) for o in parsed_data.get('owners', []))
                            log(f"  [DRY RUN] Would load {props} properties")

                    except Exception as e:
                        log(f"  ERROR processing PDF: {e}")
                        stats['errors'].append(f"PDF processing failed for '{pdf_attachment.filename}': {e}")
                        email_had_error = True

                    finally:
                        os.unlink(tmp_path)
            else:
                log("  No PDF attachment found, skipping parse")
        else:
            # Generate synopsis for digest
            stats['other_emails'] += 1

            try:
                synopsis = llm.generate_synopsis(
                    sender=msg.sender,
                    subject=msg.subject,
                    body=msg.body
                )
                log(f"  Synopsis: {synopsis[:60]}...")

            except LLMParserError as e:
                log(f"  Synopsis generation failed: {e}")
                stats['errors'].append(f"Synopsis failed for '{msg.subject}': {e}")
                synopsis = "[Synopsis generation failed]"
                email_had_error = True

            digest_entries.append(DigestEntry(
                date=msg.date,
                sender=msg.sender,
                subject=msg.subject,
                synopsis=synopsis
            ))

        # Only label emails that were fully handled; failures retry next run
        if not email_had_error:
            processed_emails.append(msg)
        else:
            log("  NOT marking as processed (will retry next run)")

    # Send digest email via Resend if there are non-rental emails
    if digest_entries:
        log(f"Building digest with {len(digest_entries)} entries...")
        digest_html = build_digest_html(digest_entries)
        digest_text = build_digest_text(digest_entries)

        if not dry_run:
            try:
                subject = f"Rental inbox digest - {datetime.now().strftime('%Y-%m-%d')}"
                emailer.send(
                    config.RESEND_API_KEY(),
                    config.EMAIL_FROM,
                    config.EMAIL_TO,
                    subject,
                    digest_text,
                    digest_html,
                )
                stats['digest_sent'] = True
                log(f"Digest email sent to {config.EMAIL_TO}")
            except Exception as e:
                stats['errors'].append(f"Failed to send digest: {e}")
                log(f"ERROR sending digest: {e}")
        else:
            log(f"[DRY RUN] Would send digest to {config.EMAIL_TO}")
            stats['digest_sent'] = True  # Mark as "would have sent"

    # Mark all processed emails with the label
    if not dry_run:
        log("Marking emails as processed...")
        for msg in processed_emails:
            try:
                mailbox.mark_as_processed(msg)
            except Exception as e:
                stats['errors'].append(f"Failed to mark email as processed: {e}")
    else:
        log(f"[DRY RUN] Would mark {len(processed_emails)} emails as processed")

    mailbox.close()
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
    parser.add_argument(
        '--since',
        help='Gmail-syntax date (YYYY/MM/DD) overriding the lookback window'
    )

    args = parser.parse_args()

    print("=" * 60)
    print("LLM Email Inbox Processor")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    if args.dry_run:
        print("MODE: Dry run (no changes will be made)")
    print("=" * 60)

    stats = process_inbox(dry_run=args.dry_run, verbose=args.verbose,
                          since=args.since)

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
