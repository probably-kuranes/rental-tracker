# 🏠 Rental Property Tracker

Automated system for monitoring rental property owner statements from Mid South Best Rentals. Fetches emails from Gmail, parses PDF statements, stores financial data in PostgreSQL, and provides an interactive Streamlit dashboard.

**Live Dashboard:** https://rental-tracker-web-production.up.railway.app/

## ✨ Features

- **📧 Gmail Integration** - Automatically fetches owner statement emails
- **📄 Deterministic PDF Parsing** - Extracts financial data from Mid South Best Rentals PDFs via `pdftotext`
- **🤖 LLM Inbox Triage** - Classifies non-statement mail with Claude and emails a digest
- **🗄️ Database Storage** - SQLite for local dev, PostgreSQL for production (Railway)
- **📊 Interactive Dashboard** - Streamlit web app with charts and metrics
- **☁️ Railway Deployment** - Web service + cron service + managed Postgres on a single platform
- **🔍 Smart Classification** - Routes documents to appropriate parsers
- **⚠️ Alerts** - Flags properties with high expenses or low margins

## 🏗️ Architecture

```
Gmail Inbox
    │
    ▼
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│ Gmail Agent │ ──▶ │ Classifier  │ ──▶ │ PDF Parser  │
└─────────────┘     └──────┬──────┘     └──────┬──────┘
                           │                   │
              non-statement│                   ▼
                           ▼            ┌─────────────┐
                    ┌─────────────┐     │ Data Loader │
                    │  LLM Digest │     └──────┬──────┘
                    │   (Claude)  │            ▼
                    └─────────────┘     ┌─────────────┐
                                        │  Postgres   │
                                        └──────┬──────┘
                                               ▼
                                        ┌─────────────┐
                                        │  Streamlit  │
                                        │  Dashboard  │
                                        └─────────────┘
```

Two cron-driven entry points run on Railway:
- `scripts/run_agent.py` — fetches owner statements, parses PDFs, loads Postgres
- `scripts/process_inbox.py` — LLM-classifies remaining inbox mail and emails a digest of anything that isn't a recognized statement

## 🚀 Quick Start

### Prerequisites

- Python 3.11+
- Gmail account with API access
- Railway account (for cloud deployment)
- Homebrew (macOS) or apt (Linux) for `poppler` / `pdftotext`

### Local Setup

```bash
git clone https://github.com/probably-kuranes/rental-tracker.git
cd rental-tracker

pip install -r requirements.txt

# Install PDF parsing tool
brew install poppler           # macOS
# sudo apt-get install poppler-utils  # Ubuntu/Debian

cp .env.example .env
# Edit .env with your settings

# Authenticate Gmail (creates token.json)
python3 src/gmail_agent.py --auth

# Initialize database
python3 src/database.py --create

# Run the agent
python3 scripts/run_agent.py --verbose

# View dashboard
streamlit run dashboard.py
```

## 📧 Gmail API Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project and enable the Gmail API
3. Configure the OAuth consent screen (External, add yourself as test user)
4. Create an OAuth 2.0 Client ID (Desktop app), download as `credentials.json`
5. Authenticate locally:
   ```bash
   python3 src/gmail_agent.py --auth
   ```
6. For Railway, base64-encode both files and set as env vars (see Deployment).

## ☁️ Cloud Deployment (Railway)

The project deploys as **three Railway services in one project**:

| Service | Purpose | Start command |
|---------|---------|---------------|
| `rental-tracker-web` | Streamlit dashboard | `streamlit run dashboard.py --server.port=$PORT --server.address=0.0.0.0` (Dockerfile default) |
| `rental-tracker-cron` | Daily statement ingest | `./entrypoint.sh` on schedule `0 9 * * *` UTC |
| `Postgres` | Managed database | Railway plugin |

### Environment variables (set on both app services)

| Variable | Notes |
|----------|-------|
| `DATABASE_URL` | Reference: `${{Postgres.DATABASE_URL}}` |
| `GMAIL_CREDENTIALS_B64` | `base64 < credentials.json` |
| `GMAIL_TOKEN_B64` | `base64 < token.json` |
| `GMAIL_SEARCH_QUERY` | Gmail filter for statements |
| `GMAIL_USER_EMAIL` | Mailbox to monitor |
| `PROCESSED_LABEL` | `RentalTracker/Processed` |
| `ANTHROPIC_API_KEY` | Required by `process_inbox.py` for LLM triage |
| `DIGEST_RECIPIENT` | Where the LLM digest is sent |

### Deploy

```bash
# First time
railway login
railway link            # link to the project
railway up              # deploys the linked service

# Subsequent deploys (any push to main):
git push origin main    # Railway auto-builds from GitHub
```

See `deploy/railway-setup.md` for the full step-by-step guide (project creation, Postgres setup, cron service, base64 secrets).

## 📊 Dashboard Features

- **Portfolio Overview**: Total properties, income, expenses, NOI
- **Property Performance**: Income, expenses, and NOI by property
- **Expense Breakdown**: Pie charts and detailed expense lists
- **Alerts**: Warnings for high expense ratios, low margins, high repairs
- **Filters**: View by owner or specific property

## 🗂️ Project Structure

```
rental-tracker/
├── README.md
├── requirements.txt
├── .env.example
├── Dockerfile                  # Railway container (web default; cron overrides CMD)
├── entrypoint.sh               # Decodes base64 secrets, runs run_agent.py
├── Procfile / nixpacks.toml    # Railway build hints
├── dashboard.py                # Streamlit dashboard
├── sample_data.db              # Demo database
├── src/
│   ├── gmail_agent.py          # Gmail OAuth + fetch (file or base64 creds)
│   ├── pdf_parser.py           # Mid South Best Rentals PDF parser
│   ├── llm_parser.py           # Claude API integration
│   ├── classifier.py           # Document routing
│   ├── database.py             # SQLAlchemy models (SQLite + Postgres)
│   ├── data_loader.py          # Import parsed data with dedup
│   └── reports.py              # Console reports
├── scripts/
│   ├── run_agent.py            # Statement ingest entry point
│   ├── process_inbox.py        # LLM inbox triage + digest
│   ├── setup_db.py
│   └── setup_gmail.py
└── deploy/
    ├── deploy.sh               # Railway deploy helper
    └── railway-setup.md        # Full Railway deployment guide
```

## 💻 Usage

### Process statements

```bash
python3 scripts/run_agent.py --dry-run --verbose   # safe preview
python3 scripts/run_agent.py --verbose             # ingest
python3 scripts/run_agent.py --verbose --summary   # ingest + report
```

Emails are only labeled `RentalTracker/Processed` after **all** attachments succeed, so transient failures (parser crash, missing `pdftotext`, DB outage) are automatically retried on the next run.

### LLM inbox digest

```bash
python3 scripts/process_inbox.py --verbose
python3 scripts/process_inbox.py --dry-run         # don't send digest
```

This script picks up any unprocessed mail that *isn't* a recognized owner statement, asks Claude to summarize each one, and emails you a single digest. Requires `ANTHROPIC_API_KEY`.

### Run on Railway

```bash
railway run python scripts/run_agent.py --verbose  # ad-hoc against prod env
railway logs                                       # tail logs
railway open                                       # open project in browser
```

### Query database

```bash
# Local SQLite
sqlite3 rental_tracker.db

# Railway Postgres
railway connect Postgres
```

## ⚙️ Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | Database connection string | `sqlite:///rental_tracker.db` |
| `GMAIL_CREDENTIALS_FILE` | OAuth credentials path (local) | `credentials.json` |
| `GMAIL_TOKEN_FILE` | Auth token path (local) | `token.json` |
| `GMAIL_CREDENTIALS_B64` | Base64 OAuth credentials (cloud) | - |
| `GMAIL_TOKEN_B64` | Base64 auth token (cloud) | - |
| `GMAIL_SEARCH_QUERY` | Gmail search filter | see `.env.example` |
| `GMAIL_USER_EMAIL` | Mailbox to monitor | - |
| `PROCESSED_LABEL` | Label for processed emails | `RentalTracker/Processed` |
| `ANTHROPIC_API_KEY` | Claude API key (LLM digest) | - |
| `DIGEST_RECIPIENT` | Where to send LLM digest | - |

## 🗄️ Database Schema

- **owners** - Property owners
- **properties** - Rental properties with current rent and deposit
- **monthly_reports** - Portfolio-level monthly summaries
- **property_months** - Property-level monthly performance
- **expenses** - Individual expense line items
- **import_logs** - Track import operations

## 🔐 Security

- Gmail credentials supplied as base64 env vars on Railway (no file mounts)
- `.env`, `credentials.json`, `token.json`, `*.db` excluded from Git
- OAuth tokens refreshed automatically

## 💰 Cost Estimate

- **Railway Hobby plan:** $5/month flat (covers web + cron + Postgres usage for this workload)
- **Anthropic API:** pennies per inbox digest run

## 🛠️ Troubleshooting

### Gmail authentication fails
```bash
rm token.json
python3 src/gmail_agent.py --auth
# Then re-encode and update GMAIL_TOKEN_B64 on Railway
base64 < token.json | pbcopy
```

### No emails found
- Check `GMAIL_SEARCH_QUERY`
- Verify the email isn't already labeled `RentalTracker/Processed`

### Railway cron didn't fire
```bash
railway logs --service rental-tracker-cron
```
Cron only runs on its schedule, not on deploy. To smoke-test, temporarily set the schedule a few minutes out.

### Dashboard shows no data
- Local: ensure `rental_tracker.db` exists or set `DATABASE_URL`
- Cloud: confirm `DATABASE_URL` references `${{Postgres.DATABASE_URL}}`

## 🚧 Future Enhancements

- [ ] Multi-month trend analysis
- [ ] Mobile-responsive dashboard
- [ ] Export reports to PDF/Excel
- [ ] LLM-based parsing for non-standard statement formats

## 📝 License

MIT

## 👤 Author

Built for tracking Memphis rental properties managed by Mid South Best Rentals.

---

**Questions?** See `deploy/railway-setup.md` or read the inline code comments.
