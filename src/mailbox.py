"""Gmail mailbox access over IMAP with an app password.

Replaces the old Gmail API OAuth flow (gmail_agent.py). OAuth tokens from a
"testing"-mode Google Cloud app expire every 7 days, which silently broke the
cron; an app password never expires. Reading goes over IMAP (port 993, not
blocked by Railway the way SMTP is), searching uses Gmail's own query syntax
via the X-GM-RAW extension, and labels are applied with X-GM-LABELS.
"""
from __future__ import annotations

import email
import email.utils
import imaplib
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from email.header import decode_header
from typing import List, Optional

from . import config


@dataclass
class EmailAttachment:
    """Represents an email attachment."""
    filename: str
    mime_type: str
    data: bytes


@dataclass
class Email:
    """Represents a Gmail message (id is the IMAP UID in All Mail)."""
    id: str
    sender: str
    subject: str
    date: datetime
    body: str
    attachments: List[EmailAttachment] = field(default_factory=list)

    @property
    def has_pdf_attachment(self) -> bool:
        return bool(self.pdf_attachments)

    @property
    def pdf_attachments(self) -> List[EmailAttachment]:
        return [
            a for a in self.attachments
            if a.mime_type == 'application/pdf' or a.filename.lower().endswith('.pdf')
        ]


def _decode(value: Optional[str]) -> str:
    """Decode RFC 2047 encoded-word headers to a plain string."""
    if not value:
        return ''
    parts = []
    for text, charset in decode_header(value):
        if isinstance(text, bytes):
            parts.append(text.decode(charset or 'utf-8', errors='replace'))
        else:
            parts.append(text)
    return ''.join(parts)


def _quote(text: str) -> str:
    """Quote a string for use as an IMAP quoted-string argument."""
    return '"' + text.replace('\\', '\\\\').replace('"', '\\"') + '"'


def _label_search_form(label: str) -> str:
    """Gmail search syntax form of a label name (RentalTracker/Processed ->
    rentaltracker-processed)."""
    return label.lower().replace('/', '-').replace(' ', '-')


class GmailMailbox:
    """
    IMAP client for the rental-tracker Gmail account.

    Usage:
        box = GmailMailbox()
        for msg in box.search_emails('from:midsouthbestrentals.com'):
            ...
            box.mark_as_processed(msg)
    """

    def __init__(self, user: Optional[str] = None, app_password: Optional[str] = None):
        self.user = user or config.GMAIL_USER()
        self.app_password = app_password or config.GMAIL_APP_PASSWORD()
        self.processed_label = config.PROCESSED_LABEL
        self._conn: Optional[imaplib.IMAP4_SSL] = None

    @property
    def conn(self) -> imaplib.IMAP4_SSL:
        if self._conn is None:
            conn = imaplib.IMAP4_SSL(config.IMAP_HOST)
            conn.login(self.user, self.app_password)
            # Creating the label is idempotent; Gmail returns an error if it
            # already exists, which we ignore.
            try:
                conn.create(_quote(self.processed_label))
            except imaplib.IMAP4.error:
                pass
            typ, data = conn.select(_quote(self._all_mail_folder(conn)))
            if typ != 'OK':
                raise RuntimeError(f"Could not select All Mail: {typ} {data}")
            self._conn = conn
        return self._conn

    @staticmethod
    def _all_mail_folder(conn: imaplib.IMAP4_SSL) -> str:
        """Find the All Mail folder by its \\All special-use attribute.

        The name is localized ("[Gmail]/All Mail" in the US, "[Google Mail]/
        All Mail" in the UK, translated elsewhere), so it cannot be hardcoded.
        """
        typ, data = conn.list('""', '*')
        if typ == 'OK':
            for line in data:
                if not line:
                    continue
                decoded = line.decode(errors='replace')
                if '\\All' in decoded:
                    # Format: (\All \HasNoChildren) "/" "[Gmail]/All Mail"
                    name = decoded.rsplit(' "/" ', 1)[-1].strip()
                    return name.strip('"')
        return '[Gmail]/All Mail'

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.logout()
            except Exception:
                pass
            self._conn = None

    # -- searching and fetching ------------------------------------------------

    def _search_uids(self, gmail_query: str) -> List[bytes]:
        typ, data = self.conn.uid('SEARCH', 'X-GM-RAW', _quote(gmail_query))
        if typ != 'OK':
            raise RuntimeError(f"IMAP search failed: {typ} {data}")
        return data[0].split() if data and data[0] else []

    def _fetch_email(self, uid: bytes) -> Email:
        typ, data = self.conn.uid('FETCH', uid, '(RFC822)')
        if typ != 'OK' or not data or data[0] is None:
            raise RuntimeError(f"IMAP fetch failed for uid {uid!r}")
        msg = email.message_from_bytes(data[0][1])

        try:
            date = email.utils.parsedate_to_datetime(msg.get('Date', ''))
        except (TypeError, ValueError):
            date = datetime.now()

        body = ''
        attachments: List[EmailAttachment] = []
        for part in msg.walk():
            if part.get_content_maintype() == 'multipart':
                continue
            filename = _decode(part.get_filename())
            disposition = str(part.get('Content-Disposition') or '')
            if filename or 'attachment' in disposition:
                payload = part.get_payload(decode=True)
                if payload:
                    attachments.append(EmailAttachment(
                        filename=filename or 'attachment',
                        mime_type=part.get_content_type(),
                        data=payload,
                    ))
            elif part.get_content_type() == 'text/plain' and not body:
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or 'utf-8'
                    body = payload.decode(charset, errors='replace')

        return Email(
            id=uid.decode(),
            sender=_decode(msg.get('From', '')),
            subject=_decode(msg.get('Subject', '')),
            date=date,
            body=body,
            attachments=attachments,
        )

    def search_emails(self, gmail_query: str, max_results: Optional[int] = None) -> List[Email]:
        """Fetch full emails matching a Gmail search query (oldest first)."""
        uids = self._search_uids(gmail_query)
        if max_results is not None:
            uids = uids[:max_results]
        return [self._fetch_email(uid) for uid in uids]

    # -- the two queries the pipeline uses --------------------------------------

    def fetch_unprocessed_statements(self, since: Optional[str] = None) -> List[Email]:
        """Owner-statement emails not yet labeled processed, back to `since`
        (Gmail date syntax YYYY/MM/DD; defaults to config.STATEMENT_SINCE)."""
        query = (
            f"{config.STATEMENT_QUERY} "
            f"-label:{_label_search_form(self.processed_label)} "
            f"after:{since or config.STATEMENT_SINCE}"
        )
        emails = self.search_emails(query)
        return [e for e in emails if e.has_pdf_attachment]

    def fetch_inbox_emails(self, since: Optional[str] = None) -> List[Email]:
        """All unprocessed inbox mail in the digest window. `since` is Gmail
        date syntax; defaults to INBOX_LOOKBACK_DAYS ago."""
        if since is None:
            cutoff = datetime.now() - timedelta(days=config.INBOX_LOOKBACK_DAYS)
            since = cutoff.strftime('%Y/%m/%d')
        query = (
            f"in:inbox -label:{_label_search_form(self.processed_label)} "
            f"after:{since}"
        )
        return self.search_emails(query, max_results=config.MAX_INBOX_EMAILS)

    # -- labeling ----------------------------------------------------------------

    def mark_as_processed(self, msg: Email) -> None:
        typ, data = self.conn.uid(
            'STORE', msg.id, '+X-GM-LABELS', _quote(self.processed_label)
        )
        if typ != 'OK':
            raise RuntimeError(f"Failed to label message {msg.id}: {typ} {data}")


# CLI entry point for testing connectivity
if __name__ == '__main__':
    box = GmailMailbox()
    print(f"Connected to {config.IMAP_HOST} as {box.user}")
    statements = box.fetch_unprocessed_statements()
    print(f"Unprocessed statements since {config.STATEMENT_SINCE}: {len(statements)}")
    for e in statements[:10]:
        print(f"  {e.date:%Y-%m-%d}  {e.subject}  [{len(e.pdf_attachments)} PDF(s)]")
    box.close()
