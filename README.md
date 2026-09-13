# 台北 → 富國島 機票監控

定期到 trip.com 查 **台北（松山 TSA / 桃園 TPE）→ 富國島（PQC）** 的來回機票，
出現歷史新低時自動寄 Email 通知。

## 監控內容

| 項目 | 設定 |
| --- | --- |
| 出發機場 | 松山（TSA）、桃園（TPE）— 各查一次後合併比價 |
| 目的地 | 富國島（PQC） |
| 可出發日 | 最早 2027-02-09 |
| 必須回台 | 最晚 2027-02-14 |
| 日期組合 | 4～5 夜，共 3 組：2/9→2/13、2/10→2/14（五天四夜）、2/9→2/14（六天五夜） |
| 乘客 | 5 成人 + 2 兒童（8、10 歲） |
| 艙等 | 經濟艙 |
| 轉機 | 不限（台北直飛富國島班次極少，多半需在胡志明或河內轉機） |
| 頻率 | 每 6 小時（02:05 / 08:05 / 14:05 / 20:05） |
| 通知 | 出現歷史新低時寄 Email |

每次執行 = 2 個機場 × 3 組日期 = **6 次查詢**，全部結果一起比較後取最便宜。
所有項目都在 [`config.yaml`](config.yaml) 裡，改了就生效，不用動程式碼。

---

## ⚠️ 必須在自己的電腦上跑，不能用 GitHub Actions

這件事是實測出來的，不是猜的。在 GitHub Actions 上跑了五次，trip.com 回的是
**不含任何票價的靜態頁面**：

| 觀察 | 結果 |
| --- | --- |
| 搜尋參數是否正確 | ✅ 正確，頁面顯示 `Taipei · All airports / Phu Quoc Island / 7 passengers · Economy` |
| 是否跳人機驗證 | ❌ 沒有 —— 不擋你，只是給你一個不會動的殼 |
| 對 trip.com 自家 API 的請求 | **0 筆**（點擊搜尋按鈕前後都是 0） |
| 頁面上的其他請求 | 4 筆，全是第三方廣告追蹤（naver、google ccm、doubleclick） |
| 原始 HTML 是否含票價 | ❌ 267KB 的 HTML 裡一個機票價格都沒有 |

也就是說 trip.com 對資料中心 IP（GitHub Actions 跑在 Azure IP 段）**靜默降級供應內容**。
這不是 selector、渲染或解析的問題，調程式碼解決不了。

**家用網路是住宅 IP，正是 trip.com 願意正常供應的對象**，所以監控要跑在你自己的
機器上。`.github/workflows/watch-fares.yml` 的排程已經停用（留著手動觸發，
日後想確認 trip.com 是否放行雲端 IP 時可以用）。

---

## 安裝

### 1. 取得程式並安裝相依套件

```bash
git clone https://github.com/wei0731-95/flight_ticket_cheapest.git
cd flight_ticket_cheapest
scripts/setup_local.sh
```

`setup_local.sh` 會建立虛擬環境、安裝套件與 Chromium（約 150MB），並備好 `.env`。
需要 Python 3.11 以上。

### 2. 設定寄信

編輯 `.env`：

```ini
SMTP_USER=你的帳號@gmail.com
SMTP_PASSWORD=十六碼應用程式密碼
MAIL_TO=wwojiaoao@gmail.com
```

Gmail 必須用**應用程式密碼**，不是登入密碼：

1. 到 <https://myaccount.google.com/security> 開啟「兩步驟驗證」
2. 到 <https://myaccount.google.com/apppasswords> 產生 16 碼密碼
3. 去掉空格填進 `SMTP_PASSWORD`

驗證設定正確：

```bash
PYTHONPATH=src ./.venv/bin/python -m tripcom_watcher test-email
```

### 3. 先手動跑一次

```bash
scripts/watch.sh --dry-run
```

`--dry-run` 只查詢並印出結果，不寄信也不寫歷史。確認有抓到票價再往下。
抓不到的話看下面「抓不到價格怎麼辦」。

### 4. 安裝排程

| 平台 | 指令 |
| --- | --- |
| macOS | `scripts/install_macos.sh` |
| Linux / NAS | `scripts/install_cron.sh` |
| Windows | 見下方 |

兩個安裝腳本都會設定成每天 02:05 / 08:05 / 14:05 / 20:05 各查一次，
並印出「立刻試跑 / 看紀錄 / 移除」的指令。

**Windows** 用工作排程器，在專案資料夾開 PowerShell 執行：

```powershell
$root = (Get-Location).Path
schtasks /Create /TN "TripcomFareWatcher" /SC DAILY /ST 02:05 /RI 360 /DU 24:00 `
  /TR "powershell -ExecutionPolicy Bypass -NoProfile -File `"$root\scripts\watch.ps1`"" /F
```

移除：`schtasks /Delete /TN "TripcomFareWatcher" /F`

### 機器要開著

排程只在機器開機且醒著時才會執行：

- **Mac 睡眠時不會跑**，醒來後 launchd 會補跑錯過的那一次。想穩定每 6 小時都跑到，
  就把睡眠關掉，或改用一直開機的機器。
- **NAS、Raspberry Pi、迷你主機**最適合，24 小時開著又省電。
- 漏掉幾次不會壞事 —— 歷史最低價存在本機檔案裡，下次跑還是照常比較。

---

## 日常操作

所有指令都在專案資料夾下執行。

```bash
scripts/watch.sh                 # 查一次（排程跑的就是這個）
scripts/watch.sh --dry-run       # 查一次但不寄信、不寫歷史
scripts/watch.sh --force-email    # 不論有無新低都寄一封
scripts/watch.sh --debug-dump     # 另外存頁面快照到 debug/

tail -f logs/watch-$(date +%Y%m).log        # 看執行紀錄
```

直接用 CLI（不經過 wrapper）：

```bash
export PYTHONPATH=src
./.venv/bin/python -m tripcom_watcher queries      # 看會查哪些組合與對應網址
./.venv/bin/python -m tripcom_watcher report       # 印出歷史最低價摘要
./.venv/bin/python -m tripcom_watcher test-email   # 寄測試信
./.venv/bin/python -m pytest -q                    # 跑測試
```

| 參數 | 用途 |
| --- | --- |
| `--dry-run` | 只查詢並印出，不寄信、不寫歷史 |
| `--no-email` | 寫歷史但不寄信 |
| `--force-email` | 不論有無新低都寄一封 |
| `--debug-dump` | 存頁面 HTML / XHR JSON / 截圖到 `debug/` |
| `--only SUBSTR` | 只跑 key 含這段字的查詢，例如 `--only 2027-02-10` |
| `--fail-on-empty` | 完全沒抓到票價時以非零結束碼退出 |

如果你的環境已經有 Chromium，可以用 `PLAYWRIGHT_CHROMIUM_EXECUTABLE=/path/to/chrome`
指定它，省掉下載。

---

## 通知規則

預設只在「**比過去所有紀錄都便宜**」時寄信，所以不會每 6 小時收到一封。
判定基準是**全團估算總價**（見下節），而不是單人票價。

`config.yaml` 的 `notify` 區段：

```yaml
notify:
  on_new_low: true            # 出現歷史新低就寄信
  absolute_threshold: null     # 低於這個金額也寄信（TWD），例如 90000
  min_drop: 1                  # 至少要再便宜這個金額才算新低，避免小幅波動洗版
  always_summary: false        # 改成 true 就每次都寄一封摘要
  failure_alert_threshold: 3   # 連續幾次完全抓不到價格就寄警告信
```

幾個刻意的設計：

- **首次取得報價也會寄一封**，讓你知道監控確實開始運作、目前的基準價是多少。
- **`absolute_threshold` 不會重複轟炸**：同一個價位只通知一次，只有再往下破才會再寄。
- **單次失敗不通知**，連續 3 次都抓不到才寄警告信。

2027/2/6 是農曆初一，你要的 2/9–2/14 正好是年假尾段與收假潮，票價本來就高、
波動也大。建議第一封「開始監控」的信到手後，看一下基準價再把
`absolute_threshold` 設成你願意出手的金額。

---

## 價格怎麼算的（重要）

trip.com 有時顯示「每位成人」票價、有時顯示總價，而且同一頁不同版本可能不一樣。
直接比較這兩種數字會產生假的「新低」，所以程式一律換算成**全團估算總價**後再比較：

- trip.com 有給總價 → 直接用它的總價
- 只有每人票價 → 以 `每人票價 × 7`（5 成人 + 2 兒童佔位）估算

信裡會同時顯示「全團估算」和「trip.com 實際顯示的數字」，並標注是哪一種。

⚠️ **估算值只用於比價排序，不是報價。** 兒童票通常比成人便宜，行李、稅金、手續費
也依航空公司而異，**實際金額請到 trip.com 結帳頁確認**。信裡每個組合都有直達
trip.com 搜尋頁的連結。

---

## 抓不到價格怎麼辦

程式用三層 fallback 抓價格，任一層成功就採用：

| 層 | 方式 | 取得的資訊 |
| --- | --- | --- |
| `xhr` | 攔截頁面載入時的 JSON API 回應 | 最完整：航空公司、航班號、轉機、時刻 |
| `dom` | 讀渲染完成的結果卡片 | 價格、航空公司、轉機次數 |
| `text` | 正則掃整頁的金額，取最低的合理值 | 只有價格 |

信件和 log 都會標注這次是哪一層抓到的（`source=xhr` / `dom` / `text`）。
降到 `text` 代表前兩層的結構對不上了，值得看一下。

**完全抓不到時：**

```bash
scripts/watch.sh --dry-run --debug-dump --only TPE-PQC_2027-02-09_2027-02-13
```

log 會印出一段 `[診斷]`，包含重導後的最終網址、頁面標題、內文前 800 字、
頁面出現的幣別符號、原始 HTML 裡的金額數量，以及**頁面發出的所有 XHR 端點**。
`debug/` 下還有完整 HTML、截圖與攔截到的 JSON。對照這些：

- 出現人機驗證 → 把 `config.yaml` 的 `scrape.delay_between_queries_s` 調大
  （例如 `[30, 90]`）、`attempts` 調大，並降低排程頻率
- 對 trip.com 自家網域 0 筆請求、HTML 也沒有票價 → 你的 IP 被降級供應，
  換個網路試試
- 有 XHR 但解析不到 → 看 `debug/*/xhr-*.json` 裡價格在哪個欄位，
  補進 `src/tripcom_watcher/parsing.py` 上方的 key 提示（`_PRICE_KEY` / `_SEGMENT_KEYS` 等）
- 卡片抓不到 → 從 `debug/*/page.html` 找結果卡片的 CSS selector，
  填進 `config.yaml` 的 `scrape.card_selectors`

`scrape.price_sanity_min` / `price_sanity_max` 界定「合理票價」範圍（預設
3,000–600,000 TWD），用來濾掉行李費、稅金等雜訊。**如果 trip.com 以外幣顯示價格，
真實票價會落在範圍外而被全部濾掉，症狀看起來就是「找不到票價」** —— 診斷輸出的
「頁面出現的幣別符號」就是用來判斷這件事的。

---

## 價格歷史

每次執行的結果寫進 [`data/price_history.json`](data/price_history.json)：

- `best` — 每組日期組合與整體的歷史最低（含當時的航班明細）
- `runs` — 最近每次執行的結果（預設保留 500 筆，由 `storage.keep_runs` 控制）

`python -m tripcom_watcher report` 可以直接把這些印出來。這個檔案有被 git 追蹤，
想備份的話偶爾 commit 上去即可；不 commit 也不影響運作。

---

## 專案結構

```
config.yaml                      搜尋條件、爬取行為、通知規則（改這裡就好）
scripts/
  setup_local.sh                 一次性安裝：venv、套件、Chromium、.env
  watch.sh                       執行一次檢查，排程呼叫的就是這支
  watch.ps1                      同上，Windows 版
  install_macos.sh               安裝 launchd 排程
  install_cron.sh                安裝 cron 排程（Linux / NAS）
src/tripcom_watcher/
  cli.py                         指令入口：run / queries / report / test-email
  config.py                      讀取與驗證 config.yaml
  queries.py                     產生日期組合與 trip.com 搜尋網址
  scraper.py                     Playwright 爬取：反偵測、送出搜尋、重試、診斷輸出
  browser_js.py                  注入頁面的 JS（反偵測、等待價格、擷取卡片、定位搜尋鈕）
  parsing.py                     三層票價解析（xhr / dom / text）
  pricing.py                     把不同基準的價格換算成可比較的全團總價
  storage.py                     價格歷史讀寫與歷史最低追蹤
  alerts.py                      判斷這次要不要通知
  report.py                      產生信件主旨、HTML 與純文字內容
  notify.py                      SMTP 寄信
tests/                           91 個測試，含 trip.com 回應的 fixture
.github/workflows/
  tests.yml                      push / PR 時跑測試
  watch-fares.yml                排程已停用，僅保留手動觸發
```

---

## 已知限制

- **雲端跑不動。** 見上面的實測結果。這是 trip.com 的來源 IP 政策，不是程式問題。
- **松山（TSA）大概查不到結果。** 松山的國際線只有東京羽田、首爾金浦、上海虹橋，
  到富國島要轉兩段以上，trip.com 很可能回空。這是預期行為，不是錯誤；
  不想看到它的失敗訊息，把 `config.yaml` 的 `origins` 改成 `[TPE]` 就好。
- **爬蟲不是官方 API。** trip.com 改版或加強風控都可能讓它失效，
  所以有連續失敗警告信和診斷輸出機制。
- **解析層尚未對「有票價的」trip.com 頁面驗證過。** 三層解析是對著模擬的回應結構
  與本機假頁面測的（都跑過真實 Chromium），但雲端環境拿不到真實票價頁面，
  所以無法確認欄位名稱與實際相符。第一次在你的電腦上跑時請加 `--debug-dump`，
  照上面的步驟核對一次。
