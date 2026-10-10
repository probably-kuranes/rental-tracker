# 🏠 Rental Tracker

> **v2 is in `tracker/`** (this section). The v1 pipeline and Streamlit
> dashboard (`src/`, `scripts/`, `dashboard.py`) are documented further down and
> still run in production until v2 is deployed.

## Rental Tracker v2

Every Mid South owner statement is broken down to its individual ledger lines
(rent receipts with the tenant's ledger key, returned payments, late fees,
bills with vendor and description). Tenancies, vacancies, late and missing
rent, repairs, make-readies, evictions, rent changes, balances and payouts are
worked out from those lines, and Mid South's update emails (thefts, vandalism,
new leases, repairs) are read by Claude and added to the same timeline.

**Screens:** Status board (each house now, plus each portfolio's balance with
Mid South), Timeline (every house over any period; markers link to the
statement PDF), Analytics (by portfolio and by house, by year), Monthly
summary (a letter written by Claude; the "Family version: Torgo" covers only
the Torgo houses), and Documents (every PDF and email received, and whether it
reconciled; upload PDFs here).

### How it works

```
mascariproperties@gmail.com ──IMAP──▶ tracker.mailbox ──┬─ statement PDFs ──▶ tracker.ingest ──▶ parse + reconcile
   (labels RentalTracker/Processed,                      ├─ published / deposit notices (recorded)
    RentalTracker/NeedsReview)                           └─ update emails ──▶ Claude ──▶ events
Uploads / folders ─────────────────────────────────────────────▶ tracker.ingest
                                                                         │
Postgres: documents, statements, ledger_lines, emails, events ◀──────────┘
        │
tracker.derive (tenancies, events, balances, payouts; recomputed on demand)
        │
tracker.app (FastAPI JSON API + tracker/web single-page UI, behind a password)
```

- **Parsers** (`tracker/parsing/`): `detail.py` reads "Owner Statement Detail
  By Building" (every monthly statement, and annual statements from 2018);
  `summary.py` reads the 2013-2017 "Property Summary" annuals. A statement is
  *reconciled* when its lines add up to the printed totals and its balance rolls
  forward; anything that does not is flagged on the Documents page.
- **Duplicates**: a PDF is stored once by content hash; a statement is loaded
  once however many copies of it arrive; a transaction on both a monthly and an
  annual statement counts once.
- **Portfolio** is decided by the properties on a statement, not the printed
  name (Torgo's statements say "Walter Mascari - T"); see `tracker/portfolios.py`.
- **Gaps** in the statements are shown as gaps ("no statements"), never as
  vacancies, and a move-out is only stated when the statements around it exist.

### Run locally

```bash
pip install -r requirements.txt          # and poppler (pdftotext)
export ALLOW_NO_AUTH=1                    # local only; production needs APP_PASSWORD
python -m tracker.cli ingest ~/Downloads/statements    # load every PDF in a folder
python -m tracker.cli check               # list anything that did not reconcile
python -m tracker.cli serve               # http://localhost:8000
pytest tests/test_tracker.py
```

### Deploy on Railway

Three new pieces in the existing Railway project; nothing in v1 changes.
Each service reads its settings from a config file in `deploy/`
(Settings → Config-as-code → file path), so no build or start commands
need typing in.

| Service | Config file | What it does |
|---|---|---|
| `tracker-db` | (Postgres database) | All data, including the original PDFs |
| `tracker-web` | `deploy/railway.web.json` | The web app; generate a public domain for it |
| `tracker-mail` | `deploy/railway.mail.json` | Reads Mid South's emails daily at 13:15 UTC |

Both app services deploy from this branch and need these variables:

| Variable | Service | Notes |
|---|---|---|
| `DATABASE_URL` | both | `${{tracker-db.DATABASE_URL}}` |
| `ANTHROPIC_API_KEY` | both | Reading update emails, writing the monthly letter |
| `APP_PASSWORD` | web | Login password (user name `david`, or set `APP_USER`) |
| `GMAIL_USER`, `GMAIL_APP_PASSWORD` | mail | mascariproperties@gmail.com and its app password (copy from the v1 cron service) |
| `MAIL_SINCE` | mail | Earliest mail to read, e.g. `2025/01/01` for the first run |

PDFs are stored in Postgres by default because Railway volumes cannot be
shared between services. Set `BLOB_BUCKET` (+ `BLOB_ENDPOINT_URL` and AWS keys)
to use S3 / Cloudflare R2 instead.

**Backfill:** download the Drive statements folder and upload every PDF on the
Documents page (multi-select works), then run the mail job once with
`python -m tracker.cli mail --since 2025/01/01`.

---

## v1: Rental Property Tracker

Automated system for monitoring rental property owner statements from Mid South Best Rentals. Reads the `mascariproperties@gmail.com` mailbox over IMAP, parses PDF statements, stores financial data in PostgreSQL, serves an interactive Streamlit dashboard, and emails a daily digest of everything else that lands in the inbox.

**Live Dashboard:** https://rental-tracker-web-production.up.railway.app/

## ✨ Features

- **📧 Gmail via IMAP + app password** - No OAuth tokens to expire; reads Gmail with the `X-GM-RAW` search extension so full Gmail query syntax works
- **📄 Deterministic PDF Parsing** - Extracts financial data from Mid South Best Rentals PDFs via `pdftotext`
- **🤖 LLM Parse Fallback** - Claude parses statements that don't match the standard format
- **🤖 LLM Inbox Triage** - Classifies non-statement mail with Claude and emails a digest via Resend
- **🗄️ Database Storage** - SQLite for local dev, PostgreSQL for production (Railway)
- **📊 Interactive Dashboard** - Portfolio overview, per-property performance, multi-month trends, expense breakdowns, alerts, CSV export
- **☁️ Railway Deployment** - Web service + daily cron service + managed Postgres

## 🏗️ Architecture

Follows the morning-digest pattern: env-var config (`src/config.py`), IMAP/app-password mail access (no Google OAuth), and email delivery over the Resend HTTPS API (Railway blocks outbound SMTP).

```
Gmail (IMAP, app password)
    │
    ▼
┌──────────────┐   statements   ┌─────────────┐     ┌─────────────┐
│ mailbox.py   │ ─────────────▶ │ Classifier  │ ──▶ │ PDF Parser  │──┐
└──────┬───────┘                └─────────────┘     │ (+LLM fall- │  │
       │ everything else                            │  back)      │  │
       ▼                                            └─────────────┘  ▼
┌──────────────┐     ┌──────────────┐               ┌─────────────┐
│  LLM Triage  │ ──▶ │ Resend email │               │ Data Loader │
│  (Claude)    │     │   digest     │               └──────┬──────┘
└──────────────┘     └──────────────┘                      ▼
                                                    ┌─────────────┐
                                                    │  Postgres   │
                                                    └──────┬──────┘
                                                           ▼
                                                    ┌─────────────┐
                                                    │  Streamlit  │
                                                    │  Dashboard  │
                                                    └─────────────┘
```

The daily Railway cron runs `entrypoint.sh`, which executes both stages:
- `scripts/run_agent.py` — fetches owner statements (back to `STATEMENT_SINCE`), parses PDFs, loads Postgres
- `scripts/process_inbox.py` — LLM-classifies remaining inbox mail from the last `INBOX_LOOKBACK_DAYS` days and emails a digest via Resend

Emails are only labeled `RentalTracker/Processed` after successful processing, so transient failures are retried on the next run, and removing the label forces reprocessing.

## 🚀 Quick Start (local)

```bash
git clone https://github.com/probably-kuranes/rental-tracker.git
cd rental-tracker

python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Install PDF parsing tool
brew install poppler           # macOS
# sudo apt-get install poppler-utils  # Ubuntu/Debian

cp .env.example .env
# Fill in GMAIL_APP_PASSWORD, ANTHROPIC_API_KEY, RESEND_API_KEY

# Test mailbox connectivity
python3 -m src.mailbox

# Run the statement ingest
python3 scripts/run_agent.py --dry-run --verbose   # safe preview
python3 scripts/run_agent.py --verbose             # ingest

# Run the inbox digest
python3 scripts/process_inbox.py --dry-run --verbose

# View dashboard
streamlit run dashboard.py
```

## 🔐 Gmail Setup (one-time)

No Google Cloud project, no OAuth. The mailbox account (`GMAIL_USER`) needs:

1. 2-Step Verification enabled
2. An app password: https://myaccount.google.com/apppasswords → create one named
   "rental-tracker" → set it as `GMAIL_APP_PASSWORD`
3. IMAP enabled (Gmail Settings → Forwarding and POP/IMAP — on by default now)

App passwords do not expire (unlike testing-mode OAuth refresh tokens, which
died every 7 days and silently broke the old version of this project).

## ☁️ Cloud Deployment (Railway)

Three Railway services in one project:

| Service | Purpose | Start command |
|---------|---------|---------------|
| `rental-tracker-web` | Streamlit dashboard | `streamlit run dashboard.py --server.port=$PORT --server.address=0.0.0.0` (Dockerfile default) |
| `rental-tracker-cron` | Daily ingest + digest | `./entrypoint.sh` on schedule `0 9 * * *` UTC |
| `Postgres` | Managed database | Railway plugin |

Any push to `main` auto-deploys both app services.

### Environment variables (cron service)

| Variable | Notes |
|----------|-------|
| `DATABASE_URL` | Reference: `${{Postgres.DATABASE_URL}}` |
| `GMAIL_USER` | `mascariproperties@gmail.com` |
| `GMAIL_APP_PASSWORD` | Gmail app password (see Gmail Setup) |
| `GMAIL_SEARCH_QUERY` | Gmail filter for statements (optional, has default) |
| `STATEMENT_SINCE` | `2025/01/01` — earliest statement to ingest |
| `INBOX_LOOKBACK_DAYS` | `7` — digest window |
| `PROCESSED_LABEL` | `RentalTracker/Processed` |
| `ANTHROPIC_API_KEY` | Claude API (triage, synopses, parse fallback) |
| `RESEND_API_KEY` | Resend HTTPS email API |
| `EMAIL_TO` | Digest recipient (`mascari.david@gmail.com`) |

The web service only needs `DATABASE_URL`.

## 📊 Dashboard Features

- **Portfolio Overview**: Total properties, income, expenses, NOI
- **Property Performance**: Income, expenses, and NOI by property
- **Trends**: Multi-month income/expense/NOI lines, per-property NOI over time
- **Expense Breakdown**: Pie charts and top-expense lists
- **Alerts**: High expense ratios, low margins, high repairs
- **Export**: Property-month and expense CSVs
- **Filters**: View by owner or specific property

## 🗂️ Project Structure

```
rental-tracker/
├── README.md
├── requirements.txt
├── .env.example
├── Dockerfile                  # Railway container (web default; cron overrides CMD)
├── entrypoint.sh               # Cron: run_agent.py + process_inbox.py
├── dashboard.py                # Streamlit dashboard
├── src/
│   ├── config.py               # All settings from env vars
│   ├── mailbox.py              # Gmail over IMAP (search, fetch, label)
│   ├── emailer.py              # Resend HTTPS delivery
│   ├── pdf_parser.py           # Mid South Best Rentals PDF parser
│   ├── llm_parser.py           # Claude: classify, summarize, parse fallback
│   ├── classifier.py           # Document/email routing
│   ├── database.py             # SQLAlchemy models (SQLite + Postgres)
│   ├── data_loader.py          # Import parsed data with dedup
│   └── reports.py              # Console reports
├── scripts/
│   ├── run_agent.py            # Statement ingest entry point
│   ├── process_inbox.py        # LLM inbox triage + Resend digest
│   └── setup_db.py
└── tests/
    └── test_parser.py
```

## 💻 Usage

```bash
# Statements (add --since 2025/01/01 to override the backfill floor)
python3 scripts/run_agent.py --dry-run --verbose
python3 scripts/run_agent.py --verbose --summary

# Inbox digest (add --since 2025/01/01 for a full backfill run)
python3 scripts/process_inbox.py --verbose
python3 scripts/process_inbox.py --dry-run

# Ad-hoc against production
railway run python scripts/run_agent.py --verbose
railway logs
```

## 🗄️ Database Schema

- **owners** - Property owners
- **properties** - Rental properties with current rent and deposit
- **monthly_reports** - Portfolio-level monthly summaries
- **property_months** - Property-level monthly performance
- **expenses** - Individual expense line items
- **import_logs** - Track import operations

## 💰 Cost Estimate

- **Railway Hobby plan:** $5/month flat
- **Anthropic API:** pennies per digest run
- **Resend:** free tier (100 emails/day)

## 🛠️ Troubleshooting

### IMAP login fails
- Regenerate the app password and update `GMAIL_APP_PASSWORD`
- Confirm 2FA is still enabled on the account

### No emails found
- Check `GMAIL_SEARCH_QUERY` and `STATEMENT_SINCE`
- Verify the email isn't already labeled `RentalTracker/Processed`
  (remove the label to force reprocessing)

### Railway cron didn't fire
```bash
railway logs --service rental-tracker-cron
```

### Dashboard shows no data
- Local: ensure `rental_tracker.db` exists or set `DATABASE_URL`
- Cloud: confirm `DATABASE_URL` references `${{Postgres.DATABASE_URL}}`

## 🚧 Future Enhancements

- [ ] Export reports to PDF/Excel (CSV export shipped)
- [ ] Year-over-year comparisons
- [ ] Unpaid-bills tracking from the statement's Unpaid Bills section
- [ ] Alerting when a statement fails to arrive on schedule

## 📝 License

MIT

## 👤 Author

Built for tracking Memphis rental properties managed by Mid South Best Rentals.
