"""Make fares from different runs comparable.

trip.com sometimes shows a per-adult fare and sometimes a party total, and which
one we get can change between runs. Comparing the raw numbers would manufacture
fake "new lows", so everything is canonicalised to an estimated party total
before it is stored or compared. The raw number and its basis are kept for
display so the email always shows what trip.com actually said.
"""

from __future__ import annotations

from .models import Offer, Passengers

# Infants on a lap typically pay ~10% of an adult fare. Only used to estimate a
# party total for comparison purposes, never presented as a quote.
INFANT_FARE_RATIO = 0.1


def canonical_total(offer: Offer, passengers: Passengers) -> float:
    """Best estimate of what the whole party pays, in the offer's currency.

    An explicit total from trip.com always wins. Otherwise the headline number
    is treated as per-seat -- which is trip.com's default display -- and scaled
    by the party size.
    """
    if offer.price_basis == "total":
        return float(offer.price)
    if offer.total_price is not None:
        return float(offer.total_price)
    seats = max(1, passengers.seated)
    return float(offer.price) * (seats + passengers.infants * INFANT_FARE_RATIO)


def is_estimated(offer: Offer) -> bool:
    """True when :func:`canonical_total` had to extrapolate from a per-seat fare."""
    return offer.price_basis != "total" and offer.total_price is None
