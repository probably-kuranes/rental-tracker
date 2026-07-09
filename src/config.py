"""Central configuration, read from environment variables.

Follows the morning-digest pattern: required secrets are functions that fail
loudly when missing; optional settings are plain module attributes with
defaults. Everything is set as env vars (Railway Variables in production,
.env locally).
"""
import os

from dotenv import load_dotenv

load_dotenv()


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


# --- Gmail (IMAP with an app password; replaces the old OAuth flow) ---------
def GMAIL_USER() -> str:
    return _require("GMAIL_USER")


def GMAIL_APP_PASSWORD() -> str:
    return _require("GMAIL_APP_PASSWORD")


IMAP_HOST = os.getenv("IMAP_HOST", "imap.gmail.com")

# Gmail search query that identifies owner statements
STATEMENT_QUERY = os.getenv(
    "GMAIL_SEARCH_QUERY",
    '(from:midsouthbestrentals.com OR from:mascari.david@gmail.com) '
    '"Owner Statement" has:attachment',
)

# Earliest date (YYYY/MM/DD, Gmail syntax) the statement ingest looks back to
STATEMENT_SINCE = os.getenv("STATEMENT_SINCE", "2025/01/01")

# The inbox digest normally only looks back this many days; the first backfill
# run overrides this with --since on the command line.
INBOX_LOOKBACK_DAYS = int(os.getenv("INBOX_LOOKBACK_DAYS", "7"))

# Safety cap on how many inbox emails one run will classify with the LLM
MAX_INBOX_EMAILS = int(os.getenv("MAX_INBOX_EMAILS", "500"))

PROCESSED_LABEL = os.getenv("PROCESSED_LABEL", "RentalTracker/Processed")


# --- Claude API --------------------------------------------------------------
def ANTHROPIC_API_KEY() -> str:
    return _require("ANTHROPIC_API_KEY")


LLM_MODEL = os.getenv("LLM_MODEL", "claude-sonnet-5")


# --- Email delivery (Resend HTTPS API; Railway blocks outbound SMTP) --------
def RESEND_API_KEY() -> str:
    return _require("RESEND_API_KEY")


EMAIL_FROM = os.getenv("EMAIL_FROM", "Rental Tracker <onboarding@resend.dev>")
EMAIL_TO = os.getenv("EMAIL_TO", "mascari.david@gmail.com")


# --- Database ----------------------------------------------------------------
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///rental_tracker.db")
