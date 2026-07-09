#!/usr/bin/env python3
"""
Run Agent

Main entry point for the rental property tracker statement ingest.
Fetches unprocessed owner-statement emails over IMAP, parses PDFs, and loads
data into the database.

Usage:
    python scripts/run_agent.py
    python scripts/run_agent.py --dry-run
    python scripts/run_agent.py --verbose
    python scripts/run_agent.py --since 2025/01/01   # backfill floor
"""

import os
import sys
import argparse
import tempfile
from datetime import datetime
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src import config
from src.mailbox import GmailMailbox
from src.classifier import Classifier, EmailAction
from src.data_loader import DataLoader
from src.database import Database
from src.reports import ReportGenerator


def run_agent(dry_run: bool = False, verbose: bool = False,
              since: str = None) -> dict:
    """
    Run the email processing agent.

    Args:
        dry_run: If True, don't actually modify anything
        verbose: If True, print detailed progress
        since: Gmail-syntax date (YYYY/MM/DD) floor for the search

    Returns:
        Dictionary with processing statistics
    """
    stats = {
        'emails_found': 0,
        'emails_processed': 0,
        'emails_skipped': 0,
        'properties_imported': 0,
        'errors': []
    }

    def log(msg: str):
        if verbose:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

    # Initialize components
    log("Initializing...")

    try:
        mailbox = GmailMailbox()
        # LLM fallback parses statements that don't match the standard
        # Mid South Best Rentals format (requires ANTHROPIC_API_KEY).
        enable_llm = bool(os.getenv('ANTHROPIC_API_KEY'))
        classifier = Classifier(enable_llm=enable_llm)
        db = Database()
        loader = DataLoader(db)
    except Exception as e:
        stats['errors'].append(f"Initialization failed: {e}")
        return stats

    # Ensure database tables exist
    log("Ensuring database tables exist...")
    if not dry_run:
        db.create_tables()

    # Fetch unprocessed emails
    log(f"Fetching unprocessed statements since {since or config.STATEMENT_SINCE}...")
    try:
        emails = mailbox.fetch_unprocessed_statements(since=since)
        stats['emails_found'] = len(emails)
        log(f"Found {len(emails)} unprocessed emails with attachments")
    except Exception as e:
        stats['errors'].append(f"Failed to fetch emails: {e}")
        return stats

    # Process each email
    for msg in emails:
        log(f"Processing: {msg.subject} from {msg.sender}")

        # Classify the email
        action, metadata = classifier.classify_email(
            sender=msg.sender,
            subject=msg.subject,
            body=msg.body,
            has_attachment=msg.has_pdf_attachment
        )

        log(f"  Classification: {action.value} (confidence: {metadata.get('confidence', 'N/A')})")

        if action != EmailAction.PARSE_STATEMENT:
            log(f"  Action {action.value}: leaving for the inbox digest")
            stats['emails_skipped'] += 1
            continue

        # Process PDF attachments
        email_had_error = False
        for pdf_attachment in msg.pdf_attachments:
            log(f"  Processing attachment: {pdf_attachment.filename}")

            # Save PDF to temp file
            with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
                tmp.write(pdf_attachment.data)
                tmp_path = tmp.name

            try:
                # Parse the PDF
                parsed_data = classifier.parse_document(tmp_path)

                owners = [o.get('owner_name', 'Unknown') for o in parsed_data.get('owners', [])]
                properties = sum(len(o.get('properties', [])) for o in parsed_data.get('owners', []))
                log(f"  Parsed: {len(owners)} owners, {properties} properties")

                if not dry_run:
                    # Load into database
                    result = loader.load(parsed_data, email_id=msg.id)
                    stats['properties_imported'] += result['properties_loaded']

                    if result['errors']:
                        email_had_error = True
                        for err in result['errors']:
                            stats['errors'].append(f"{pdf_attachment.filename}: {err}")

                    log(f"  Loaded: {result['properties_loaded']} properties, "
                        f"{result['reports_skipped']} duplicates skipped")
                else:
                    log(f"  [DRY RUN] Would load {properties} properties")

            except Exception as e:
                email_had_error = True
                error_msg = f"Failed to process {pdf_attachment.filename}: {e}"
                log(f"  ERROR: {error_msg}")
                stats['errors'].append(error_msg)
                continue

            finally:
                # Clean up temp file
                os.unlink(tmp_path)

        # Mark email as processed only if all attachments were processed without error.
        # This prevents emails from being silently skipped on the next run after a
        # transient failure (e.g. parser crash, missing dependency).
        if not dry_run and not email_had_error:
            try:
                mailbox.mark_as_processed(msg)
                log("  Marked as processed")
            except Exception as e:
                stats['errors'].append(f"Failed to mark email as processed: {e}")
        elif email_had_error:
            log("  NOT marked as processed (will retry on next run)")

        stats['emails_processed'] += 1

    mailbox.close()
    return stats


def main():
    parser = argparse.ArgumentParser(
        description='Run the rental property email processing agent'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Parse emails but do not modify database or mark as processed'
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Print detailed progress'
    )
    parser.add_argument(
        '--summary',
        action='store_true',
        help='Print summary report after processing'
    )
    parser.add_argument(
        '--since',
        help='Gmail-syntax date floor (YYYY/MM/DD), default STATEMENT_SINCE'
    )

    args = parser.parse_args()

    print("=" * 50)
    print("Rental Property Tracker - Email Agent")
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    if args.dry_run:
        print("MODE: Dry run (no changes will be made)")
    print("=" * 50)

    stats = run_agent(dry_run=args.dry_run, verbose=args.verbose, since=args.since)

    print("\n" + "=" * 50)
    print("RESULTS")
    print("=" * 50)
    print(f"  Emails found: {stats['emails_found']}")
    print(f"  Emails processed: {stats['emails_processed']}")
    print(f"  Emails skipped: {stats['emails_skipped']}")
    print(f"  Properties imported: {stats['properties_imported']}")

    if stats['errors']:
        print(f"\n  ERRORS ({len(stats['errors'])}):")
        for err in stats['errors']:
            print(f"    - {err}")

    if args.summary and not args.dry_run:
        print("\n")
        ReportGenerator().print_summary_report()

    # Exit with error code if there were errors
    sys.exit(1 if stats['errors'] else 0)


if __name__ == '__main__':
    main()
