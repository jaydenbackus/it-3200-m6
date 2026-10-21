#!/usr/bin/env bash
# Sends a mix of normal, 404, error, and slow requests so dashboards and alerts have data.
# Error/slow routes only work when the app runs with ENABLE_SIMULATION=true.
# Usage: ./scripts/generate-traffic.sh [base-url] [duration-seconds]
set -euo pipefail

BASE_URL="${1:-http://localhost:3000}"
DURATION="${2:-300}"
END=$((SECONDS + DURATION))

echo "Sending traffic to $BASE_URL for ${DURATION}s..."
while [ "$SECONDS" -lt "$END" ]; do
  for _ in 1 2 3 4 5 6; do curl -s -o /dev/null "$BASE_URL/"; done
  curl -s -o /dev/null "$BASE_URL/health"
  curl -s -o /dev/null "$BASE_URL/does-not-exist"
  curl -s -o /dev/null "$BASE_URL/simulate/error"
  curl -s -o /dev/null "$BASE_URL/simulate/slow"
  sleep 1
done
echo "Done."
