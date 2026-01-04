#!/usr/bin/env python3
"""
Setup Gmail

Run the OAuth authorization flow for Gmail API access.
This will open a browser window for you to authorize the application.

Prerequisites:
    1. Create a project in Google Cloud Console
    2. Enable the Gmail API
    3. Create OAuth 2.0 credentials (Desktop application)
    4. Download credentials.json to project root

Usage:
    python scripts/setup_gmail.py
"""

import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from src.gmail_agent import GmailAgent


def main():
    print("=" * 50)
    print("Gmail API Authorization Setup")
    print("=" * 50)
    print()
    
    agent = GmailAgent()
    
    print(f"Credentials file: {agent.credentials_file}")
    print(f"Token file: {agent.token_file}")
    print()
    
    if not Path(agent.credentials_file).exists():
        print("❌ ERROR: credentials.json not found!")
        print()
        print("To fix this:")
        print("  1. Go to https://console.cloud.google.com")
        print("  2. Create a new project (or select existing)")
        print("  3. Enable the Gmail API")
        print("  4. Go to Credentials > Create Credentials > OAuth 2.0 Client ID")
        print("  5. Select 'Desktop application'")
        print("  6. Download the JSON file")
        print("  7. Save it as 'credentials.json' in the project root")
        print()
        sys.exit(1)
    
    print("Starting authorization flow...")
    print("A browser window will open for you to authorize access.")
    print()
    
    try:
        creds = agent.authenticate()
        print()
        print("✓ Authorization successful!")
        print(f"✓ Token saved to: {agent.token_file}")
        print()
        
        # Test the connection
        print("Testing connection...")
        service = agent.service
        profile = service.users().getProfile(userId='me').execute()
        print(f"✓ Connected as: {profile['emailAddress']}")
        print(f"✓ Total messages: {profile['messagesTotal']}")
        print()
        
        # Test the search query
        print(f"Testing search query: {agent.search_query}")
        results = service.users().messages().list(
            userId='me',
            q=agent.search_query,
            maxResults=5
        ).execute()
        
        messages = results.get('messages', [])
        print(f"✓ Found {len(messages)} matching messages (showing max 5)")
        print()
        
        print("Setup complete! You can now run:")
        print("  python scripts/run_agent.py --verbose")
        
    except Exception as e:
        print(f"❌ Authorization failed: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
