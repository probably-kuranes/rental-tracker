#!/usr/bin/env python3
"""
Setup Database

Initialize the database tables for the rental property tracker.

Usage:
    python scripts/setup_db.py
    python scripts/setup_db.py --drop  # Drop and recreate (DESTRUCTIVE)
"""

import sys
import argparse
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from src.database import Database, Base


def main():
    parser = argparse.ArgumentParser(
        description='Initialize the rental tracker database'
    )
    parser.add_argument(
        '--drop',
        action='store_true',
        help='Drop existing tables before creating (DESTRUCTIVE - will delete all data)'
    )
    parser.add_argument(
        '--url',
        type=str,
        help='Database URL (overrides DATABASE_URL env var)'
    )
    
    args = parser.parse_args()
    
    db = Database(url=args.url) if args.url else Database()
    
    print(f"Database: {db.url}")
    print()
    
    if args.drop:
        confirm = input(
            "⚠️  WARNING: This will DELETE ALL DATA in the database.\n"
            "Type 'yes' to confirm: "
        )
        if confirm.lower() != 'yes':
            print("Cancelled.")
            sys.exit(0)
        
        print("Dropping existing tables...")
        db.drop_tables()
        print("Tables dropped.")
    
    print("Creating tables...")
    db.create_tables()
    
    print("\nTables created:")
    for table_name in Base.metadata.tables:
        print(f"  ✓ {table_name}")
    
    print("\nDatabase setup complete!")
    
    # Print next steps
    print("\nNext steps:")
    print("  1. Set up Gmail API credentials (see README.md)")
    print("  2. Run: python scripts/setup_gmail.py")
    print("  3. Run: python scripts/run_agent.py --verbose")


if __name__ == '__main__':
    main()
