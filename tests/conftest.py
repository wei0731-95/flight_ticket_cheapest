from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from tripcom_watcher.config import Config, build_config
from tripcom_watcher.models import Leg, Offer, QueryResult, RunSummary, SearchQuery

FIXTURES = Path(__file__).parent / "fixtures"


def raw_config(**overrides) -> dict:
    base = {
        "search": {
            "origins": ["TPE", "TSA"],
            "destination": "PQC",
            "window_start": "2027-02-09",
            "window_end": "2027-02-14",
            "min_nights": 4,
            "max_nights": 5,
            "passengers": {"adults": 5, "children": 2, "infants": 0, "child_ages": [8, 10]},
            "cabin": "economy",
            "currency": "TWD",
            "locale": "zh-tw",
            "max_stops": None,
        },
        "scrape": {"price_sanity_min": 3000, "price_sanity_max": 600000},
        "notify": {"on_new_low": True, "min_drop": 1, "always_summary": False,
                   "failure_alert_threshold": 3},
        "storage": {"history_path": "data/price_history.json", "keep_runs": 50},
    }
    for section, values in overrides.items():
        base.setdefault(section, {}).update(values)
    return base


@pytest.fixture
def config(tmp_path: Path) -> Config:
    return build_config(raw_config(), root=tmp_path)


@pytest.fixture
def query() -> SearchQuery:
    return SearchQuery("TPE", "PQC", date(2027, 2, 9), date(2027, 2, 13))


@pytest.fixture
def tripcom_payload() -> dict:
    return json.loads((FIXTURES / "flight_search_response.json").read_text(encoding="utf-8"))


def make_offer(
    *,
    price: float,
    query_key: str = "TPE-PQC_2027-02-09_2027-02-13",
    origin: str = "TPE",
    depart: str = "2027-02-09",
    ret: str = "2027-02-13",
    basis: str = "per_adult",
    total: float | None = None,
    stops: int | None = 0,
    carrier: str = "VJ",
) -> Offer:
    return Offer(
        query_key=query_key,
        origin=origin,
        destination="PQC",
        depart_date=depart,
        return_date=ret,
        price=price,
        currency="TWD",
        price_basis=basis,
        total_price=total,
        carriers=[carrier],
        outbound=Leg(origin, "PQC", f"{depart} 09:00", f"{depart} 12:10", [carrier], [f"{carrier}931"], stops),
        inbound=Leg("PQC", origin, f"{ret} 13:00", f"{ret} 18:05", [carrier], [f"{carrier}932"], stops),
        max_stops=stops,
        deep_link="https://www.trip.com/flights/showfarefirst?dcity=tpe&acity=pqc",
        source="xhr",
        scraped_at="2026-09-13T04:00:00+00:00",
    )


def make_summary(*offers_by_query: tuple[SearchQuery, list[Offer]], errors=()) -> RunSummary:
    results = [QueryResult(query=q, offers=list(o), attempts=1) for q, o in offers_by_query]
    results += [QueryResult(query=q, offers=[], error=e, attempts=3) for q, e in errors]
    now = datetime(2026, 9, 13, 4, 0, tzinfo=timezone.utc)
    return RunSummary(started_at=now, finished_at=now, results=results)
