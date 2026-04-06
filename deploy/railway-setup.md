# Railway Deployment Guide

Deploy the Rental Tracker on Railway with PostgreSQL, a Streamlit dashboard, and a daily cron job.

## Prerequisites

1. [Railway account](https://railway.com) (Pro plan recommended for cron jobs)
2. [Railway CLI](https://docs.railway.com/guides/cli) installed (`brew install railway` or `npm install -g @railway/cli`)
3. Gmail API credentials (`credentials.json`) and auth token (`token.json`) — run `python3 src/gmail_agent.py --auth` locally first

## Architecture

```
Railway Project
├── PostgreSQL (database plugin)
├── Web Service (Streamlit dashboard, from Procfile)
└── Cron Service (daily email agent, from entrypoint.sh)
```

## Step 1: Create the Railway Project

1. Go to https://railway.com/new and create a new project
2. Connect your GitHub repo (`probably-kuranes/rental-tracker`)
3. Railway will auto-detect the Python app and deploy the web service using the `Procfile`

## Step 2: Add PostgreSQL

1. In your Railway project, click **New** → **Database** → **Add PostgreSQL**
2. Railway automatically creates `DATABASE_URL` — link it to both services
3. The app's `Database` class already handles PostgreSQL via SQLAlchemy

## Step 3: Set Environment Variables

In the Railway dashboard, set these variables for **both** services:

| Variable | Value | Notes |
|----------|-------|-------|
| `DATABASE_URL` | (auto from PostgreSQL plugin) | Use Railway's `${{Postgres.DATABASE_URL}}` reference |
| `GMAIL_CREDENTIALS_B64` | `base64 < credentials.json` | Run locally, paste output |
| `GMAIL_TOKEN_B64` | `base64 < token.json` | Run locally, paste output |
| `GMAIL_SEARCH_QUERY` | `(from:midsouthbestrentals.com OR from:mascari.david@gmail.com) "Owner Statement" has:attachment` | |
| `GMAIL_USER_EMAIL` | `mascariproperties@gmail.com` | |
| `PROCESSED_LABEL` | `RentalTracker/Processed` | |
| `DOWNLOAD_DIR` | `/tmp/downloads` | |
| `PYTHONUNBUFFERED` | `1` | |

**Tip:** Use Railway's shared variables to avoid duplicating between services.

## Step 4: Create the Cron Service

1. In your Railway project, click **New** → **Service**
2. Connect the same GitHub repo
3. Set the **Start Command** to: `./entrypoint.sh`
4. Under **Settings** → **Cron Schedule**, set: `0 9 * * *` (daily at 9 AM UTC)
5. Link the PostgreSQL `DATABASE_URL` to this service

The cron service uses the Dockerfile (which installs `poppler-utils` for PDF parsing).

## Step 5: Initialize the Database

Run once after first deploy:

```bash
railway link  # connect to your project
railway run python3 scripts/setup_db.py
```

## Step 6: Verify

1. Check the web service URL in Railway dashboard — your Streamlit dashboard should be live
2. Trigger the cron service manually from the Railway dashboard to test the email pipeline
3. Check the dashboard for imported data

## Updating Gmail Token

The Gmail OAuth token expires periodically. When it does:

1. Run locally: `python3 src/gmail_agent.py --auth`
2. Re-encode: `base64 < token.json | pbcopy`
3. Update `GMAIL_TOKEN_B64` in Railway dashboard

The app will auto-refresh the token when possible, but if the refresh token itself expires, you'll need to re-authenticate locally.

## Cost

Railway Pro plan: $5/month base + usage. For this app (small PostgreSQL, lightweight cron, low-traffic Streamlit), expect ~$5-10/month total.

## Automated Deployment (deploy.sh)

For a scripted setup, run `./deploy/deploy.sh` from the project root. It base64-encodes your credentials and sets Railway environment variables automatically.
