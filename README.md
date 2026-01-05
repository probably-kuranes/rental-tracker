# 🏠 Rental Property Tracker

Automated system for monitoring rental property owner statements from Mid South Best Rentals. Fetches emails from Gmail, parses PDF statements, stores financial data, and provides interactive visualizations.

**Live Dashboard:** https://rental-tracker-ld8ugdkxncahm2kelwpmfy.streamlit.app/

## ✨ Features

- **📧 Gmail Integration** - Automatically fetches owner statement emails
- **📄 PDF Parsing** - Extracts financial data from Mid South Best Rentals PDFs
- **🗄️ Database Storage** - SQLite for local dev, PostgreSQL for production
- **📊 Interactive Dashboard** - Streamlit web app with charts and metrics
- **☁️ Cloud Deployment** - Runs on Google Cloud Run
- **🔍 Smart Classification** - Routes documents to appropriate parsers
- **⚠️ Alerts** - Flags properties with high expenses or low margins

## 🏗️ Architecture

```
Gmail Inbox
    │
    ▼
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│ Gmail Agent │ ──▶ │ Classifier  │ ──▶ │ PDF Parser  │
└─────────────┘     └─────────────┘     └──────┬──────┘
                                               │
                                               ▼
                                        ┌─────────────┐
                                        │ Data Loader │
                                        └──────┬──────┘
                                               ▼
                                        ┌─────────────┐
                                        │   SQLite    │
                                        └─────────────┘
                                               │
                                               ▼
                                        ┌─────────────┐
                                        │  Streamlit  │
                                        │  Dashboard  │
                                        └─────────────┘
```

## 🚀 Quick Start

### Prerequisites

- Python 3.9+
- Gmail account with API access
- Google Cloud account (for Cloud Run deployment)
- Homebrew (macOS) for installing dependencies

### Local Setup

```bash
# Clone the repository
git clone https://github.com/probably-kuranes/rental-tracker.git
cd rental-tracker

# Install dependencies
pip install -r requirements.txt

# Install PDF parsing tool
brew install poppler  # macOS
# sudo apt-get install poppler-utils  # Ubuntu/Debian

# Configure environment
cp .env.example .env
# Edit .env with your settings

# Set up Gmail API credentials (see Gmail Setup section)

# Initialize database
python3 src/database.py --create

# Run the agent
python3 scripts/run_agent.py --verbose

# View dashboard
streamlit run dashboard.py
```

## 📧 Gmail API Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project
3. Enable the Gmail API
4. Go to APIs & Services → OAuth consent screen
   - Choose "External" user type
   - Add your email as a test user
5. Go to APIs & Services → Credentials
   - Create OAuth 2.0 Client ID (Desktop app)
   - Download as `credentials.json`
6. Authenticate:
   ```bash
   python3 src/gmail_agent.py --auth
   ```

## ☁️ Cloud Deployment

### Google Cloud Run

```bash
cd /Users/davidmascari/Desktop/rental-tracker

# Run deployment script
./deploy/deploy.sh
```

Or manually:

```bash
# Set variables
export PROJECT_ID="your-project-id"
export REGION="us-central1"

# Build and deploy
gcloud builds submit --tag gcr.io/$PROJECT_ID/rental-tracker
gcloud run jobs create rental-tracker-job \
  --image gcr.io/$PROJECT_ID/rental-tracker \
  --region $REGION \
  --set-secrets=/secrets/credentials/credentials.json=gmail-credentials:latest,/secrets/token/token.json=gmail-token:latest

# Run manually
gcloud run jobs execute rental-tracker-job --region $REGION
```

See `deploy/cloud-run-setup.md` for detailed instructions.

### Streamlit Dashboard

The dashboard is automatically deployed to Streamlit Cloud when you push to GitHub.

**Live URL:** https://rental-tracker-ld8ugdkxncahm2kelwpmfy.streamlit.app/

To redeploy:
1. Push changes to GitHub
2. Streamlit Cloud auto-deploys in ~2 minutes

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
├── .gitignore
├── Dockerfile                  # Container for Cloud Run
├── entrypoint.sh              # Cloud Run startup script
├── dashboard.py               # Streamlit dashboard
├── sample_data.db             # Demo database for Streamlit Cloud
├── src/
│   ├── gmail_agent.py         # Email fetching and OAuth
│   ├── pdf_parser.py          # Mid South Best Rentals PDF parser
│   ├── llm_parser.py          # Claude API integration (future)
│   ├── classifier.py          # Document routing
│   ├── database.py            # SQLAlchemy models
│   ├── data_loader.py         # Import parsed data
│   └── reports.py             # Console reports
├── scripts/
│   └── run_agent.py           # Main entry point
└── deploy/
    ├── deploy.sh              # Automated Cloud Run deployment
    └── cloud-run-setup.md     # Detailed deployment guide
```

## 💻 Usage

### Process Emails Locally

```bash
# Dry run (don't modify anything)
python3 scripts/run_agent.py --dry-run --verbose

# Process for real
python3 scripts/run_agent.py --verbose

# With summary report
python3 scripts/run_agent.py --verbose --summary
```

### Run in Google Cloud

```bash
# Execute job manually
gcloud run jobs execute rental-tracker-job --region us-central1

# View executions
gcloud run jobs executions list --job rental-tracker-job --region us-central1

# View logs
gcloud logging read "resource.type=cloud_run_job AND resource.labels.job_name=rental-tracker-job" --limit 50
```

### View Dashboard

```bash
# Run locally
streamlit run dashboard.py

# Or visit cloud deployment
open https://rental-tracker-ld8ugdkxncahm2kelwpmfy.streamlit.app/
```

### Query Database

```bash
# Open SQLite console
sqlite3 rental_tracker.db

# Example queries
SELECT * FROM properties;
SELECT * FROM monthly_reports ORDER BY period_start DESC;
SELECT p.address, pm.total_income, pm.noi
FROM properties p
JOIN property_months pm ON p.id = pm.property_id;

# Exit
.quit
```

## ⚙️ Configuration

Environment variables (`.env` file):

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | Database connection string | `sqlite:///rental_tracker.db` |
| `GMAIL_CREDENTIALS_FILE` | Path to OAuth credentials | `credentials.json` |
| `GMAIL_TOKEN_FILE` | Path to auth token | `token.json` |
| `GMAIL_SEARCH_QUERY` | Gmail search filter | `(from:midsouthbestrentals.com OR from:mascari.david@gmail.com) "Owner Statement" has:attachment` |
| `GMAIL_USER_EMAIL` | Gmail address to monitor | `mascariproperties@gmail.com` |
| `PROCESSED_LABEL` | Label for processed emails | `RentalTracker/Processed` |
| `ANTHROPIC_API_KEY` | Claude API key (future) | - |

## 🗄️ Database Schema

### Tables

- **owners** - Property owners
- **properties** - Rental properties with current rent and deposit
- **monthly_reports** - Portfolio-level monthly summaries
- **property_months** - Property-level monthly performance
- **expenses** - Individual expense line items
- **import_logs** - Track import operations

## 🔐 Security

- Gmail credentials stored in Google Cloud Secret Manager
- Database file excluded from Git (`.gitignore`)
- No sensitive data in code repository
- OAuth tokens refreshed automatically

## 💰 Cost Estimate

**Google Cloud Run:**
- < $2/month for daily runs
- Only pay when job executes

**Streamlit Cloud:**
- Free for public repos

**Total: < $2/month**

## 🛠️ Troubleshooting

### Gmail Authentication Fails

```bash
# Re-authenticate
python3 src/gmail_agent.py --auth

# Check credentials
ls -la credentials.json token.json
```

### No Emails Found

- Check Gmail search query in `.env`
- Verify email has "Owner Statement" in subject
- Check if email already has "RentalTracker/Processed" label

### Cloud Run Job Fails

```bash
# View logs
gcloud logging read "resource.type=cloud_run_job" --limit 50

# Check secrets
gcloud secrets versions list gmail-credentials
gcloud secrets versions list gmail-token
```

### Dashboard Shows No Data

- Local: Ensure `rental_tracker.db` exists
- Cloud: Uses `sample_data.db` from repository

## 🚧 Future Enhancements

- [ ] Automated scheduling (GitHub Actions, Cloud Scheduler, or cron)
- [ ] PostgreSQL for persistent cloud storage
- [ ] Multi-month trend analysis
- [ ] Email notifications for alerts
- [ ] Mobile-responsive dashboard
- [ ] Export reports to PDF/Excel
- [ ] LLM-based parsing for non-standard documents

## 📝 License

MIT

## 👤 Author

Built for tracking 10 Memphis rental properties managed by Midsouth Homebuyers.

---

**Questions?** Check the deployment guide in `deploy/cloud-run-setup.md` or review the code comments.
