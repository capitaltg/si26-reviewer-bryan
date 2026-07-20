#!/usr/bin/env bash
# Run the worker locally against the dev Postgres (5434) + Vercel Blob.
# Loads worker/.env.local, then polls for jobs. Ctrl-C to stop.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -f .env.local ]; then
  echo "worker/.env.local not found — see the committed template." >&2
  exit 1
fi

set -a
# shellcheck disable=SC1091
source .env.local
set +a

if [ "${BLOB_READ_WRITE_TOKEN:-}" = "REPLACE_WITH_STATIC_BLOB_TOKEN" ]; then
  echo "BLOB_READ_WRITE_TOKEN is still the placeholder — paste the real token into worker/.env.local first." >&2
  exit 1
fi

# AWS Bedrock creds are needed for the vision stage; warn if absent but still
# run (ingest/script-align work without them; only the vision pass will fail).
if [ -z "${AWS_ACCESS_KEY_ID:-}" ] || [ -z "${AWS_SECRET_ACCESS_KEY:-}" ]; then
  echo "warning: AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY not set — the vision stage (Bedrock) will fail until you set them." >&2
fi

exec .venv/bin/python -m worker.main
