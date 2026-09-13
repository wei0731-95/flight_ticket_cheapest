#!/usr/bin/env bash
# 在 Linux / NAS 安裝 cron 排程，每 6 小時查一次。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LINE="5 2,8,14,20 * * * /bin/bash $ROOT/scripts/watch.sh"
MARK="# tripcom-fare-watcher"

command -v crontab >/dev/null 2>&1 || { echo "這台機器沒有 crontab，請改用系統內建的排程工具" >&2; exit 1; }

current="$(crontab -l 2>/dev/null || true)"
if printf '%s\n' "$current" | grep -qF "$MARK"; then
  echo "排程已存在，先移除舊的再重新安裝"
  current="$(printf '%s\n' "$current" | grep -vF "$MARK" | grep -vF "scripts/watch.sh" || true)"
fi

printf '%s\n%s\n%s\n' "$current" "$MARK" "$LINE" | grep -v '^$' | crontab -

cat <<MSG
已安裝 cron 排程：
  $LINE

每天 02:05 / 08:05 / 14:05 / 20:05 各查一次（依機器本地時區）。

  看目前排程   crontab -l
  看執行紀錄   tail -f $ROOT/logs/watch-\$(date +%Y%m).log
  移除         crontab -l | grep -v 'scripts/watch.sh' | grep -v '$MARK' | crontab -
MSG
