#!/usr/bin/env bash
# 在 macOS 安裝排程（launchd），每 6 小時查一次：02:05 / 08:05 / 14:05 / 20:05。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL="com.tripcom.fare-watcher"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

mkdir -p "$HOME/Library/LaunchAgents" "$ROOT/logs"

cat > "$PLIST" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$ROOT/scripts/watch.sh</string>
  </array>
  <key>WorkingDirectory</key><string>$ROOT</string>
  <key>StartCalendarInterval</key>
  <array>
    <dict><key>Hour</key><integer>2</integer><key>Minute</key><integer>5</integer></dict>
    <dict><key>Hour</key><integer>8</integer><key>Minute</key><integer>5</integer></dict>
    <dict><key>Hour</key><integer>14</integer><key>Minute</key><integer>5</integer></dict>
    <dict><key>Hour</key><integer>20</integer><key>Minute</key><integer>5</integer></dict>
  </array>
  <key>StandardOutPath</key><string>$ROOT/logs/launchd.out.log</string>
  <key>StandardErrorPath</key><string>$ROOT/logs/launchd.err.log</string>
  <key>RunAtLoad</key><false/>
</dict>
</plist>
PLIST_EOF

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"

cat <<MSG
已安裝排程：$PLIST
每天 02:05 / 08:05 / 14:05 / 20:05 各查一次。

  立刻試跑一次   launchctl start $LABEL
  看執行紀錄     tail -f $ROOT/logs/watch-\$(date +%Y%m).log
  暫停           launchctl unload $PLIST
  移除           launchctl unload $PLIST && rm $PLIST

注意：Mac 睡眠時 launchd 不會執行，醒來後會補跑錯過的那一次。
若希望穩定每 6 小時都跑到，請到「系統設定 → 電池 / 節能」把睡眠關掉，
或改用一直開機的機器（NAS、Raspberry Pi）。
MSG
