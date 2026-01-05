#!/bin/bash
set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Rental Tracker - Cloud Run Deployment${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# Check if gcloud is installed
if ! command -v gcloud &> /dev/null; then
    echo -e "${RED}Error: gcloud CLI not found${NC}"
    echo "Install from: https://cloud.google.com/sdk/docs/install"
    exit 1
fi

# Check if required files exist
if [ ! -f "credentials.json" ]; then
    echo -e "${RED}Error: credentials.json not found${NC}"
    echo "Make sure your Gmail API credentials are in the project root"
    exit 1
fi

if [ ! -f "token.json" ]; then
    echo -e "${RED}Error: token.json not found${NC}"
    echo "Run 'python3 src/gmail_agent.py --auth' first to generate token.json"
    exit 1
fi

# Get project ID
echo -e "${YELLOW}Enter your Google Cloud Project ID:${NC}"
read -r PROJECT_ID

if [ -z "$PROJECT_ID" ]; then
    echo -e "${RED}Error: Project ID cannot be empty${NC}"
    exit 1
fi

export PROJECT_ID
export REGION="us-central1"

echo ""
echo -e "${GREEN}Using:${NC}"
echo "  Project ID: $PROJECT_ID"
echo "  Region: $REGION"
echo ""

# Set project
echo -e "${YELLOW}Setting active project...${NC}"
gcloud config set project "$PROJECT_ID"

# Enable APIs
echo -e "${YELLOW}Enabling required APIs (this may take a minute)...${NC}"
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  secretmanager.googleapis.com \
  scheduler.googleapis.com \
  --quiet

# Store secrets
echo -e "${YELLOW}Creating secrets in Secret Manager...${NC}"

# Check if secrets already exist and update or create
if gcloud secrets describe gmail-credentials --project="$PROJECT_ID" &> /dev/null; then
    echo "  Updating gmail-credentials..."
    gcloud secrets versions add gmail-credentials --data-file=credentials.json
else
    echo "  Creating gmail-credentials..."
    gcloud secrets create gmail-credentials --data-file=credentials.json
fi

if gcloud secrets describe gmail-token --project="$PROJECT_ID" &> /dev/null; then
    echo "  Updating gmail-token..."
    gcloud secrets versions add gmail-token --data-file=token.json
else
    echo "  Creating gmail-token..."
    gcloud secrets create gmail-token --data-file=token.json
fi

# Build container
echo -e "${YELLOW}Building container with Cloud Build...${NC}"
gcloud builds submit --tag "gcr.io/$PROJECT_ID/rental-tracker" --quiet

# Deploy Cloud Run Job
echo -e "${YELLOW}Deploying to Cloud Run...${NC}"

# Get the default compute service account
SERVICE_ACCOUNT="$(gcloud iam service-accounts list --filter='Compute Engine default service account' --format='value(email)')"

gcloud run jobs deploy rental-tracker-job \
  --image "gcr.io/$PROJECT_ID/rental-tracker" \
  --region "$REGION" \
  --set-secrets="/secrets/credentials.json=gmail-credentials:latest,/secrets/token.json=gmail-token:latest" \
  --set-env-vars="DATABASE_URL=sqlite:////tmp/rental_tracker.db,GMAIL_CREDENTIALS_FILE=/secrets/credentials.json,GMAIL_TOKEN_FILE=/secrets/token.json" \
  --max-retries 2 \
  --task-timeout 10m \
  --service-account="$SERVICE_ACCOUNT" \
  --quiet

echo -e "${GREEN}✓ Cloud Run job deployed successfully!${NC}"
echo ""

# Ask about Cloud Scheduler
echo -e "${YELLOW}Do you want to set up Cloud Scheduler to run this automatically? (y/n)${NC}"
read -r SETUP_SCHEDULER

if [ "$SETUP_SCHEDULER" = "y" ] || [ "$SETUP_SCHEDULER" = "Y" ]; then
    echo -e "${YELLOW}How often should it run?${NC}"
    echo "  1) Daily at 9 AM"
    echo "  2) Weekly on Monday at 9 AM"
    echo "  3) Custom cron expression"
    read -r SCHEDULE_CHOICE

    case $SCHEDULE_CHOICE in
        1)
            SCHEDULE="0 9 * * *"
            DESC="daily at 9 AM"
            ;;
        2)
            SCHEDULE="0 9 * * 1"
            DESC="weekly on Mondays at 9 AM"
            ;;
        3)
            echo "Enter cron expression (e.g., '0 9 * * *'):"
            read -r SCHEDULE
            DESC="custom schedule"
            ;;
        *)
            echo -e "${RED}Invalid choice${NC}"
            exit 1
            ;;
    esac

    echo -e "${YELLOW}Creating Cloud Scheduler job ($DESC)...${NC}"

    # Check if scheduler job already exists
    if gcloud scheduler jobs describe rental-tracker-daily --location="$REGION" --project="$PROJECT_ID" &> /dev/null; then
        echo "  Updating existing scheduler job..."
        gcloud scheduler jobs update http rental-tracker-daily \
          --location "$REGION" \
          --schedule "$SCHEDULE" \
          --quiet
    else
        echo "  Creating new scheduler job..."
        gcloud scheduler jobs create http rental-tracker-daily \
          --location "$REGION" \
          --schedule "$SCHEDULE" \
          --uri "https://$REGION-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/$PROJECT_ID/jobs/rental-tracker-job:run" \
          --http-method POST \
          --oauth-service-account-email "$SERVICE_ACCOUNT" \
          --quiet
    fi

    echo -e "${GREEN}✓ Cloud Scheduler configured!${NC}"
fi

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Deployment Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "To test the job manually, run:"
echo -e "${YELLOW}  gcloud run jobs execute rental-tracker-job --region $REGION${NC}"
echo ""
echo "To view logs:"
echo -e "${YELLOW}  gcloud run jobs executions list --job rental-tracker-job --region $REGION${NC}"
echo ""
echo "Estimated monthly cost: < \$2 (without database)"
echo ""
