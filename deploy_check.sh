#!/usr/bin/env bash
set -euo pipefail
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD required}"
: "${TF_ADMIN_USER:?TF_ADMIN_USER required}"
: "${TF_ADMIN_PASSWORD:?TF_ADMIN_PASSWORD required}"
: "${TF_AUTH_SECRET:?TF_AUTH_SECRET required}"
export TF_ENV=production
python production_check.py
docker compose config >/dev/null
echo "Deployment configuration: OK"
