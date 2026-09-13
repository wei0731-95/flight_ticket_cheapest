from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from tripcom_watcher.queries import build_queries, build_url, date_pairs, search_params

from .conftest import raw_config
from tripcom_watcher.config import build_config


def test_date_pairs_cover_four_and_five_nights(config):
    assert date_pairs(config.search) == [
        ("2027-02-09", "2027-02-13"),
        ("2027-02-09", "2027-02-14"),
        ("2027-02-10", "2027-02-14"),
    ]


def test_pairs_never_return_after_the_window_closes(config):
    for depart, ret in date_pairs(config.search):
        assert ret <= config.search.window_end.isoformat()
        assert depart >= config.search.window_start.isoformat()


def test_only_four_nights_when_max_nights_is_four():
    search = build_config(raw_config(search={"max_nights": 4})).search
    assert date_pairs(search) == [
        ("2027-02-09", "2027-02-13"),
        ("2027-02-10", "2027-02-14"),
    ]


def test_build_queries_multiplies_origins_by_date_pairs(config):
    queries = build_queries(config.search)
    assert len(queries) == 6
    assert len({q.key for q in queries}) == 6
    assert {q.origin for q in queries} == {"TPE", "TSA"}


def test_queries_are_sorted_by_departure_then_origin(config):
    keys = [q.key for q in build_queries(config.search)]
    assert keys == sorted(keys, key=lambda k: (k.split("_")[1], k.split("_")[2], k[:3]))


def test_nights_and_days_are_consistent(config):
    for query in build_queries(config.search):
        assert query.nights in (4, 5)
        assert query.days == query.nights + 1


def test_search_params_carry_the_party_size(config, query):
    params = search_params(query, config.search)
    assert params["quantity"] == "5"
    assert params["childqty"] == "2"
    assert params["babyqty"] == "0"
    assert params["triptype"] == "rt"
    assert params["class"] == "y"
    assert params["curr"] == "TWD"


def test_direct_only_adds_the_nonstop_flags(query):
    search = build_config(raw_config(search={"max_stops": 0})).search
    params = search_params(query, search)
    assert params["stops"] == "0"
    assert params["nonstop"] == "1"


def test_unlimited_stops_omits_the_flags(config, query):
    params = search_params(query, config.search)
    assert "stops" not in params
    assert "nonstop" not in params


def test_build_url_is_a_valid_tripcom_search(config, query):
    parsed = urlparse(build_url(query, config.search))
    assert parsed.netloc == "www.trip.com"
    assert parsed.path == "/flights/showfarefirst"
    assert parse_qs(parsed.query)["ddate"] == ["2027-02-09"]
    assert parse_qs(parsed.query)["rdate"] == ["2027-02-13"]


def test_search_url_carries_every_param(config, query):
    query_string = parse_qs(urlparse(build_url(query, config.search)).query)
    for key in ("dcity", "acity", "ddate", "rdate", "triptype", "class", "quantity", "childqty"):
        assert key in query_string
