from __future__ import annotations

from tripcom_watcher.parsing import (
    PriceSanity,
    amounts_in_text,
    extract_offers,
    offer_from_page_text,
    offers_from_cards,
    offers_from_payloads,
)

SANITY = PriceSanity(3000, 600000)


# -- layer 1: XHR JSON ------------------------------------------------------


def test_xhr_layer_reconstructs_both_itineraries(tripcom_payload, query):
    offers = offers_from_payloads([tripcom_payload], query, SANITY)
    assert len(offers) == 2
    prices = sorted(o.price for o in offers)
    assert prices == [15200, 18999]
    assert {o.source for o in offers} == {"xhr"}


def test_xhr_layer_prefers_the_per_adult_fare_and_keeps_the_total(tripcom_payload, query):
    cheapest = min(offers_from_payloads([tripcom_payload], query, SANITY), key=lambda o: o.price)
    assert cheapest.price == 15200
    assert cheapest.price_basis == "per_adult"
    assert cheapest.total_price == 103360


def test_xhr_layer_splits_outbound_from_inbound(tripcom_payload, query):
    offers = {o.price: o for o in offers_from_payloads([tripcom_payload], query, SANITY)}
    connecting = offers[18999]
    assert connecting.outbound.origin == "TPE"
    assert connecting.outbound.destination == "PQC"
    assert connecting.outbound.flight_numbers == ["VN577", "VN1821"]
    assert connecting.outbound.stops == 1
    assert connecting.inbound.origin == "PQC"
    assert connecting.inbound.destination == "TPE"
    assert connecting.inbound.flight_numbers == ["VN1830", "VN578"]


def test_xhr_layer_marks_a_nonstop_itinerary(tripcom_payload, query):
    direct = min(offers_from_payloads([tripcom_payload], query, SANITY), key=lambda o: o.price)
    assert direct.max_stops == 0
    assert direct.carriers == ["VJ"]


def test_xhr_layer_ignores_fees_below_the_sanity_floor(tripcom_payload, query):
    # baggageFee 1200 sits outside the sanity range and must never become a fare.
    assert all(o.price >= 3000 for o in offers_from_payloads([tripcom_payload], query, SANITY))


def test_xhr_layer_reads_a_bare_nested_amount(query):
    payload = {"list": [{"price": {"value": 21000}, "segments": [
        {"departAirport": "TPE", "arriveAirport": "PQC", "airlineCode": "CI", "flightNo": "CI781"}]}]}
    offers = offers_from_payloads([payload], query, SANITY)
    assert [o.price for o in offers] == [21000]


def test_xhr_layer_labels_a_total_only_payload(query):
    payload = {"itineraryList": [{"totalPrice": 98000, "segmentList": [
        {"departAirport": "TPE", "arriveAirport": "PQC", "airlineCode": "VJ", "flightNo": "VJ931"}]}]}
    offer = offers_from_payloads([payload], query, SANITY)[0]
    assert offer.price == 98000
    assert offer.price_basis == "total"


def test_xhr_layer_skips_nodes_without_flight_information(query):
    assert offers_from_payloads([{"promo": {"price": 25000, "title": "限時優惠"}}], query, SANITY) == []


def test_xhr_layer_tolerates_junk_payloads(query):
    for payload in (None, [], {}, "nope", {"a": [1, 2, 3]}, {"deep": {"deeper": {}}}):
        assert offers_from_payloads([payload], query, SANITY) == []


# -- layer 2: DOM cards -----------------------------------------------------


def test_dom_layer_reads_price_carrier_and_stops(query):
    cards = [
        {"text": "越捷 VJ931 09:00 TPE — 12:10 PQC 直飛 每位成人 NT$15,200 行李 NT$1,200",
         "href": "https://www.trip.com/a"},
        {"text": "越南航空 VN577 08:30 TPE — 14:45 PQC 轉機 1 次 每位成人 NT$18,999",
         "href": "https://www.trip.com/b"},
    ]
    offers = offers_from_cards(cards, query, SANITY)
    assert [o.price for o in offers] == [15200, 18999]
    assert [o.max_stops for o in offers] == [0, 1]
    assert offers[0].carriers == ["VJ931"[:2]]
    assert offers[0].deep_link == "https://www.trip.com/a"
    assert offers[0].price_basis == "per_adult"


def test_dom_layer_detects_a_total_price_label(query):
    cards = [{"text": "VJ931 09:00 TPE — 12:10 PQC 總價 NT$103,360"}]
    assert offers_from_cards(cards, query, SANITY)[0].price_basis == "total"


def test_dom_layer_prefers_currency_marked_amounts(query):
    # 45678 is unmarked noise (a flight count, an id); NT$15,200 is the fare.
    cards = [{"text": "編號 45678 VJ931 09:00 — 12:10 每位成人 NT$15,200"}]
    assert offers_from_cards(cards, query, SANITY)[0].price == 15200


def test_dom_layer_skips_cards_with_no_plausible_amount(query):
    cards = [{"text": "尚無報價"}, {"text": ""}, {"text": "NT$12"}]
    assert offers_from_cards(cards, query, SANITY) == []


# -- layer 3: page text -----------------------------------------------------


def test_text_layer_returns_the_cheapest_marked_amount(query):
    text = "最低 NT$15,200 起 每位成人 · 另有 NT$18,999 · 行李 900"
    offer = offer_from_page_text(text, query, SANITY)
    assert offer.price == 15200
    assert offer.source == "text"


def test_text_layer_returns_nothing_without_amounts(query):
    assert offer_from_page_text("查無航班", query, SANITY) is None


def test_amounts_in_text_flags_currency_markers():
    found = dict(amounts_in_text("NT$15,200 與 18999", SANITY))
    assert found[15200] is True
    assert found[18999] is False


def test_sanity_rejects_booleans_and_strings():
    assert not SANITY.accepts(True)
    assert not SANITY.accepts("15200")
    assert SANITY.accepts(15200)


# -- layer ordering ---------------------------------------------------------


def test_xhr_layer_wins_when_all_layers_have_data(tripcom_payload, query):
    offers = extract_offers(
        query=query,
        sanity=SANITY,
        payloads=[tripcom_payload],
        cards=[{"text": "VJ931 09:00 — 12:10 每位成人 NT$9,999"}],
        page_text="NT$4,000",
    )
    assert {o.source for o in offers} == {"xhr"}


def test_falls_back_to_dom_when_no_json_was_captured(query):
    offers = extract_offers(
        query=query,
        sanity=SANITY,
        payloads=[],
        cards=[{"text": "VJ931 09:00 — 12:10 每位成人 NT$9,999"}],
        page_text="NT$4,000",
    )
    assert [o.source for o in offers] == ["dom"]


def test_falls_back_to_page_text_when_no_cards_were_found(query):
    offers = extract_offers(query=query, sanity=SANITY, page_text="最低 NT$9,999")
    assert [(o.source, o.price) for o in offers] == [("text", 9999)]


def test_returns_empty_when_nothing_is_parseable(query):
    assert extract_offers(query=query, sanity=SANITY, page_text="查無航班") == []


def test_offers_are_sorted_cheapest_first(tripcom_payload, query):
    offers = extract_offers(query=query, sanity=SANITY, payloads=[tripcom_payload])
    assert [o.price for o in offers] == sorted(o.price for o in offers)
