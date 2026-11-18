#!/bin/sh
# R2's S3 endpoint for the rest of a GitHub Actions job (2026-11-18). The repository's Cloudflare token
# (CLOUDFLARE_API_TOKEN, from the secret CLOUDFLARE_R2_TOKEN) has R2 object read and write on the two buckets this
# pipeline uses (dirtywaterwatch-data, dirtywaterwatch-raw) and D1 read, nothing account-wide: Cloudflare's REST API
# refuses object calls from a bucket-limited token, R2's S3 endpoint accepts them. Cloudflare's S3 credentials for an
# API token are its id (the access key id) and the SHA-256 of its value (the secret access key). This script reads
# the id from the account's token verify endpoint, masks both, and writes AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY,
# AWS_DEFAULT_REGION and R2_S3_ENDPOINT to $GITHUB_ENV, so every later `wrangler r2 object get|put|delete` goes
# through the S3 endpoint (scripts/wrangler_redact.py) and the mail feed reads the raw bucket the same way. It fails
# the step when the token does not verify or the AWS CLI is missing. Run after the wrangler guard step.
set +x   # never trace this script: the key id and the secret are assigned below (Astra r2-s3 review P2)
set -eu
: "${CLOUDFLARE_API_TOKEN:?CLOUDFLARE_API_TOKEN is needed}" "${CLOUDFLARE_ACCOUNT_ID:?CLOUDFLARE_ACCOUNT_ID is needed}"
: "${GITHUB_ENV:?GITHUB_ENV is needed}"
command -v "${AWS_CLI:-aws}" > /dev/null || { echo "::error::r2-s3-keys: the AWS CLI is not installed"; exit 1; }
kid=$(curl -s -m 30 -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
  "https://api.cloudflare.com/client/v4/accounts/$CLOUDFLARE_ACCOUNT_ID/tokens/verify" | python3 -I -c '
import json, re, sys
try:
    d = json.load(sys.stdin)
except ValueError:
    sys.exit(0)
r = d.get("result") or {}
i = str(r.get("id") or "")
print(i if d.get("success") and r.get("status") == "active" and re.fullmatch(r"[0-9a-f]{32}", i) else "")') || kid=""
[ -n "$kid" ] || { echo "::error::r2-s3-keys: the token did not verify on the account endpoint"; exit 1; }
sec=$(python3 -I -c 'import hashlib, os; print(hashlib.sha256(os.environ["CLOUDFLARE_API_TOKEN"].encode()).hexdigest())')
echo "::add-mask::$kid"
echo "::add-mask::$sec"
{
  echo "AWS_ACCESS_KEY_ID=$kid"
  echo "AWS_SECRET_ACCESS_KEY=$sec"
  echo "AWS_DEFAULT_REGION=auto"
  echo "R2_S3_ENDPOINT=https://$CLOUDFLARE_ACCOUNT_ID.r2.cloudflarestorage.com"
} >> "$GITHUB_ENV"
echo "r2-s3-keys: R2 objects go through R2's S3 endpoint from the next step on"
