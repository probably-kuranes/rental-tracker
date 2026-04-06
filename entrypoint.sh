#!/bin/bash
set -e

# Decode base64-encoded Gmail credentials from environment variables
# (Railway stores secrets as env vars, not mounted files)
if [ ! -z "$GMAIL_CREDENTIALS_B64" ]; then
    echo "$GMAIL_CREDENTIALS_B64" | base64 -d > /tmp/credentials.json
    export GMAIL_CREDENTIALS_FILE=/tmp/credentials.json
fi

if [ ! -z "$GMAIL_TOKEN_B64" ]; then
    echo "$GMAIL_TOKEN_B64" | base64 -d > /tmp/token.json
    export GMAIL_TOKEN_FILE=/tmp/token.json
fi

# Run the rental tracker
echo "Starting rental tracker..."
python3 scripts/run_agent.py --verbose
