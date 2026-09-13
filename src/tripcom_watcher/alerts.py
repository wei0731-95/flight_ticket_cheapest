"""Decide whether a run is worth an email.

Evaluated against the history *before* the run is appended, so "new low" means
cheaper than anything seen in an earlier run.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .config import Config
from .models import Offer, QueryResult, RunSummary
from .pricing import canonical_total
from .storage import History

# Highest priority first; decides the subject line when several apply.
KIND_LABELS = {
    "new_low": "歷史新低",
    "threshold": "低於設定門檻",
    "baseline": "開始監控",
    "summary": "定期摘要",
    "failure": "爬取失敗警告",
    "none": "不通知",
}


@dataclass
class PriceChange:
    """How one search's cheapest fare moved since the last time we saw it."""

    query_key: str
    offer: Offer
    total: float
    previous_total: float | None

    @property
    def is_new_low(self) -> bool:
        return self.previous_total is None or self.total < self.previous_total

    @property
    def delta(self) -> float | None:
        if self.previous_total is None:
            return None
        return self.total - self.previous_total


@dataclass
class Decision:
    send: bool = False
    kind: str = "none"
    reasons: list[str] = field(default_factory=list)
    cheapest: Offer | None = None
    cheapest_total: float | None = None
    previous_total: float | None = None
    changes: list[PriceChange] = field(default_factory=list)
    failures: list[QueryResult] = field(default_factory=list)
    threshold_hit: bool = False

    @property
    def label(self) -> str:
        return KIND_LABELS.get(self.kind, self.kind)

    @property
    def drop(self) -> float | None:
        if self.cheapest_total is None or self.previous_total is None:
            return None
        return self.previous_total - self.cheapest_total


def evaluate(history: History, summary: RunSummary, config: Config) -> Decision:
    pax = config.search.passengers
    notify = config.notify

    changes: list[PriceChange] = []
    for result in summary.results:
        offer = result.cheapest
        if offer is None:
            continue
        previous = history.best(result.query.key)
        changes.append(
            PriceChange(
                query_key=result.query.key,
                offer=offer,
                total=canonical_total(offer, pax),
                previous_total=None if previous is None else previous.total,
            )
        )
    changes.sort(key=lambda c: c.total)

    decision = Decision(changes=changes, failures=summary.failures)

    cheapest = summary.cheapest
    if cheapest is None:
        # Nothing at all came back. Only shout once the failures look persistent.
        run_failures = history.consecutive_failed_runs + 1
        if summary.results and run_failures >= notify.failure_alert_threshold:
            decision.send = True
            decision.kind = "failure"
            decision.reasons.append(
                f"連續 {run_failures} 次執行都沒抓到任何票價，請檢查 trip.com 頁面結構或是否被風控阻擋"
            )
        return decision

    total = canonical_total(cheapest, pax)
    previous_best = history.overall_best()
    previous_total = None if previous_best is None else previous_best.total

    decision.cheapest = cheapest
    decision.cheapest_total = total
    decision.previous_total = previous_total

    if previous_total is None:
        if notify.on_new_low:
            decision.send = True
            decision.kind = "baseline"
            decision.reasons.append(
                f"第一次取得報價，目前最便宜為 {cheapest.currency} {total:,.0f}（全團估算）"
            )
    elif total <= previous_total - notify.min_drop:
        if notify.on_new_low:
            decision.send = True
            decision.kind = "new_low"
            decision.reasons.append(
                f"比先前最低 {cheapest.currency} {previous_total:,.0f} 再便宜 "
                f"{cheapest.currency} {previous_total - total:,.0f}"
            )

    if notify.absolute_threshold is not None and total <= notify.absolute_threshold:
        already = history.threshold_notified_total
        # Re-alert only when we dip below the cheapest price we already announced.
        if already is None or total < already:
            decision.threshold_hit = True
            decision.send = True
            if decision.kind in {"none", "summary"}:
                decision.kind = "threshold"
            decision.reasons.append(
                f"已低於設定門檻 {cheapest.currency} {notify.absolute_threshold:,.0f}"
            )

    if notify.always_summary and not decision.send:
        decision.send = True
        decision.kind = "summary"
        decision.reasons.append("已開啟每次執行都寄摘要")

    if decision.failures and decision.send:
        decision.reasons.append(f"本次有 {len(decision.failures)} 組查詢失敗，明細見信末")

    return decision
