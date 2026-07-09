#!/bin/bash
# Daily cron entry point (Railway cron service).
# Runs the statement ingest, then the LLM inbox digest. A failure in one
# doesn't block the other; the exit code reflects whether anything failed.

status=0

echo "=== Statement ingest ==="
python3 scripts/run_agent.py --verbose || status=1

echo "=== Inbox digest ==="
python3 scripts/process_inbox.py --verbose || status=1

exit $status
