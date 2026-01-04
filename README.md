# Rental Property Tracker

Automated pipeline for processing rental property owner statements from Mid South Best Rentals. Monitors a Gmail inbox for incoming statements, extracts financial data from PDFs, and stores results in a PostgreSQL database.

## Features

- Gmail integration to automatically fetch owner statement emails
- PDF parsing to extract portfolio summaries and property-level detail
- Structured database storage with historical tracking
- Expense categorization (HVAC, Plumbing, Electrical, etc.)
- Placeholder for LLM-based parsing of non-standard documents

## Architecture

```
Gmail Inbox
    │
    ▼
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│ Gmail Agent │ ──▶ │ Classifier  │ ──▶ │ PDF Parser  │
└─────────────┘     └─────────────┘     └──────┬──────┘
                           │                   │
                           ▼                   │
                    ┌─────────────┐            │
                    │ LLM Parser  │            │
                    │ (future)    │            │
                    └──────┬──────┘            │
                           │                   │
                           └─────────┬─────────┘
                                     ▼
                              ┌─────────────┐
                              │ Data Loader │
                              └──────┬──────┘
                                     ▼
                              ┌─────────────┐
                              │ PostgreSQL  │
                              └─────────────┘
```

## Setup

### Prerequisites

- Python 3.10+
- PostgreSQL (or SQLite for local development)
- Gmail account with API access enabled
- pdftotext (from poppler-utils)

### Installation

```bash
# Clone the repository
git clone https://github.com/yourusername/rental-tracker.git
cd rental-tracker

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install system dependency for PDF parsing
# Ubuntu/Debian:
sudo apt-get install poppler-utils
# macOS:
brew install poppler

# Copy environment template and configure
cp .env.example .env
# Edit .env with your credentials
```

### Gmail API Setup

1. Go to Google Cloud Console (https://console.cloud.google.com)
2. Create a new project
3. Enable the Gmail API
4. Create OAuth 2.0 credentials (Desktop application)
5. Download credentials.json and place in project root
6. Run `python scripts/setup_gmail.py` to authorize

### Database Setup

```bash
# Initialize database tables
python scripts/setup_db.py
```

## Usage

### Manual Run

```bash
# Process all unread owner statement emails
python scripts/run_agent.py
```

### Scheduled Run (Linux/macOS)

Add to crontab to run daily at 8am:

```bash
crontab -e
# Add line:
0 8 * * * cd /path/to/rental-tracker && /path/to/venv/bin/python scripts/run_agent.py
```

### Generate Reports

```bash
# Print summary to console
python scripts/run_reports.py --summary

# Export to Excel
python scripts/run_reports.py --export monthly_report.xlsx
```

## Project Structure

```
rental-tracker/
├── README.md
├── requirements.txt
├── .env.example
├── .gitignore
├── src/
│   ├── __init__.py
│   ├── gmail_agent.py      # Email fetching and attachment handling
│   ├── pdf_parser.py       # Deterministic PDF extraction
│   ├── llm_parser.py       # Claude API integration (placeholder)
│   ├── classifier.py       # Routes documents to appropriate parser
│   ├── database.py         # DB connection and table definitions
│   ├── data_loader.py      # Writes parsed data to database
│   └── reports.py          # Query and summarize data
├── scripts/
│   ├── run_agent.py        # Main entry point
│   ├── setup_db.py         # Initialize database
│   └── setup_gmail.py      # Gmail OAuth flow
└── tests/
    ├── __init__.py
    ├── test_parser.py
    └── fixtures/
        └── sample_statement.pdf
```

## Configuration

Environment variables (set in .env):

| Variable | Description |
|----------|-------------|
| DATABASE_URL | PostgreSQL connection string |
| GMAIL_CREDENTIALS_FILE | Path to Gmail OAuth credentials |
| GMAIL_TOKEN_FILE | Path to store Gmail auth token |
| GMAIL_SEARCH_QUERY | Gmail search filter for statements |
| ANTHROPIC_API_KEY | API key for Claude (future use) |

## License

MIT
