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
| 頻率 | 每 6 小時（台北時間約 02:05 / 08:05 / 14:05 / 20:05） |
| 通知 | 出現歷史新低時寄 Email |

每次執行 = 2 個機場 × 3 組日期 = **6 次查詢**，全部結果一起比較後取最便宜。
所有項目都在 [`config.yaml`](config.yaml) 裡，改了就生效，不用動程式碼。

## 開始使用（三步）

### 1. 設定寄信用的 Secrets

到 **Settings → Secrets and variables → Actions → New repository secret**，加入：

| Secret | 值 |
| --- | --- |
| `SMTP_USER` | 你的 Gmail 地址，例如 `you@gmail.com` |
| `SMTP_PASSWORD` | Gmail **應用程式密碼**（16 碼，不是登入密碼） |
| `MAIL_TO` | 收件地址，例如 `wwojiaoao@gmail.com`（多個用逗號分隔） |
| `MAIL_FROM` | 選填，預設同 `SMTP_USER` |
| `SMTP_HOST` / `SMTP_PORT` | 選填，預設 `smtp.gmail.com` / `587` |

**怎麼拿 Gmail 應用程式密碼：**

1. 到 <https://myaccount.google.com/security> 開啟「兩步驟驗證」（沒開的話下一步會找不到）
2. 到 <https://myaccount.google.com/apppasswords> 建立一組應用程式密碼
3. 複製那 16 碼、去掉空格，填進 `SMTP_PASSWORD`

### 2. 確認排程跑在預設分支上

**GitHub 的排程（`schedule`）只會在 repo 的預設分支上執行。**

這個 repo 目前的預設分支就是 `claude/busy-brown-ttm0dm` —— 空 repo 第一個被推上來的
分支會自動成為預設分支，所以排程**不需要額外合併就會運作**。

之後如果你把預設分支換成 `main` 或其他分支，記得把這份程式一起帶過去，
否則 cron 會停止觸發。

### 3. 手動跑一次確認

到 **Actions → 機票監控 → Run workflow**，把 `debug_dump` 和 `force_email` 都勾起來，執行。

- `force_email` 會強制寄信，可以確認 SMTP 設定正確
- `debug_dump` 會把 trip.com 的實際頁面 HTML、XHR JSON 和截圖存成 artifact，
  萬一抓不到價格，這些檔案就是找出原因的依據（見下面「抓不到價格怎麼辦」）

## 本機執行

```bash
pip install -r requirements-dev.txt
python -m playwright install chromium

cp .env.example .env       # 填入 SMTP 設定
export PYTHONPATH=src

python -m tripcom_watcher queries            # 看會查哪些組合，以及對應的 trip.com 網址
python -m tripcom_watcher run --dry-run      # 查一次，印出結果，不寄信也不寫歷史
python -m tripcom_watcher run --debug-dump   # 查一次並把頁面快照存到 debug/
python -m tripcom_watcher report             # 印出歷史最低價摘要
python -m tripcom_watcher test-email         # 寄一封測試信
python -m pytest -q                          # 跑測試
```

常用參數：

| 參數 | 用途 |
| --- | --- |
| `--dry-run` | 只查詢並印出，不寄信、不寫歷史 |
| `--no-email` | 寫歷史但不寄信 |
| `--force-email` | 不論有無新低都寄一封 |
| `--debug-dump` | 存頁面 HTML / XHR JSON / 截圖到 `debug/` |
| `--only SUBSTR` | 只跑 key 含這段字的查詢，例如 `--only 2027-02-10` |
| `--fail-on-empty` | 完全沒抓到票價時以非零結束碼退出 |

如果你的環境已經有 Chromium，可以用 `PLAYWRIGHT_CHROMIUM_EXECUTABLE=/path/to/chrome`
指定它，省掉 `playwright install`。

## 通知規則

預設只在「**比過去所有紀錄都便宜**」時寄信，所以不會每 6 小時收到一封。
判定基準是**全團估算總價**（見下節），而不是單人票價。

`config.yaml` 的 `notify` 區段可以調整：

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
- **單次失敗不通知**（trip.com 偶爾會擋），連續 3 次都抓不到才寄警告信。

## 價格怎麼算的（重要）

trip.com 有時顯示「每位成人」票價、有時顯示總價，而且同一頁不同版本可能不一樣。
直接比較這兩種數字會產生假的「新低」，所以程式一律換算成**全團估算總價**後再比較與儲存：

- trip.com 有給總價 → 直接用它的總價
- 只有每人票價 → 以 `每人票價 × 7`（5 成人 + 2 兒童佔位）估算

信裡會同時顯示「全團估算」和「trip.com 實際顯示的數字」，並標注是哪一種。

⚠️ **估算值只用於比價排序，不是報價。** 兒童票通常比成人便宜，行李、稅金、手續費
也依航空公司而異，**實際金額請到 trip.com 結帳頁確認**。信裡每個組合都有直達
trip.com 搜尋頁的連結。

## 抓不到價格怎麼辦

trip.com 會改版，也有反爬蟲機制。程式用三層 fallback 抓價格，任一層成功就採用：

| 層 | 方式 | 取得的資訊 |
| --- | --- | --- |
| `xhr` | 攔截頁面載入時的 JSON API 回應 | 最完整：航空公司、航班號、轉機、時刻 |
| `dom` | 讀渲染完成的結果卡片 | 價格、航空公司、轉機次數 |
| `text` | 正則掃整頁的金額，取最低的合理值 | 只有價格 |

信件和 log 都會標注這次是哪一層抓到的（`source=xhr` / `dom` / `text`）。
如果降到 `text`，代表前兩層的結構對不上了，值得看一下。

**完全抓不到時的排查步驟：**

1. 手動跑一次 workflow，勾 `debug_dump`，下載 `debug-snapshot-*` artifact
2. 看 `screenshot.png`：
   - 出現人機驗證 → 被風控了。把 `config.yaml` 的
     `scrape.delay_between_queries_s` 調大（例如 `[30, 90]`）、`attempts` 調大，
     並把排程頻率降低
   - 正常顯示結果 → 是解析對不上
3. 解析對不上時：
   - 看 `xhr-*.json` 裡價格放在哪個欄位；`src/tripcom_watcher/parsing.py`
     上方的 `_PRICE_KEY` / `_SEGMENT_KEYS` 等「key 提示」就是比對依據，補上新欄位名即可
   - 或看 `page.html` 找出結果卡片的 CSS selector，填進 `config.yaml` 的
     `scrape.card_selectors`，跳過自動啟發式

`scrape.price_sanity_min` / `price_sanity_max` 界定「合理票價」範圍（預設 3,000–600,000 TWD），
用來濾掉頁面上的行李費、稅金等雜訊數字。如果真實票價落在範圍外，記得調整。

## 價格歷史

每次執行的結果會寫進 [`data/price_history.json`](data/price_history.json)，由 Actions 自動 commit 回 repo，
所以「歷史最低價」跨執行、跨容器都留得住。檔案裡有：

- `best` — 每組日期組合與整體的歷史最低（含當時的航班明細）
- `runs` — 最近每次執行的結果（預設保留 500 筆，由 `storage.keep_runs` 控制）

`python -m tripcom_watcher report` 可以直接把這些印出來。

## 專案結構

```
config.yaml                      搜尋條件、爬取行為、通知規則（改這裡就好）
src/tripcom_watcher/
  cli.py                         指令入口：run / queries / report / test-email
  config.py                      讀取與驗證 config.yaml
  queries.py                     產生日期組合與 trip.com 搜尋網址
  scraper.py                     Playwright 爬取，含重試與 debug 快照
  browser_js.py                  注入頁面的 JS（反偵測、等待價格、擷取卡片）
  parsing.py                     三層票價解析（xhr / dom / text）
  pricing.py                     把不同基準的價格換算成可比較的全團總價
  storage.py                     價格歷史讀寫與歷史最低追蹤
  alerts.py                      判斷這次要不要通知
  report.py                      產生信件主旨、HTML 與純文字內容
  notify.py                      SMTP 寄信
tests/                           91 個測試，含 trip.com 回應的 fixture
.github/workflows/
  watch-fares.yml                每 6 小時執行的排程
  tests.yml                      push / PR 時跑測試
```

## 已知限制

- **解析層尚未對 trip.com 線上頁面驗證過。** 開發環境的連外政策擋掉了
  `www.trip.com`，所以解析邏輯是對著模擬的回應結構和本機假頁面測的（三層都有跑過
  真實 Chromium）。第一次在 Actions 上跑時請務必勾 `debug_dump`，照上面的步驟核對。
- **松山（TSA）大概查不到結果。** 松山的國際線只有東京羽田、首爾金浦、上海虹橋，
  到富國島要轉兩段以上，trip.com 很可能回空。這是預期行為，不是錯誤；
  設定裡留著它是因為你指定了這個機場。不想看到它的失敗訊息，
  把 `config.yaml` 的 `origins` 改成 `[TPE]` 就好。
- **爬蟲不是官方 API。** trip.com 改版或加強風控都可能讓它失效，
  所以有連續失敗警告信和 debug 快照機制。
- **2027 年 2 月 6 日是農曆初一，你要的 2/9–2/14 正好是年假尾段與收假潮。**
  這段期間票價本來就高、波動也大，建議第一封「開始監控」的信到手後，
  看一下基準價再把 `notify.absolute_threshold` 設成你願意出手的金額，
  這樣真的跌到可接受範圍時會額外收到一封，不用一直盯著新低。
