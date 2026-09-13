"""Dataclasses shared across the watcher."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any


AIRPORT_NAMES = {
    "TPE": "桃園",
    "TSA": "松山",
    "PQC": "富國島",
}


def airport_label(code: str) -> str:
    name = AIRPORT_NAMES.get(code.upper())
    return f"{name}({code.upper()})" if name else code.upper()


@dataclass(frozen=True)
class Passengers:
    adults: int = 1
    children: int = 0
    infants: int = 0
    child_ages: tuple[int, ...] = ()

    @property
    def seated(self) -> int:
        """Passengers that occupy a seat (infants normally sit on a lap)."""
        return self.adults + self.children

    @property
    def total(self) -> int:
        return self.adults + self.children + self.infants

    def describe(self) -> str:
        parts = [f"{self.adults} 成人"]
        if self.children:
            ages = f"（{', '.join(str(a) for a in self.child_ages)} 歲）" if self.child_ages else ""
            parts.append(f"{self.children} 兒童{ages}")
        if self.infants:
            parts.append(f"{self.infants} 嬰兒")
        return " + ".join(parts)


@dataclass(frozen=True)
class SearchQuery:
    """One concrete round-trip search on trip.com."""

    origin: str
    destination: str
    depart_date: date
    return_date: date

    @property
    def nights(self) -> int:
        return (self.return_date - self.depart_date).days

    @property
    def days(self) -> int:
        return self.nights + 1

    @property
    def key(self) -> str:
        return (
            f"{self.origin}-{self.destination}"
            f"_{self.depart_date.isoformat()}_{self.return_date.isoformat()}"
        )

    def describe(self) -> str:
        return (
            f"{airport_label(self.origin)} → {airport_label(self.destination)} "
            f"{self.depart_date.isoformat()} 去 / {self.return_date.isoformat()} 回 "
            f"（{self.days} 天 {self.nights} 夜）"
        )


@dataclass
class Leg:
    """One direction of the itinerary."""

    origin: str | None = None
    destination: str | None = None
    depart_time: str | None = None
    arrive_time: str | None = None
    carriers: list[str] = field(default_factory=list)
    flight_numbers: list[str] = field(default_factory=list)
    stops: int | None = None
    duration_minutes: int | None = None

    def describe(self) -> str:
        route = " → ".join(p for p in (self.origin, self.destination) if p) or "—"
        bits = [route]
        if self.depart_time or self.arrive_time:
            bits.append(f"{self.depart_time or '?'}–{self.arrive_time or '?'}")
        if self.flight_numbers:
            bits.append("/".join(self.flight_numbers))
        elif self.carriers:
            bits.append("/".join(self.carriers))
        if self.stops is not None:
            bits.append("直飛" if self.stops == 0 else f"轉機 {self.stops} 次")
        return " · ".join(bits)


@dataclass
class Offer:
    """A single priced itinerary scraped from trip.com."""

    query_key: str
    origin: str
    destination: str
    depart_date: str
    return_date: str
    price: float
    currency: str = "TWD"
    # "per_adult" | "total" | "unknown" -- trip.com is inconsistent about which
    # number it shows, so we record what we believe the number means.
    price_basis: str = "unknown"
    total_price: float | None = None
    carriers: list[str] = field(default_factory=list)
    outbound: Leg | None = None
    inbound: Leg | None = None
    max_stops: int | None = None
    deep_link: str = ""
    # which extraction layer produced this offer: "xhr" | "dom" | "text"
    source: str = "unknown"
    scraped_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Offer":
        raw = dict(raw)
        for side in ("outbound", "inbound"):
            leg = raw.get(side)
            raw[side] = Leg(**leg) if isinstance(leg, dict) else None
        known = {f.name for f in dataclasses.fields(cls)}
        return cls(**{k: v for k, v in raw.items() if k in known})

    def describe_price(self) -> str:
        label = {
            "per_adult": "每位成人",
            "total": "全團總價",
            "unknown": "價格",
        }[self.price_basis if self.price_basis in {"per_adult", "total"} else "unknown"]
        return f"{label} {self.currency} {self.price:,.0f}"


@dataclass
class QueryResult:
    """Outcome of scraping one SearchQuery."""

    query: SearchQuery
    offers: list[Offer] = field(default_factory=list)
    error: str | None = None
    attempts: int = 0
    url: str = ""
    scraped_at: str = ""

    @property
    def ok(self) -> bool:
        return self.error is None and bool(self.offers)

    @property
    def cheapest(self) -> Offer | None:
        return min(self.offers, key=lambda o: o.price) if self.offers else None


@dataclass
class RunSummary:
    """Everything one scheduled run produced."""

    started_at: datetime
    finished_at: datetime
    results: list[QueryResult] = field(default_factory=list)

    @property
    def cheapest(self) -> Offer | None:
        offers = [o for r in self.results for o in r.offers]
        return min(offers, key=lambda o: o.price) if offers else None

    @property
    def failures(self) -> list[QueryResult]:
        return [r for r in self.results if not r.ok]
