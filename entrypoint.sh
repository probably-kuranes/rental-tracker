#!/bin/bash
# Daily cron entry point (Railway rental-tracker-cron service).
# Sends the rental inbox digest for mascariproperties@gmail.com.
# Statement ingest moved to the v2 tracker-mail service, so it no longer runs here.

exec python3 scripts/process_inbox.py --verbose
