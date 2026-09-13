"""Drive a headless Chromium through trip.com's round-trip search."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Response, TimeoutError as PlaywrightTimeout
from playwright.async_api import async_playwright

from .browser_js import BLOCK_MARKERS, COLLECT_CARDS, HAS_PRICES, STEALTH_INIT
from .config import Config
from .models import Offer, QueryResult, SearchQuery
from .parsing import PriceSanity, extract_offers
from .queries import build_url

log = logging.getLogger(__name__)

# Requests whose JSON bodies are worth keeping for the parser.
_XHR_URL_HINTS = ("soa2", "flight", "search", "productlist", "fltproduct", "batch", "lowprice")
_MAX_PAYLOAD_BYTES = 6_000_000
_MAX_PAYLOADS = 40
_MAX_SEEN_URLS = 120
_MAX_CARDS = 80

_USER_AGENTS = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
)

_LAUNCH_ARGS = (
    "--disable-blink-features=AutomationControlled",
    "--disable-dev-shm-usage",
    "--no-sandbox",
    "--disable-gpu",
    "--disable-features=IsolateOrigins,site-per-process",
)


class BlockedError(RuntimeError):
    """trip.com served a bot wall instead of search results."""


class NoResultsError(RuntimeError):
    """The page loaded but never produced a plausible fare."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _is_blocked(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in BLOCK_MARKERS)


class TripScraper:
    """Scrapes one trip.com search per :meth:`scrape` call.

    Each query gets a fresh browser context (new fingerprint, clean cookies) so a
    context that trips the bot wall does not poison the rest of the run.
    """

    def __init__(self, config: Config, debug_dir: Path | None = None) -> None:
        self.config = config
        self.debug_dir = debug_dir
        self.sanity = PriceSanity(
            config.scrape.price_sanity_min, config.scrape.price_sanity_max
        )
        self._playwright = None
        self._browser = None

    async def __aenter__(self) -> "TripScraper":
        self._playwright = await async_playwright().start()
        launch: dict[str, Any] = {
            "headless": self.config.scrape.headless,
            "args": list(_LAUNCH_ARGS),
        }
        # Lets an environment that ships its own Chromium (or a sandbox whose
        # bundled build does not match this Playwright release) skip the
        # download: PLAYWRIGHT_CHROMIUM_EXECUTABLE=/path/to/chrome
        executable = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE", "").strip()
        if executable:
            launch["executable_path"] = executable
        self._browser = await self._playwright.chromium.launch(**launch)
        return self

    async def __aexit__(self, *exc_info: Any) -> None:
        if self._browser is not None:
            await self._browser.close()
        if self._playwright is not None:
            await self._playwright.stop()

    # -- per-query ---------------------------------------------------------

    async def scrape(self, query: SearchQuery, deadline: float | None = None) -> QueryResult:
        scrape_cfg = self.config.scrape
        result = QueryResult(query=query, scraped_at=_now())
        last_error: Exception | None = None

        for attempt in range(1, scrape_cfg.attempts + 1):
            if attempt > 1 and deadline is not None and time.monotonic() >= deadline:
                log.warning("%s 已用完本次執行的時間預算，不再重試", query.key)
                break
            result.attempts = attempt
            # Later attempts fall back to trip.com's alternate search route.
            url = build_url(query, self.config.search, fallback=attempt > 2)
            result.url = url
            try:
                offers = await self._attempt(query, url, attempt)
            except (BlockedError, NoResultsError, PlaywrightTimeout, PlaywrightError) as exc:
                last_error = exc
                log.warning(
                    "%s 第 %d/%d 次嘗試失敗：%s",
                    query.key, attempt, scrape_cfg.attempts, _short(exc),
                )
                if attempt < scrape_cfg.attempts:
                    await asyncio.sleep(_backoff(scrape_cfg.retry_backoff_s, attempt))
                continue

            result.offers = offers
            result.error = None
            result.scraped_at = _now()
            log.info("%s 取得 %d 筆報價，最低 %s", query.key, len(offers), _cheapest_label(offers))
            return result

        result.error = f"{type(last_error).__name__}: {_short(last_error)}"
        return result

    async def _attempt(self, query: SearchQuery, url: str, attempt: int) -> list[Offer]:
        assert self._browser is not None, "TripScraper 必須在 async with 區塊中使用"
        scrape_cfg = self.config.scrape

        context = await self._browser.new_context(
            user_agent=random.choice(_USER_AGENTS),
            locale="zh-TW",
            timezone_id="Asia/Taipei",
            viewport={
                "width": random.randint(1440, 1680),
                "height": random.randint(860, 1000),
            },
            device_scale_factor=random.choice([1, 2]),
            extra_http_headers={
                "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
                "Upgrade-Insecure-Requests": "1",
            },
        )
        collector = PayloadCollector()
        try:
            await context.add_init_script(f"({STEALTH_INIT.strip()})();")
            page = await context.new_page()
            page.set_default_timeout(scrape_cfg.timeout_ms)
            page.on("response", collector.handle)

            await page.goto(url, wait_until="domcontentloaded", timeout=scrape_cfg.timeout_ms)
            await _settle(page, scrape_cfg.results_timeout_ms)
            await collector.drain()
            payloads = collector.payloads

            page_text = await page.evaluate("() => document.body ? document.body.innerText : ''")
            if _is_blocked(page_text):
                raise BlockedError("頁面出現人機驗證")

            cards = await page.evaluate(
                COLLECT_CARDS, {"selectors": list(scrape_cfg.card_selectors), "limit": _MAX_CARDS}
            )

            if self.debug_dir is not None:
                await self._describe(page, query, collector, cards, page_text)
                await self._dump(page, query, attempt, payloads, cards, page_text)

            offers = extract_offers(
                query=query,
                sanity=self.sanity,
                payloads=payloads,
                cards=cards,
                page_text=page_text,
                currency=self.config.search.currency,
                deep_link=url,
                scraped_at=_now(),
            )
            if not offers:
                raise NoResultsError(
                    f"頁面載入完成但找不到合理票價（XHR {len(payloads)} 筆 / 卡片 {len(cards)} 張）"
                )
            return _filter_stops(offers, self.config.search.max_stops)
        finally:
            await context.close()

    async def _describe(
        self,
        page: Any,
        query: SearchQuery,
        collector: "PayloadCollector",
        cards: list[dict],
        page_text: str,
    ) -> None:
        """Log what the page actually was.

        Debug artifacts are not reachable from every environment, so the digest
        that matters for fixing the parser goes into the job log too: where we
        ended up after redirects, what the page says, and which endpoints it
        called -- the last one being how the XHR hints get corrected.
        """
        try:
            title = await page.title()
        except Exception:
            title = "?"
        flat = " | ".join(line.strip() for line in page_text.splitlines() if line.strip())
        log.info("[診斷] %s 最終網址：%s", query.key, page.url)
        log.info("[診斷] %s 標題：%r　內文 %d 字　卡片 %d 張　JSON %d 筆",
                 query.key, title, len(page_text), len(cards), len(collector.payloads))
        log.info("[診斷] %s 內文前 800 字：%s", query.key, flat[:800])
        log.info("[診斷] %s 頁面共發出 %d 筆 XHR/fetch：", query.key, len(collector.seen))
        for url in collector.seen[:50]:
            log.info("[診斷]   %s", url)

    async def _dump(
        self,
        page: Any,
        query: SearchQuery,
        attempt: int,
        payloads: list[Any],
        cards: list[dict],
        page_text: str,
    ) -> None:
        folder = self.debug_dir / f"{query.key}_try{attempt}"
        folder.mkdir(parents=True, exist_ok=True)
        try:
            (folder / "page.txt").write_text(page_text, encoding="utf-8")
            (folder / "page.html").write_text(await page.content(), encoding="utf-8")
            (folder / "cards.json").write_text(
                json.dumps(cards, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            for index, payload in enumerate(payloads):
                (folder / f"xhr-{index:02d}.json").write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2)[:2_000_000],
                    encoding="utf-8",
                )
            await page.screenshot(path=str(folder / "screenshot.png"), full_page=False)
        except Exception as exc:  # debug output must never fail the run
            log.warning("寫入 debug 快照失敗：%s", _short(exc))

    # -- whole run ---------------------------------------------------------

    async def scrape_all(self, queries: list[SearchQuery]) -> list[QueryResult]:
        low, high = self.config.scrape.delay_between_queries_s
        deadline = time.monotonic() + self.config.scrape.run_budget_s
        results: list[QueryResult] = []
        for index, query in enumerate(queries):
            if time.monotonic() >= deadline:
                log.warning("時間預算用盡，跳過 %s", query.key)
                results.append(
                    QueryResult(
                        query=query,
                        error="SkippedError: 超出本次執行的時間預算，尚未查詢",
                        scraped_at=_now(),
                    )
                )
                continue
            if index:
                await asyncio.sleep(random.uniform(low, high))
            log.info("(%d/%d) 查詢 %s", index + 1, len(queries), query.describe())
            results.append(await self.scrape(query, deadline=deadline))
        return results


# -- helpers ---------------------------------------------------------------


class PayloadCollector:
    """Collects JSON bodies from flight-search XHRs while the page renders.

    Reading a response body is itself async, so each read is tracked as a task
    and :meth:`drain` is awaited before parsing -- otherwise the browser context
    could close while bodies are still in flight and the JSON layer would see
    nothing.
    """

    def __init__(self) -> None:
        self.payloads: list[Any] = []
        # Every XHR/fetch the page made, matched or not. When nothing parses,
        # this is the only way to find out what trip.com actually calls.
        self.seen: list[str] = []
        self._tasks: set[asyncio.Task] = set()

    def handle(self, response: Response) -> None:
        content_type = (response.headers or {}).get("content-type", "").lower()
        try:
            resource_type = response.request.resource_type
        except Exception:
            resource_type = ""
        if len(self.seen) < _MAX_SEEN_URLS and (
            resource_type in {"xhr", "fetch"} or "json" in content_type
        ):
            self.seen.append(f"[{resource_type or '?'}] {response.url[:240]}")

        if len(self.payloads) + len(self._tasks) >= _MAX_PAYLOADS:
            return
        url = response.url.lower()
        if not any(hint in url for hint in _XHR_URL_HINTS):
            return
        if "json" not in content_type:
            return
        task = asyncio.ensure_future(self._read(response))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _read(self, response: Response) -> None:
        try:
            body = await response.body()
        except Exception:
            # The response can be gone already (navigation, redirect, abort).
            return
        if not body or len(body) > _MAX_PAYLOAD_BYTES:
            return
        try:
            self.payloads.append(json.loads(body))
        except (ValueError, UnicodeDecodeError):
            return

    async def drain(self, timeout: float = 20.0) -> None:
        """Wait for in-flight body reads so nothing captured is lost."""
        while self._tasks:
            pending = set(self._tasks)
            done, still_pending = await asyncio.wait(pending, timeout=timeout)
            if still_pending:
                for task in still_pending:
                    task.cancel()
                return


async def _settle(page: Any, results_timeout_ms: int) -> None:
    """Wait for fares to render, then give streaming results a moment to arrive."""
    try:
        await page.wait_for_function(HAS_PRICES, arg=3, timeout=results_timeout_ms)
    except PlaywrightTimeout:
        # Not fatal: the JSON layer may still hold fares even if the DOM lags.
        log.debug("等待價格渲染逾時，改用已擷取的資料")
    await page.mouse.wheel(0, random.randint(600, 1200))
    await asyncio.sleep(random.uniform(3.0, 6.0))
    try:
        await page.wait_for_load_state("networkidle", timeout=15_000)
    except PlaywrightTimeout:
        pass


def _filter_stops(offers: list[Offer], max_stops: int | None) -> list[Offer]:
    if max_stops is None:
        return offers
    # Keep offers whose stop count is unknown; dropping them would hide fares.
    kept = [o for o in offers if o.max_stops is None or o.max_stops <= max_stops]
    return kept or offers


def _backoff(schedule: tuple[float, ...], attempt: int) -> float:
    if not schedule:
        return 10.0
    delay = schedule[min(attempt, len(schedule)) - 1]
    return delay + random.uniform(0, delay * 0.25)


def _short(exc: Exception | None, limit: int = 200) -> str:
    text = str(exc or "").strip().splitlines()
    return (text[0] if text else type(exc).__name__)[:limit]


def _cheapest_label(offers: list[Offer]) -> str:
    if not offers:
        return "—"
    best = min(offers, key=lambda o: o.price)
    return f"{best.currency} {best.price:,.0f} ({best.price_basis}, {best.source})"
