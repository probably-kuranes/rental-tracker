"""
Gmail Agent

Connects to Gmail API to fetch owner statement emails and download attachments.
"""

import os
import base64
import pickle
from pathlib import Path
from typing import List, Optional
from dataclasses import dataclass
from datetime import datetime

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


# Gmail API scopes needed
SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.modify',  # For adding labels
]


@dataclass
class EmailAttachment:
    """Represents an email attachment."""
    filename: str
    mime_type: str
    data: bytes
    
    def save(self, directory: str) -> Path:
        """Save attachment to directory, return path."""
        path = Path(directory) / self.filename
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'wb') as f:
            f.write(self.data)
        return path


@dataclass
class Email:
    """Represents a Gmail message."""
    id: str
    thread_id: str
    sender: str
    subject: str
    date: datetime
    body: str
    attachments: List[EmailAttachment]
    labels: List[str]
    
    @property
    def has_pdf_attachment(self) -> bool:
        """Check if email has PDF attachment."""
        return any(
            a.mime_type == 'application/pdf' or a.filename.lower().endswith('.pdf')
            for a in self.attachments
        )
    
    @property
    def pdf_attachments(self) -> List[EmailAttachment]:
        """Get only PDF attachments."""
        return [
            a for a in self.attachments
            if a.mime_type == 'application/pdf' or a.filename.lower().endswith('.pdf')
        ]


class GmailAgent:
    """
    Agent for fetching and processing Gmail messages.
    
    Usage:
        agent = GmailAgent()
        emails = agent.fetch_unprocessed_statements()
        for email in emails:
            for pdf in email.pdf_attachments:
                path = pdf.save('./downloads')
                # Process the PDF...
            agent.mark_as_processed(email)
    """
    
    def __init__(
        self,
        credentials_file: Optional[str] = None,
        token_file: Optional[str] = None
    ):
        """
        Initialize Gmail agent.
        
        Args:
            credentials_file: Path to OAuth credentials JSON
            token_file: Path to store/load auth token
        """
        self.credentials_file = credentials_file or os.getenv(
            'GMAIL_CREDENTIALS_FILE', 'credentials.json'
        )
        self.token_file = token_file or os.getenv(
            'GMAIL_TOKEN_FILE', 'token.json'
        )
        self.search_query = os.getenv(
            'GMAIL_SEARCH_QUERY',
            'from:midsouthbestrentals.com has:attachment'
        )
        self.processed_label = os.getenv(
            'PROCESSED_LABEL',
            'RentalTracker/Processed'
        )
        
        self._service = None
        self._processed_label_id = None
    
    def authenticate(self) -> Credentials:
        """
        Authenticate with Gmail API.
        
        Returns:
            Valid credentials
            
        Raises:
            FileNotFoundError: If credentials file not found
        """
        creds = None
        
        # Load existing token if available
        if os.path.exists(self.token_file):
            with open(self.token_file, 'rb') as token:
                creds = pickle.load(token)
        
        # Refresh or get new credentials if needed
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not os.path.exists(self.credentials_file):
                    raise FileNotFoundError(
                        f"Gmail credentials file not found: {self.credentials_file}\n"
                        "Download from Google Cloud Console and save as credentials.json"
                    )
                flow = InstalledAppFlow.from_client_secrets_file(
                    self.credentials_file, SCOPES
                )
                creds = flow.run_local_server(port=0)
            
            # Save token for next run
            with open(self.token_file, 'wb') as token:
                pickle.dump(creds, token)
        
        return creds
    
    @property
    def service(self):
        """Get authenticated Gmail service."""
        if self._service is None:
            creds = self.authenticate()
            self._service = build('gmail', 'v1', credentials=creds)
        return self._service
    
    def _get_or_create_label(self, label_name: str) -> str:
        """Get label ID, creating if necessary."""
        try:
            # List existing labels
            results = self.service.users().labels().list(userId='me').execute()
            labels = results.get('labels', [])
            
            for label in labels:
                if label['name'] == label_name:
                    return label['id']
            
            # Create label if not found
            label_body = {
                'name': label_name,
                'labelListVisibility': 'labelShow',
                'messageListVisibility': 'show'
            }
            created = self.service.users().labels().create(
                userId='me', body=label_body
            ).execute()
            return created['id']
            
        except HttpError as e:
            raise RuntimeError(f"Failed to get/create label: {e}")
    
    @property
    def processed_label_id(self) -> str:
        """Get ID of the 'processed' label."""
        if self._processed_label_id is None:
            self._processed_label_id = self._get_or_create_label(self.processed_label)
        return self._processed_label_id
    
    def _parse_message(self, msg_data: dict) -> Email:
        """Parse Gmail API message into Email object."""
        headers = {
            h['name'].lower(): h['value']
            for h in msg_data['payload'].get('headers', [])
        }
        
        # Parse date
        date_str = headers.get('date', '')
        try:
            # Gmail date format varies, try common formats
            for fmt in ['%a, %d %b %Y %H:%M:%S %z', '%d %b %Y %H:%M:%S %z']:
                try:
                    date = datetime.strptime(date_str.split(' (')[0].strip(), fmt)
                    break
                except ValueError:
                    continue
            else:
                date = datetime.now()
        except Exception:
            date = datetime.now()
        
        # Get body
        body = ''
        payload = msg_data['payload']
        if 'body' in payload and payload['body'].get('data'):
            body = base64.urlsafe_b64decode(payload['body']['data']).decode('utf-8', errors='ignore')
        elif 'parts' in payload:
            for part in payload['parts']:
                if part['mimeType'] == 'text/plain' and part['body'].get('data'):
                    body = base64.urlsafe_b64decode(part['body']['data']).decode('utf-8', errors='ignore')
                    break
        
        # Get attachments
        attachments = []
        if 'parts' in payload:
            for part in payload['parts']:
                if part.get('filename') and part['body'].get('attachmentId'):
                    att_id = part['body']['attachmentId']
                    att_data = self.service.users().messages().attachments().get(
                        userId='me',
                        messageId=msg_data['id'],
                        id=att_id
                    ).execute()
                    
                    file_data = base64.urlsafe_b64decode(att_data['data'])
                    attachments.append(EmailAttachment(
                        filename=part['filename'],
                        mime_type=part.get('mimeType', 'application/octet-stream'),
                        data=file_data
                    ))
        
        return Email(
            id=msg_data['id'],
            thread_id=msg_data['threadId'],
            sender=headers.get('from', ''),
            subject=headers.get('subject', ''),
            date=date,
            body=body,
            attachments=attachments,
            labels=msg_data.get('labelIds', [])
        )
    
    def fetch_unprocessed_statements(self, max_results: int = 50) -> List[Email]:
        """
        Fetch unprocessed owner statement emails.
        
        Args:
            max_results: Maximum number of emails to fetch
            
        Returns:
            List of Email objects with attachments
        """
        # Build query to exclude already-processed emails
        query = f"{self.search_query} -label:{self.processed_label}"
        
        try:
            results = self.service.users().messages().list(
                userId='me',
                q=query,
                maxResults=max_results
            ).execute()
            
            messages = results.get('messages', [])
            emails = []
            
            for msg_ref in messages:
                msg_data = self.service.users().messages().get(
                    userId='me',
                    id=msg_ref['id'],
                    format='full'
                ).execute()
                
                email = self._parse_message(msg_data)
                if email.has_pdf_attachment:
                    emails.append(email)
            
            return emails
            
        except HttpError as e:
            raise RuntimeError(f"Failed to fetch emails: {e}")
    
    def mark_as_processed(self, email: Email) -> None:
        """
        Mark an email as processed by adding label.
        
        Args:
            email: Email to mark as processed
        """
        try:
            self.service.users().messages().modify(
                userId='me',
                id=email.id,
                body={'addLabelIds': [self.processed_label_id]}
            ).execute()
        except HttpError as e:
            raise RuntimeError(f"Failed to mark email as processed: {e}")
    
    def fetch_email_by_id(self, message_id: str) -> Email:
        """
        Fetch a specific email by ID.
        
        Args:
            message_id: Gmail message ID
            
        Returns:
            Email object
        """
        try:
            msg_data = self.service.users().messages().get(
                userId='me',
                id=message_id,
                format='full'
            ).execute()
            return self._parse_message(msg_data)
        except HttpError as e:
            raise RuntimeError(f"Failed to fetch email {message_id}: {e}")


# CLI entry point for testing
if __name__ == '__main__':
    import sys
    
    agent = GmailAgent()
    
    if len(sys.argv) > 1 and sys.argv[1] == '--auth':
        print("Authenticating with Gmail...")
        agent.authenticate()
        print("Authentication successful! Token saved.")
        sys.exit(0)
    
    print("Fetching unprocessed owner statements...")
    emails = agent.fetch_unprocessed_statements()
    
    print(f"Found {len(emails)} unprocessed emails with PDF attachments:")
    for email in emails:
        print(f"\n  From: {email.sender}")
        print(f"  Subject: {email.subject}")
        print(f"  Date: {email.date}")
        print(f"  Attachments: {[a.filename for a in email.pdf_attachments]}")
