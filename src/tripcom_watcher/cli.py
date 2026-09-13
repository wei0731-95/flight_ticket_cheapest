"""Command line entry point."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import alerts, report
from .config import Config, ConfigError, MailConfig, load_config
from .models import RunSummary
from .notify import NotifyError, send_email
from .queries import build_queries, build_url
from .storage import History

log = logging.getLogger("tripcom_watcher")


def _load_dotenv(path: Path) -> None:
    """Minimal .env support so local runs do not need a shell wrapper."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("asyncio").setLevel(logging.WARNING)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tripcom-watcher",
        description="監控 trip.com 台北→富國島來回機票，出現新低價時寄信通知。",
    )
    parser.add_argument("-c", "--config", default="config.yaml", help="設定檔路徑（預設 config.yaml）")
    parser.add_argument("-v", "--verbose", action="store_true", help="輸出除錯訊息")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="執行一次查詢、更新歷史並在符合條件時寄信")
    run.add_argument("--dry-run", action="store_true", help="只查詢並印出結果，不寄信也不寫入歷史")
    run.add_argument("--no-email", action="store_true", help="查詢並寫入歷史，但不寄信")
    run.add_argument("--force-email", action="store_true", help="不論有無新低都寄一封信")
    run.add_argument("--debug-dump", action="store_true", help="把頁面 HTML / XHR JSON / 截圖存到 debug/")
    run.add_argument("--only", metavar="SUBSTR", help="只跑 key 含有這段字串的查詢")
    run.add_argument("--fail-on-empty", action="store_true", help="完全沒抓到票價時以非零結束碼退出")

    sub.add_parser("queries", help="列出會被查詢的日期與機場組合")
    sub.add_parser("report", help="印出目前的歷史最低價摘要")
    sub.add_parser("test-email", help="寄一封測試信，確認 SMTP 設定正確")
    return parser


# -- commands ---------------------------------------------------------------


def cmd_queries(config: Config) -> int:
    queries = build_queries(config.search)
    print(f"共 {len(queries)} 組查詢（{config.search.passengers.describe()}，{config.search.cabin}）\n")
    for index, query in enumerate(queries, 1):
        print(f"{index:>2}. {query.describe()}")
        print(f"    {build_url(query, config.search)}")
    return 0


def cmd_report(config: Config) -> int:
    history = History.load(config.history_path)
    if history.run_count == 0:
        print(f"還沒有任何紀錄（{config.history_path}）")
        return 0

    overall = history.overall_best()
    print(f"歷史檔：{config.history_path}")
    print(f"已執行 {history.run_count} 次，最後更新 {history.data.get('updated_at')}")
    if overall is not None:
        print(
            f"\n歷史最低（全團估算）：{report.money(overall.total, overall.currency)}"
            f"  {report.trip_label(overall.offer)}  {overall.offer.origin}"
            f"  （{overall.offer.describe_price()}，{overall.seen_at}）"
        )

    print("\n各組合歷史最低：")
    for query in build_queries(config.search):
        best = history.best(query.key)
        value = report.money(None if best is None else best.total, config.search.currency)
        print(f"  {query.key:<34} {value:>16}")

    series = history.totals_series(limit=15)
    if series:
        print("\n最近幾次的最低價：")
        for timestamp, total in series:
            print(f"  {timestamp}  {report.money(total, config.search.currency):>16}")
    return 0


def cmd_test_email(config: Config) -> int:
    mail = MailConfig.from_env()
    if not mail.configured:
        print(f"寄信設定不完整，缺少：{', '.join(mail.missing())}", file=sys.stderr)
        return 2
    decision = alerts.Decision(
        send=True,
        kind="summary",
        reasons=["這是一封測試信，代表 SMTP 設定正確，監控可以開始運作。"],
    )
    try:
        send_email(
            mail,
            "[機票監控] 測試信 · 設定正確",
            report.text_body(decision, config),
            report.html_body(decision, config),
        )
    except NotifyError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"測試信已寄給 {', '.join(mail.recipients)}")
    return 0


def cmd_run(config: Config, args: argparse.Namespace) -> int:
    # Imported here so `queries` / `report` work without Playwright installed.
    from .scraper import TripScraper

    queries = build_queries(config.search)
    if args.only:
        queries = [q for q in queries if args.only.lower() in q.key.lower()]
    if not queries:
        print("沒有符合條件的查詢組合", file=sys.stderr)
        return 2

    debug_dir: Path | None = None
    if args.debug_dump or config.scrape.debug_dump:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        debug_dir = config.root / "debug" / stamp
        debug_dir.mkdir(parents=True, exist_ok=True)
        log.info("debug 快照將寫入 %s", debug_dir)

    history = History.load(config.history_path)
    started = datetime.now(timezone.utc)

    async def scrape() -> list:
        async with TripScraper(config, debug_dir=debug_dir) as scraper:
            return await scraper.scrape_all(queries)

    results = asyncio.run(scrape())
    summary = RunSummary(
        started_at=started, finished_at=datetime.now(timezone.utc), results=results
    )

    decision = alerts.evaluate(history, summary, config)
    if args.force_email and decision.cheapest is not None and not decision.send:
        decision.send = True
        decision.kind = "summary"
        decision.reasons.append("以 --force-email 強制寄出")

    print()
    print(report.console_summary(decision, config, run_count=history.run_count + 1))
    print()

    emailed = False
    if decision.send and not args.dry_run and not args.no_email:
        mail = MailConfig.from_env()
        if not mail.configured:
            log.error("符合通知條件但寄信設定不完整，缺少：%s", ", ".join(mail.missing()))
        else:
            try:
                send_email(
                    mail,
                    report.subject(decision, config),
                    report.text_body(decision, config, run_count=history.run_count + 1),
                    report.html_body(decision, config, run_count=history.run_count + 1),
                )
                emailed = True
            except NotifyError as exc:
                log.error("%s", exc)
    elif decision.send:
        log.info("符合通知條件，但本次不寄信（--dry-run / --no-email）")
    else:
        log.info("未達通知條件（%s），不寄信", decision.label)

    if not args.dry_run:
        if emailed and decision.threshold_hit:
            history.mark_threshold_notified(decision.cheapest_total)
        history.append_run(summary, config)
        history.save(config.history_path, keep_runs=config.storage.keep_runs)
        log.info("歷史已更新：%s", config.history_path)

    failed = len(summary.failures)
    if failed:
        log.warning("%d/%d 組查詢沒有取得報價", failed, len(results))
    if args.fail_on_empty and summary.cheapest is None:
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    _setup_logging(args.verbose)

    config_path = Path(args.config)
    _load_dotenv(config_path.resolve().parent / ".env")

    try:
        config = load_config(config_path)
    except ConfigError as exc:
        print(f"設定錯誤：{exc}", file=sys.stderr)
        return 2

    if args.command == "queries":
        return cmd_queries(config)
    if args.command == "report":
        return cmd_report(config)
    if args.command == "test-email":
        return cmd_test_email(config)
    return cmd_run(config, args)
