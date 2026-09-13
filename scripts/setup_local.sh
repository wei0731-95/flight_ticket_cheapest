#!/usr/bin/env bash
# 一次性安裝：建立虛擬環境、安裝套件與 Chromium、備妥 .env。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

command -v python3 >/dev/null 2>&1 || { echo "請先安裝 Python 3.11 以上" >&2; exit 1; }

echo "==> 建立虛擬環境 .venv"
python3 -m venv .venv

echo "==> 安裝套件"
./.venv/bin/pip install --quiet --upgrade pip
./.venv/bin/pip install --quiet -r requirements.txt

echo "==> 安裝 Chromium（第一次會下載約 150MB）"
./.venv/bin/python -m playwright install chromium

if [ ! -f .env ]; then
  cp .env.example .env
  echo "==> 已建立 .env"
fi

cat <<'MSG'

安裝完成。接下來：

  1. 編輯 .env，填入寄信設定
       SMTP_USER      你的 Gmail 地址
       SMTP_PASSWORD  Gmail「應用程式密碼」（16 碼，不是登入密碼）
       MAIL_TO        收件地址
     應用程式密碼申請：https://myaccount.google.com/apppasswords
     （需先開啟兩步驟驗證）

  2. 測試寄信
       PYTHONPATH=src ./.venv/bin/python -m tripcom_watcher test-email

  3. 試跑一次（不寄信、不寫歷史）
       scripts/watch.sh --dry-run

  4. 確認沒問題後安裝排程
       macOS        scripts/install_macos.sh
       Linux / NAS  scripts/install_cron.sh
       Windows      見 README

MSG
