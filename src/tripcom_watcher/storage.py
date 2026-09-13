"""Persist fare history between runs so "cheapest ever" survives restarts."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import Config
from .models import Offer, QueryResult, RunSummary
from .pricing import canonical_total

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1
OVERALL_KEY = "__overall__"


@dataclass
class BestRecord:
    """The cheapest fare ever seen for one key."""

    total: float
    currency: str
    seen_at: str
    offer: Offer

    def to_dict(self) -> dict[str, Any]:
        return {
            "total": self.total,
            "currency": self.currency,
            "seen_at": self.seen_at,
            "offer": self.offer.to_dict(),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "BestRecord | None":
        try:
            return cls(
                total=float(raw["total"]),
                currency=str(raw.get("currency", "TWD")),
                seen_at=str(raw.get("seen_at", "")),
                offer=Offer.from_dict(raw["offer"]),
            )
        except (KeyError, TypeError, ValueError):
            return None


def _empty() -> dict[str, Any]:
    return {
        "version": SCHEMA_VERSION,
        "updated_at": None,
        "consecutive_failed_runs": 0,
        "threshold_notified_total": None,
        "best": {},
        "runs": [],
    }


class History:
    """Thin wrapper over the JSON history file."""

    def __init__(self, data: dict[str, Any] | None = None) -> None:
        self.data = data if isinstance(data, dict) else _empty()
        self.data.setdefault("version", SCHEMA_VERSION)
        self.data.setdefault("consecutive_failed_runs", 0)
        self.data.setdefault("threshold_notified_total", None)
        self.data.setdefault("best", {})
        self.data.setdefault("runs", [])

    # -- io ----------------------------------------------------------------

    @classmethod
    def load(cls, path: Path) -> "History":
        if not path.exists():
            return cls()
        try:
            return cls(json.loads(path.read_text(encoding="utf-8")))
        except (ValueError, OSError) as exc:
            # A corrupt history must not stop the watcher; start a fresh one and
            # keep the damaged file around for inspection.
            log.warning("歷史檔 %s 讀取失敗（%s），改用空白歷史", path, exc)
            try:
                path.rename(path.with_suffix(path.suffix + ".corrupt"))
            except OSError:
                pass
            return cls()

    def save(self, path: Path, keep_runs: int = 500) -> None:
        runs = self.data.get("runs") or []
        if keep_runs > 0 and len(runs) > keep_runs:
            self.data["runs"] = runs[-keep_runs:]
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
            encoding="utf-8",
        )
        temp.replace(path)

    # -- reads -------------------------------------------------------------

    def best(self, key: str) -> BestRecord | None:
        raw = (self.data.get("best") or {}).get(key)
        return BestRecord.from_dict(raw) if isinstance(raw, dict) else None

    def overall_best(self) -> BestRecord | None:
        return self.best(OVERALL_KEY)

    @property
    def consecutive_failed_runs(self) -> int:
        return int(self.data.get("consecutive_failed_runs") or 0)

    @property
    def threshold_notified_total(self) -> float | None:
        value = self.data.get("threshold_notified_total")
        return None if value is None else float(value)

    @property
    def run_count(self) -> int:
        return len(self.data.get("runs") or [])

    def totals_series(self, limit: int = 30) -> list[tuple[str, float | None]]:
        """(timestamp, cheapest party total) for the most recent runs."""
        series: list[tuple[str, float | None]] = []
        for run in (self.data.get("runs") or [])[-limit:]:
            cheapest = run.get("cheapest") or {}
            total = cheapest.get("total")
            series.append((str(run.get("ts", "")), None if total is None else float(total)))
        return series

    # -- writes ------------------------------------------------------------

    def append_run(self, summary: RunSummary, config: Config) -> None:
        """Record this run's outcome and refresh the best-ever records."""
        pax = config.search.passengers
        cheapest = summary.cheapest
        entry: dict[str, Any] = {
            "ts": summary.finished_at.isoformat(timespec="seconds"),
            "duration_s": round((summary.finished_at - summary.started_at).total_seconds(), 1),
            "cheapest": None,
            "queries": {},
        }
        if cheapest is not None:
            entry["cheapest"] = {
                "total": canonical_total(cheapest, pax),
                "price": cheapest.price,
                "price_basis": cheapest.price_basis,
                "currency": cheapest.currency,
                "query_key": cheapest.query_key,
                "source": cheapest.source,
            }

        for result in summary.results:
            entry["queries"][result.query.key] = _query_entry(result, config)

        self.data["runs"] = (self.data.get("runs") or []) + [entry]
        self.data["updated_at"] = entry["ts"]

        if summary.results and not any(r.ok for r in summary.results):
            self.data["consecutive_failed_runs"] = self.consecutive_failed_runs + 1
        else:
            self.data["consecutive_failed_runs"] = 0

        for result in summary.results:
            best_offer = result.cheapest
            if best_offer is not None:
                self.record_best(result.query.key, best_offer, config)
        if cheapest is not None:
            self.record_best(OVERALL_KEY, cheapest, config)

    def record_best(self, key: str, offer: Offer, config: Config) -> bool:
        """Store ``offer`` as the best for ``key`` if it beats what we had."""
        total = canonical_total(offer, config.search.passengers)
        current = self.best(key)
        if current is not None and total >= current.total:
            return False
        self.data.setdefault("best", {})[key] = BestRecord(
            total=total,
            currency=offer.currency,
            seen_at=offer.scraped_at or self.data.get("updated_at") or "",
            offer=offer,
        ).to_dict()
        return True

    def mark_threshold_notified(self, total: float | None) -> None:
        self.data["threshold_notified_total"] = total


def _query_entry(result: QueryResult, config: Config) -> dict[str, Any]:
    best = result.cheapest
    return {
        "offers": len(result.offers),
        "error": result.error,
        "attempts": result.attempts,
        "total": None if best is None else canonical_total(best, config.search.passengers),
        "price": None if best is None else best.price,
        "price_basis": None if best is None else best.price_basis,
        "source": None if best is None else best.source,
    }
