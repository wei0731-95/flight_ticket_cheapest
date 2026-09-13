#!/usr/bin/env bash
# 執行一次票價檢查。設計給 cron / launchd / NAS 排程呼叫。
#
#   scripts/watch.sh                # 正式執行：查詢、寫入歷史、符合條件時寄信
#   scripts/watch.sh --dry-run      # 只查詢並印出，不寄信也不寫歷史
#   scripts/watch.sh --debug-dump   # 另外存下頁面快照到 debug/
#
# 排程呼叫時不會有終端機，所有輸出都寫進 logs/watch-YYYYMM.log。
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1

mkdir -p logs
LOG="$ROOT/logs/watch-$(date +%Y%m).log"
# 只留最近半年的紀錄。
find "$ROOT/logs" -name 'watch-*.log' -mtime +190 -delete 2>/dev/null || true

if [ -x "$ROOT/.venv/bin/python" ]; then
  PY="$ROOT/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PY="$(command -v python3)"
else
  echo "找不到 python3，請先執行 scripts/setup_local.sh" >&2
  exit 127
fi

export PYTHONPATH="$ROOT/src"
export PYTHONUNBUFFERED=1

{
  echo "===== 開始 $(date '+%Y-%m-%d %H:%M:%S %z') ====="
  "$PY" -m tripcom_watcher run "$@"
  status=$?
  echo "===== 結束 status=$status ====="
  echo
} >> "$LOG" 2>&1

exit "${status:-0}"
