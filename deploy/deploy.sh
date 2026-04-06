#!/bin/bash
set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Rental Tracker - Railway Deployment${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""

# Check if railway CLI is installed
if ! command -v railway &> /dev/null; then
    echo -e "${RED}Error: Railway CLI not found${NC}"
    echo "Install: npm install -g @railway/cli"
    echo "Or: brew install railway"
    exit 1
fi

# Check if logged in
if ! railway whoami &> /dev/null; then
    echo -e "${YELLOW}Logging in to Railway...${NC}"
    railway login
fi

# Check required local files for generating base64 env vars
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

echo ""
echo -e "${YELLOW}Step 1: Generating base64-encoded credentials...${NC}"
GMAIL_CREDENTIALS_B64=$(base64 < credentials.json)
GMAIL_TOKEN_B64=$(base64 < token.json)
echo -e "${GREEN}  Done.${NC}"

echo ""
echo -e "${YELLOW}Step 2: Link to your Railway project.${NC}"
echo "  If this is a new project, create one at https://railway.com/new"
echo "  Then run: railway link"
echo ""
echo -e "${YELLOW}Is this project already linked? (y/n)${NC}"
read -r LINKED

if [ "$LINKED" != "y" ] && [ "$LINKED" != "Y" ]; then
    railway link
fi

echo ""
echo -e "${YELLOW}Step 3: Setting environment variables...${NC}"
railway variables set \
    GMAIL_CREDENTIALS_B64="$GMAIL_CREDENTIALS_B64" \
    GMAIL_TOKEN_B64="$GMAIL_TOKEN_B64" \
    GMAIL_SEARCH_QUERY='(from:midsouthbestrentals.com OR from:mascari.david@gmail.com) "Owner Statement" has:attachment' \
    GMAIL_USER_EMAIL=mascariproperties@gmail.com \
    PROCESSED_LABEL=RentalTracker/Processed \
    DOWNLOAD_DIR=/tmp/downloads \
    PYTHONUNBUFFERED=1

echo -e "${GREEN}  Environment variables set.${NC}"
echo ""
echo -e "${YELLOW}NOTE: Set DATABASE_URL manually in the Railway dashboard${NC}"
echo "  after adding the PostgreSQL plugin (it auto-provides the URL)."
echo ""

echo -e "${YELLOW}Step 4: Deploying...${NC}"
railway up

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Deployment Complete!${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo "Next steps:"
echo "  1. Add PostgreSQL plugin in Railway dashboard"
echo "  2. Link DATABASE_URL to both the web and cron services"
echo "  3. Create a cron service for the email agent:"
echo "     - Same repo, start command: ./entrypoint.sh"
echo "     - Cron schedule: 0 9 * * * (daily at 9 AM UTC)"
echo "  4. Initialize the database:"
echo "     railway run python3 scripts/setup_db.py"
echo ""
echo "Dashboard URL will be shown in the Railway dashboard once deployed."
echo ""
