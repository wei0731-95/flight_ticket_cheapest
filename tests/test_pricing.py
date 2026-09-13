from __future__ import annotations

from tripcom_watcher.models import Passengers
from tripcom_watcher.pricing import canonical_total, is_estimated

from .conftest import make_offer

PARTY = Passengers(adults=5, children=2, infants=0)


def test_explicit_total_is_used_verbatim():
    offer = make_offer(price=15200, total=103360)
    assert canonical_total(offer, PARTY) == 103360
    assert not is_estimated(offer)


def test_total_basis_is_used_verbatim():
    offer = make_offer(price=103360, basis="total", total=None)
    assert canonical_total(offer, PARTY) == 103360
    assert not is_estimated(offer)


def test_per_adult_fare_is_scaled_by_seated_passengers():
    offer = make_offer(price=15200, basis="per_adult", total=None)
    assert canonical_total(offer, PARTY) == 15200 * 7
    assert is_estimated(offer)


def test_unknown_basis_is_treated_as_per_seat():
    offer = make_offer(price=15200, basis="unknown", total=None)
    assert canonical_total(offer, PARTY) == 15200 * 7


def test_infants_are_counted_at_a_reduced_ratio():
    party = Passengers(adults=2, children=0, infants=1)
    offer = make_offer(price=10000, basis="per_adult", total=None)
    assert canonical_total(offer, party) == 10000 * 2.1


def test_a_per_seat_fare_and_a_matching_total_compare_equal():
    """The whole point: the same trip priced either way must not look like a change."""
    per_seat = make_offer(price=15200, basis="per_adult", total=None)
    as_total = make_offer(price=15200 * 7, basis="total", total=None)
    assert canonical_total(per_seat, PARTY) == canonical_total(as_total, PARTY)
