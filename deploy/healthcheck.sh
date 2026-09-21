#!/bin/sh
set -eu
curl -fsS http://localhost:8000/api/health >/dev/null
