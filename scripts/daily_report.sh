#!/bin/bash
# =============================================================================
# 정리 폴더에 파일이 얼마나 쌓였는지 매일 기록하는 스크립트 (파일은 옮기지 않음)
#
#   ./scripts/daily_report.sh           → 흩어진 파일·정리된 파일 수 한 줄 출력
#   ./scripts/daily_report.sh --scan    → AI로 살펴보고 분류별 개수까지 출력 (정리 계획만 만듦)
#
# 매일 밤 9시에 자동 실행 (crontab -e 에 한 줄 추가):
#   0 21 * * * /home/내아이디/file-secretary/scripts/daily_report.sh >> ~/file-secretary.log 2>&1
# =============================================================================
set -euo pipefail

API_URL="${API_URL:-http://localhost:8000}"
ENV_FILE="$(dirname "$0")/../.env"
if [ -z "${SECRETARY_API_KEY:-}" ] && [ -f "$ENV_FILE" ]; then
    SECRETARY_API_KEY="$(grep -E '^SECRETARY_API_KEY=' "$ENV_FILE" | cut -d= -f2-)"
fi

for cmd in curl jq; do
    command -v "$cmd" >/dev/null || { echo "'$cmd'가 필요합니다: sudo apt install -y $cmd" >&2; exit 1; }
done

call() {  # call 메서드 경로
    curl -sS --fail -X "$1" -H "X-API-Key: ${SECRETARY_API_KEY:-}" -H "Content-Type: application/json" \
        "${API_URL}$2" ${3:+-d "$3"}
}

now="$(date '+%Y-%m-%d %H:%M')"
call GET /api/v1/stats | jq -r --arg now "$now" \
    '"\($now)  흩어진 파일 \(.loose_files)개 · 정리된 파일 \(.organized_files)개"'

if [ "${1:-}" = "--scan" ]; then
    call POST /api/v1/plans '{}' | jq -r '
        "  살펴본 파일 \(.total)개 (분석: \(.llm_source))",
        (.items | group_by(.category) | map("  - \(.[0].category): \(length)개") | .[]),
        "  → 대시보드(http://localhost:8501)에서 확인 후 정리하세요."'
fi
