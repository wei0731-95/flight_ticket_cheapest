"""Turn the configured travel window into concrete trip.com searches."""

from __future__ import annotations

from datetime import timedelta
from urllib.parse import urlencode

from .config import SearchConfig
from .models import SearchQuery

# This page renders the search form pre-filled from the query string. It does
# NOT run the search on load -- the scraper has to press Search. (/flights/booking
# was tried as a fallback and redirects to account/signin?forcelogin=authfail.)
SEARCH_ENDPOINT = "https://www.trip.com/flights/showfarefirst"


def date_pairs(search: SearchConfig) -> list[tuple[str, str]]:
    """All (depart, return) date pairs inside the window with an allowed length."""
    pairs: list[tuple[str, str]] = []
    span = (search.window_end - search.window_start).days
    for offset in range(span + 1):
        depart = search.window_start + timedelta(days=offset)
        for nights in range(search.min_nights, search.max_nights + 1):
            ret = depart + timedelta(days=nights)
            if ret > search.window_end:
                continue
            pairs.append((depart.isoformat(), ret.isoformat()))
    return pairs


def build_queries(search: SearchConfig) -> list[SearchQuery]:
    """Every origin x date-pair combination, de-duplicated and stably ordered."""
    queries: list[SearchQuery] = []
    seen: set[str] = set()
    for depart, ret in date_pairs(search):
        for origin in search.origins:
            if origin == search.destination:
                continue
            query = SearchQuery(
                origin=origin,
                destination=search.destination,
                depart_date=_parse(depart),
                return_date=_parse(ret),
            )
            if query.key in seen:
                continue
            seen.add(query.key)
            queries.append(query)
    queries.sort(key=lambda q: (q.depart_date, q.return_date, q.origin))
    return queries


def _parse(value: str):
    from datetime import date

    return date.fromisoformat(value)


def search_params(query: SearchQuery, search: SearchConfig) -> dict[str, str]:
    """Query-string parameters trip.com's round-trip search expects."""
    pax = search.passengers
    params = {
        "dcity": query.origin.lower(),
        "acity": query.destination.lower(),
        "ddate": query.depart_date.isoformat(),
        "rdate": query.return_date.isoformat(),
        "triptype": "rt",
        "class": search.cabin_code,
        "quantity": str(pax.adults),
        "childqty": str(pax.children),
        "babyqty": str(pax.infants),
        "searchboxarg": "t",
        "lowpricesource": "searchform",
        "locale": search.locale,
        "curr": search.currency,
    }
    if search.max_stops is not None:
        # 0 = direct only, 1 = at most one stop. trip.com also accepts the
        # "nonstop" toggle, which we set together with the stop count.
        params["stops"] = str(search.max_stops)
        if search.max_stops == 0:
            params["nonstop"] = "1"
    return params


def build_url(query: SearchQuery, search: SearchConfig) -> str:
    return f"{SEARCH_ENDPOINT}?{urlencode(search_params(query, search))}"
