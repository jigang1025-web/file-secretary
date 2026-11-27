#!/bin/bash
# 연습 폴더(demo/inbox)를 '정리 전' 상태로 되돌린다 (발표 리허설 전에 실행).
# 진짜 폴더가 연결되어 있으면 서버가 거부한다 (안전장치).
set -euo pipefail

API_URL="${API_URL:-http://localhost:8000}"
ENV_FILE="$(dirname "$0")/../.env"
if [ -z "${SECRETARY_API_KEY:-}" ] && [ -f "$ENV_FILE" ]; then
    SECRETARY_API_KEY="$(grep -E '^SECRETARY_API_KEY=' "$ENV_FILE" | cut -d= -f2-)"
fi

curl -sS --fail -X POST -H "X-API-Key: ${SECRETARY_API_KEY:-}" "${API_URL}/api/v1/demo/reset"
echo
