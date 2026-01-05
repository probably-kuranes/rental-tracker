#!/bin/bash
set -e

# Copy secrets to writable locations
echo "Copying credentials to writable locations..."
cp /secrets/credentials/credentials.json /tmp/credentials.json
cp /secrets/token/token.json /tmp/token.json

# Update environment variables to point to writable copies
export GMAIL_CREDENTIALS_FILE=/tmp/credentials.json
export GMAIL_TOKEN_FILE=/tmp/token.json

# Run the rental tracker
echo "Starting rental tracker..."
python3 scripts/run_agent.py --verbose
