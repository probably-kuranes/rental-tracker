#!/usr/bin/env python3
"""
Ingest statement PDFs directly from disk (no email involved).

Used for backfilling history from saved statement files, e.g. the MSHB
annual-statement compilation. The owner is derived from the FILENAME
(e.g. "Torgo 2019 Annual Statement.pdf" -> "Torgo Properties LLC") because
statement PDFs are addressed to family members interchangeably and the
filename carries the true portfolio.

Usage:
    python scripts/ingest_files.py <folder-or-pdf> [more paths...]
    python scripts/ingest_files.py --dry-run <folder>
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.classifier import Classifier
from src.data_loader import DataLoader
from src.database import Database

# Filename prefix -> canonical owner (entity) name
ENTITY_MAP = {
    'torgo': 'Torgo Properties LLC',
    'dunwich': 'Dunwich Properties LLC',
    'miskatonic': 'Miskatonic Properties LLC',
    'walter mascari': 'Walter Mascari',
    'david mascari': 'David Mascari',
}


def owner_from_filename(path: Path):
    """Derive the portfolio owner from a filename like
    'Torgo 2019 Annual Statement.pdf'. Returns None if unrecognized."""
    stem = path.stem.lower()
    for prefix, entity in ENTITY_MAP.items():
        if stem.startswith(prefix):
            return entity
    return None


def iter_pdfs(paths):
    for p in paths:
        p = Path(p).expanduser()
        if p.is_dir():
            yield from sorted(p.glob('*.pdf'))
        elif p.suffix.lower() == '.pdf':
            yield p


def main():
    ap = argparse.ArgumentParser(description='Ingest statement PDFs from disk')
    ap.add_argument('paths', nargs='+', help='PDF files or folders of PDFs')
    ap.add_argument('--dry-run', action='store_true',
                    help='Parse but do not write to the database')
    args = ap.parse_args()

    db = Database()
    if not args.dry_run:
        db.create_tables()
    loader = DataLoader(db)
    classifier = Classifier(enable_llm=True)

    totals = {'files': 0, 'loaded': 0, 'skipped_dup': 0, 'failed': 0}

    for pdf in iter_pdfs(args.paths):
        totals['files'] += 1
        owner = owner_from_filename(pdf)
        print(f"\n[{totals['files']}] {pdf.name}"
              f"  ->  owner: {owner or '(from PDF header)'}", flush=True)
        try:
            parsed = classifier.parse_document(str(pdf))
        except Exception as e:
            print(f"    PARSE FAILED: {e}", flush=True)
            totals['failed'] += 1
            continue

        parsed['source_file'] = pdf.name
        owners = parsed.get('owners', [])
        if not owners:
            print("    no owner statement found in PDF", flush=True)
            totals['failed'] += 1
            continue

        # The filename names the portfolio; the PDF addressee does not.
        # Statements duplicated inside one PDF collapse to one owner.
        if owner:
            for o in owners:
                o['owner_name'] = owner
            if len(owners) > 1 and all(
                o.get('period_start') == owners[0].get('period_start')
                for o in owners
            ):
                parsed['owners'] = owners = owners[:1]

        for o in owners:
            n_props = len(o.get('properties', []))
            print(f"    {o.get('owner_name')} | {o.get('period_start')} - "
                  f"{o.get('period_end')} | income {o.get('income')} | "
                  f"{n_props} properties", flush=True)

        if args.dry_run:
            continue

        try:
            result = loader.load(parsed)
        except Exception as e:
            print(f"    LOAD FAILED: {e}", flush=True)
            totals['failed'] += 1
            continue

        if result['reports_created']:
            totals['loaded'] += 1
            print(f"    loaded: {result['reports_created']} report(s), "
                  f"{result['properties_loaded']} property rows, "
                  f"{result['expenses_loaded']} expense lines", flush=True)
        elif result['reports_skipped']:
            totals['skipped_dup'] += 1
            print("    skipped: already in database (same owner + period)", flush=True)
        if result['errors']:
            print(f"    warnings: {result['errors']}", flush=True)

    print(f"\n{'='*50}\nFiles: {totals['files']} | loaded: {totals['loaded']} | "
          f"duplicates skipped: {totals['skipped_dup']} | failed: {totals['failed']}")
    return 1 if totals['failed'] else 0


if __name__ == '__main__':
    sys.exit(main())
