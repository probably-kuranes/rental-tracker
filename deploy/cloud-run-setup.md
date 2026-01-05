# Google Cloud Run Deployment Guide

This guide walks you through deploying the Rental Tracker to Google Cloud Run.

## Prerequisites

1. Google Cloud account with billing enabled
2. `gcloud` CLI installed ([Install guide](https://cloud.google.com/sdk/docs/install))
3. Docker installed locally (for testing)

## Step 1: Set up Google Cloud Project

```bash
# Set your project ID
export PROJECT_ID="rental-tracker-YOUR_ID"
export REGION="us-central1"

# Create project (if new)
gcloud projects create $PROJECT_ID

# Set active project
gcloud config set project $PROJECT_ID

# Enable required APIs
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  secretmanager.googleapis.com \
  sqladmin.googleapis.com \
  scheduler.googleapis.com
```

## Step 2: Store Secrets in Secret Manager

```bash
# Store Gmail credentials
gcloud secrets create gmail-credentials \
  --data-file=credentials.json

# Store Gmail token
gcloud secrets create gmail-token \
  --data-file=token.json

# Create a .env.production file with your settings
cat > .env.production << EOF
DATABASE_URL=sqlite:////tmp/rental_tracker.db
GMAIL_CREDENTIALS_FILE=/secrets/credentials.json
GMAIL_TOKEN_FILE=/secrets/token.json
GMAIL_SEARCH_QUERY=(from:midsouthbestrentals.com OR from:mascari.david@gmail.com) "Owner Statement" has:attachment
GMAIL_USER_EMAIL=mascariproperties@gmail.com
PROCESSED_LABEL=RentalTracker/Processed
DOWNLOAD_DIR=/tmp/downloads
EOF

# Store environment config
gcloud secrets create app-env \
  --data-file=.env.production
```

## Step 3: Build and Deploy Container

```bash
# Build container using Cloud Build
gcloud builds submit --tag gcr.io/$PROJECT_ID/rental-tracker

# Deploy to Cloud Run as a JOB (not a service)
gcloud run jobs create rental-tracker-job \
  --image gcr.io/$PROJECT_ID/rental-tracker \
  --region $REGION \
  --set-secrets=/secrets/credentials.json=gmail-credentials:latest,/secrets/token.json=gmail-token:latest \
  --set-env-vars=DATABASE_URL=sqlite:////tmp/rental_tracker.db,GMAIL_CREDENTIALS_FILE=/secrets/credentials.json,GMAIL_TOKEN_FILE=/secrets/token.json \
  --max-retries 2 \
  --task-timeout 10m

# Test the job manually
gcloud run jobs execute rental-tracker-job --region $REGION
```

## Step 4: Set up Cloud Scheduler (Automation)

```bash
# Create a schedule to run daily at 9 AM
gcloud scheduler jobs create http rental-tracker-daily \
  --location $REGION \
  --schedule "0 9 * * *" \
  --uri "https://$REGION-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/$PROJECT_ID/jobs/rental-tracker-job:run" \
  --http-method POST \
  --oauth-service-account-email $PROJECT_ID@appspot.gserviceaccount.com

# Or run weekly on Mondays
# --schedule "0 9 * * 1"
```

## Step 5: (Optional) Set up PostgreSQL Database

For production use with persistent storage:

```bash
# Create Cloud SQL PostgreSQL instance
gcloud sql instances create rental-tracker-db \
  --database-version=POSTGRES_15 \
  --tier=db-f1-micro \
  --region=$REGION

# Create database
gcloud sql databases create rental_tracker \
  --instance=rental-tracker-db

# Set password
gcloud sql users set-password postgres \
  --instance=rental-tracker-db \
  --password=YOUR_SECURE_PASSWORD

# Update DATABASE_URL in secrets to use PostgreSQL
# postgresql://postgres:PASSWORD@/rental_tracker?host=/cloudsql/PROJECT_ID:REGION:rental-tracker-db
```

## Costs Estimate

- **Cloud Run Job**: ~$0.10-1.00/month (running daily for a few minutes)
- **Secret Manager**: $0.06/month (3 secrets)
- **Cloud Scheduler**: $0.10/month (1 job)
- **Cloud SQL** (optional): ~$7/month (db-f1-micro)

**Total without Cloud SQL: < $2/month**
**Total with Cloud SQL: ~$8-10/month**

## Monitoring and Logs

```bash
# View job executions
gcloud run jobs executions list --job rental-tracker-job --region $REGION

# View logs
gcloud logging read "resource.type=cloud_run_job AND resource.labels.job_name=rental-tracker-job" --limit 50
```

## Troubleshooting

**Issue: "Permission denied" errors**
- Ensure the default service account has necessary permissions
- Grant Secret Manager Secret Accessor role

**Issue: Gmail authentication fails**
- Verify credentials.json and token.json are correctly uploaded to Secret Manager
- Check that the secrets are mounted at the correct paths

**Issue: Database not persisting**
- SQLite in /tmp will not persist between runs
- Use Cloud SQL PostgreSQL for production
