"""Pull fares out of whatever trip.com gave us.

trip.com changes its markup and its internal JSON shapes without notice, so
extraction runs in three layers and the first one that yields a plausible fare
wins:

1. ``xhr``  - walk the JSON payloads the page fetched while rendering. Richest
              data (carriers, stops, times) when the shape is recognisable.
2. ``dom``  - read the rendered result cards. Survives JSON shape changes.
3. ``text`` - regex every currency amount on the page and take the lowest
              plausible one. Loses all detail but still answers "how cheap".

Every layer is keyed off *hints* rather than exact field names, and everything
is filtered through a price sanity range so baggage fees and taxes on the page
do not masquerade as fares.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Iterator

from .models import Leg, Offer, SearchQuery

# --- key hints -------------------------------------------------------------

_PRICE_KEY = re.compile(r"(price|fare|amount|cost)", re.I)
# Keys that merely *mention* price but never hold a number we want.
_PRICE_KEY_DENY = re.compile(
    r"(id|type|tag|level|desc|label|unit|code|url|key|name|currency|text|class|style|flag|rate|token)$",
    re.I,
)
_TOTAL_KEY = re.compile(r"(total|sum|all|order|grand)", re.I)
_PER_ADULT_KEY = re.compile(r"(adult|avg|average|person|passenger|unit|each)", re.I)

_SEGMENT_KEYS = {
    "segments",
    "segmentlist",
    "segmentinfolist",
    "journeylist",
    "journeys",
    "legs",
    "leglist",
    "flightsegments",
    "flightlist",
    "sequencelist",
    "sequences",
    "routelist",
    "translist",
    "tripsegments",
}
_FLIGHT_FIELD_KEYS = {
    "flightno",
    "flightnumber",
    "flightnum",
    "marketairline",
    "airlinecode",
    "carrier",
    "departairport",
    "arriveairport",
    "dcity",
    "acity",
}

_CARRIER_KEY = re.compile(r"(airlinecode|carrier|marketairline|operateairline|airline)$", re.I)
_FLIGHT_NO_KEY = re.compile(r"(flightno|flightnumber|flightnum)$", re.I)
_DEPART_AIRPORT_KEY = re.compile(r"(departairport|dairport|dportcode|origin|dcity|from)$", re.I)
_ARRIVE_AIRPORT_KEY = re.compile(r"(arriveairport|aairport|aportcode|destination|acity|to)$", re.I)
_DEPART_TIME_KEY = re.compile(r"(departtime|dtime|departuretime|departdatetime)$", re.I)
_ARRIVE_TIME_KEY = re.compile(r"(arrivetime|atime|arrivaltime|arrivedatetime)$", re.I)
_STOPS_KEY = re.compile(r"(stop(s|count|num|number)?|transfercount|transfernum)$", re.I)
_DURATION_KEY = re.compile(r"(duration|totalduration|flighttime|traveltime|costtime)$", re.I)

_BARE_AMOUNT_KEYS = {"value", "amount", "total", "displayvalue", "display"}
# Guard against pathological payloads with huge price arrays.
_MAX_PRICE_LIST_ITEMS = 50

_IATA = re.compile(r"^[A-Z]{3}$")
_AIRLINE_CODE = re.compile(r"^[0-9A-Z]{2}$")

# --- text amounts ----------------------------------------------------------

_AMOUNT = re.compile(
    r"\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?"   # 12,345 / 1,234,567.89
    r"|\d{4,7}(?:\.\d{1,2})?"              # 12345
)
_CURRENCY_MARK = re.compile(r"(NT\$|NTD|TWD|US\$|USD|HK\$|RMB|CNY|JPY|EUR|GBP|[$￥¥€£])\s*$")

_PER_ADULT_TEXT = re.compile(r"(每位成人|每人|每位|per\s+adult|per\s+person|/\s*人|人均)", re.I)
_TOTAL_TEXT = re.compile(r"(總價|总价|總計|总计|合計|合计|total\s+price|total:)", re.I)


class PriceSanity:
    """Plausible fare range, used to reject page noise."""

    def __init__(self, minimum: float, maximum: float) -> None:
        self.minimum = float(minimum)
        self.maximum = float(maximum)

    def accepts(self, value: Any) -> bool:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False
        return self.minimum <= float(value) <= self.maximum


# --- generic helpers -------------------------------------------------------


def _walk(node: Any) -> Iterator[dict]:
    """Yield every dict nested anywhere inside ``node``."""
    stack = [node]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            yield current
            stack.extend(current.values())
        elif isinstance(current, (list, tuple)):
            stack.extend(current)


def _norm(key: str) -> str:
    return key.replace("_", "").replace("-", "").lower()


def _numeric(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.replace(",", "").strip()
        if re.fullmatch(r"\d+(?:\.\d+)?", cleaned):
            return float(cleaned)
    return None


def _first_str(node: dict, pattern: re.Pattern[str], validator: re.Pattern[str] | None = None) -> str | None:
    for key, value in node.items():
        if not isinstance(value, str) or not pattern.search(_norm(key)):
            continue
        candidate = value.strip()
        if not candidate:
            continue
        if validator and not validator.fullmatch(candidate.upper()):
            continue
        return candidate.upper() if validator else candidate
    return None


def _first_int(node: dict, pattern: re.Pattern[str]) -> int | None:
    for key, value in node.items():
        if pattern.search(_norm(key)):
            number = _numeric(value)
            if number is not None:
                return int(number)
    return None


# --- layer 1: XHR JSON -----------------------------------------------------


def _is_price_key(normalized: str) -> bool:
    return bool(_PRICE_KEY.search(normalized)) and not _PRICE_KEY_DENY.search(normalized)


def _price_candidates(node: dict, sanity: PriceSanity) -> list[tuple[float, str]]:
    """(amount, basis) pairs on ``node`` or one level inside its price containers.

    trip.com puts fares in several shapes -- ``{"price": 12345}``,
    ``{"price": {"value": 12345}}`` and ``{"priceList": [{"adultPrice": ...}]}``
    have all been seen -- so we scan the node itself plus one level into any
    child whose key looks price-related.
    """
    found: list[tuple[float, str]] = []

    def consider(key: str, value: Any, *, inside_price_container: bool = False) -> None:
        normalized = _norm(key)
        if not _is_price_key(normalized):
            # Inside a price container a bare "value"/"amount" is still a fare.
            if not (inside_price_container and normalized in _BARE_AMOUNT_KEYS):
                return
        amount = _numeric(value)
        if amount is None or not sanity.accepts(amount):
            return
        if _TOTAL_KEY.search(normalized):
            basis = "total"
        elif _PER_ADULT_KEY.search(normalized):
            basis = "per_adult"
        else:
            basis = "unknown"
        found.append((amount, basis))

    def scan(mapping: dict, *, inside_price_container: bool) -> None:
        for key, value in mapping.items():
            consider(key, value, inside_price_container=inside_price_container)

    scan(node, inside_price_container=False)
    for key, value in node.items():
        if not _is_price_key(_norm(key)):
            continue
        if isinstance(value, dict):
            scan(value, inside_price_container=True)
        elif isinstance(value, list):
            for item in value[:_MAX_PRICE_LIST_ITEMS]:
                if isinstance(item, dict):
                    scan(item, inside_price_container=True)
    return found


def _looks_like_itinerary(node: dict) -> bool:
    keys = {_norm(k) for k in node}
    if keys & _SEGMENT_KEYS:
        return any(isinstance(node[k], list) and node[k] for k in node if _norm(k) in _SEGMENT_KEYS)
    return len(keys & _FLIGHT_FIELD_KEYS) >= 2


def _segments_of(node: dict) -> list[dict]:
    segments: list[dict] = []
    for key, value in node.items():
        if _norm(key) in _SEGMENT_KEYS and isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    # A journey may itself wrap another segment list.
                    nested = _segments_of(item)
                    segments.extend(nested or [item])
    return segments


def _leg_from(segments: list[dict]) -> Leg | None:
    if not segments:
        return None
    leg = Leg()
    for segment in segments:
        carrier = _first_str(segment, _CARRIER_KEY, _AIRLINE_CODE)
        if carrier and carrier not in leg.carriers:
            leg.carriers.append(carrier)
        flight_no = _first_str(segment, _FLIGHT_NO_KEY)
        if flight_no and flight_no not in leg.flight_numbers:
            leg.flight_numbers.append(flight_no)
    leg.origin = _first_str(segments[0], _DEPART_AIRPORT_KEY, _IATA)
    leg.destination = _first_str(segments[-1], _ARRIVE_AIRPORT_KEY, _IATA)
    leg.depart_time = _first_str(segments[0], _DEPART_TIME_KEY)
    leg.arrive_time = _first_str(segments[-1], _ARRIVE_TIME_KEY)
    leg.stops = len(segments) - 1
    duration = _first_int(segments[0], _DURATION_KEY) if len(segments) == 1 else None
    leg.duration_minutes = duration
    return leg


def _split_legs(segments: list[dict], query: SearchQuery) -> tuple[Leg | None, Leg | None]:
    """Group segments into outbound/inbound using the origin airport as the pivot."""
    if not segments:
        return None, None

    outbound: list[dict] = []
    inbound: list[dict] = []
    current = outbound
    for index, segment in enumerate(segments):
        origin = _first_str(segment, _DEPART_AIRPORT_KEY, _IATA)
        # A later segment departing from the destination starts the way home.
        if index and origin == query.destination and current is outbound:
            current = inbound
        current.append(segment)

    if not inbound:
        # Fall back to splitting on the trip's arrival back at the origin.
        for index, segment in enumerate(segments):
            arrival = _first_str(segment, _ARRIVE_AIRPORT_KEY, _IATA)
            if arrival == query.origin and index + 1 < len(segments):
                outbound, inbound = segments[: index + 1], segments[index + 1 :]
                break
    return _leg_from(outbound), _leg_from(inbound)


def offers_from_payloads(
    payloads: Iterable[Any],
    query: SearchQuery,
    sanity: PriceSanity,
    *,
    currency: str = "TWD",
    deep_link: str = "",
    scraped_at: str = "",
) -> list[Offer]:
    """Layer 1: reconstruct itineraries from captured XHR JSON."""
    offers: list[Offer] = []
    seen: set[tuple[float, str]] = set()

    for payload in payloads:
        for node in _walk(payload):
            if not _looks_like_itinerary(node):
                continue
            candidates = _price_candidates(node, sanity)
            if not candidates:
                continue

            total = next((amount for amount, basis in candidates if basis == "total"), None)
            per_adult = next(
                (amount for amount, basis in candidates if basis == "per_adult"), None
            )
            headline, basis = min(candidates, key=lambda pair: pair[0])
            if per_adult is not None:
                headline, basis = per_adult, "per_adult"

            segments = _segments_of(node)
            outbound, inbound = _split_legs(segments, query)
            carriers = sorted(
                {c for leg in (outbound, inbound) if leg for c in leg.carriers}
            )

            fingerprint = (headline, "|".join(carriers))
            if fingerprint in seen:
                continue
            seen.add(fingerprint)

            stops = [leg.stops for leg in (outbound, inbound) if leg and leg.stops is not None]
            offers.append(
                Offer(
                    query_key=query.key,
                    origin=query.origin,
                    destination=query.destination,
                    depart_date=query.depart_date.isoformat(),
                    return_date=query.return_date.isoformat(),
                    price=headline,
                    currency=currency,
                    price_basis=basis,
                    total_price=total,
                    carriers=carriers,
                    outbound=outbound,
                    inbound=inbound,
                    max_stops=max(stops) if stops else None,
                    deep_link=deep_link,
                    source="xhr",
                    scraped_at=scraped_at,
                )
            )
    return offers


# --- layer 2 + 3: rendered page -------------------------------------------


def amounts_in_text(text: str, sanity: PriceSanity) -> list[tuple[float, bool]]:
    """(amount, had_currency_marker) for every plausible amount in ``text``."""
    results: list[tuple[float, bool]] = []
    for match in _AMOUNT.finditer(text):
        amount = _numeric(match.group(0))
        if amount is None or not sanity.accepts(amount):
            continue
        prefix = text[max(0, match.start() - 8) : match.start()]
        results.append((amount, bool(_CURRENCY_MARK.search(prefix))))
    return results


def _basis_from_text(text: str) -> str:
    if _TOTAL_TEXT.search(text):
        return "total"
    if _PER_ADULT_TEXT.search(text):
        return "per_adult"
    return "unknown"


def offers_from_cards(
    cards: Iterable[dict[str, Any]],
    query: SearchQuery,
    sanity: PriceSanity,
    *,
    currency: str = "TWD",
    deep_link: str = "",
    scraped_at: str = "",
) -> list[Offer]:
    """Layer 2: one offer per rendered result card."""
    offers: list[Offer] = []
    for card in cards:
        text = (card.get("text") or "").strip()
        if not text:
            continue
        amounts = amounts_in_text(text, sanity)
        if not amounts:
            continue
        # A card's fare is the currency-marked amount when there is one.
        marked = [amount for amount, marked_ in amounts if marked_]
        price = min(marked) if marked else min(amount for amount, _ in amounts)

        carriers = sorted(set(re.findall(r"\b([0-9A-Z]{2})\d{2,4}\b", text.upper())))
        stops = None
        if re.search(r"(直飛|直达|nonstop|direct)", text, re.I):
            stops = 0
        else:
            stop_match = re.search(r"(?:轉機|转机|stop)\D{0,4}(\d)", text, re.I)
            if stop_match:
                stops = int(stop_match.group(1))

        offers.append(
            Offer(
                query_key=query.key,
                origin=query.origin,
                destination=query.destination,
                depart_date=query.depart_date.isoformat(),
                return_date=query.return_date.isoformat(),
                price=price,
                currency=currency,
                price_basis=_basis_from_text(text),
                carriers=carriers,
                max_stops=stops,
                deep_link=card.get("href") or deep_link,
                source="dom",
                scraped_at=scraped_at,
            )
        )
    return offers


def offer_from_page_text(
    text: str,
    query: SearchQuery,
    sanity: PriceSanity,
    *,
    currency: str = "TWD",
    deep_link: str = "",
    scraped_at: str = "",
) -> Offer | None:
    """Layer 3: last resort - the cheapest currency-marked number on the page."""
    amounts = amounts_in_text(text, sanity)
    marked = [amount for amount, marked_ in amounts if marked_]
    pool = marked or [amount for amount, _ in amounts]
    if not pool:
        return None
    return Offer(
        query_key=query.key,
        origin=query.origin,
        destination=query.destination,
        depart_date=query.depart_date.isoformat(),
        return_date=query.return_date.isoformat(),
        price=min(pool),
        currency=currency,
        price_basis=_basis_from_text(text),
        deep_link=deep_link,
        source="text",
        scraped_at=scraped_at,
    )


def extract_offers(
    *,
    query: SearchQuery,
    sanity: PriceSanity,
    payloads: Iterable[Any] = (),
    cards: Iterable[dict[str, Any]] = (),
    page_text: str = "",
    currency: str = "TWD",
    deep_link: str = "",
    scraped_at: str = "",
) -> list[Offer]:
    """Run the layers in order and return the first non-empty result."""
    common = dict(currency=currency, deep_link=deep_link, scraped_at=scraped_at)

    offers = offers_from_payloads(payloads, query, sanity, **common)
    if offers:
        return sorted(offers, key=lambda o: o.price)

    offers = offers_from_cards(cards, query, sanity, **common)
    if offers:
        return sorted(offers, key=lambda o: o.price)

    single = offer_from_page_text(page_text, query, sanity, **common)
    return [single] if single else []
