from __future__ import annotations

from datetime import date

from tripcom_watcher.alerts import evaluate
from tripcom_watcher.config import build_config
from tripcom_watcher.models import SearchQuery
from tripcom_watcher.storage import History

from .conftest import make_offer, make_summary, raw_config

Q1 = SearchQuery("TPE", "PQC", date(2027, 2, 9), date(2027, 2, 13))
Q2 = SearchQuery("TPE", "PQC", date(2027, 2, 10), date(2027, 2, 14))


def _seed(config, total: float) -> History:
    history = History()
    history.append_run(make_summary((Q1, [make_offer(price=total / 7, total=total)])), config)
    return history


# -- first run --------------------------------------------------------------


def test_first_run_with_results_notifies_as_a_baseline(config):
    decision = evaluate(History(), make_summary((Q1, [make_offer(price=15200, total=103360)])), config)
    assert decision.send
    assert decision.kind == "baseline"
    assert decision.cheapest_total == 103360
    assert decision.previous_total is None


def test_baseline_is_suppressed_when_new_low_alerts_are_off():
    config = build_config(raw_config(notify={"on_new_low": False}))
    decision = evaluate(History(), make_summary((Q1, [make_offer(price=15200, total=103360)])), config)
    assert not decision.send


# -- new lows ---------------------------------------------------------------


def test_a_cheaper_run_is_a_new_low(config):
    history = _seed(config, 103360)
    decision = evaluate(history, make_summary((Q1, [make_offer(price=13200, total=89360)])), config)
    assert decision.send
    assert decision.kind == "new_low"
    assert decision.drop == 14000


def test_an_unchanged_price_does_not_notify(config):
    history = _seed(config, 103360)
    decision = evaluate(history, make_summary((Q1, [make_offer(price=15200, total=103360)])), config)
    assert not decision.send
    assert decision.kind == "none"


def test_a_more_expensive_run_does_not_notify(config):
    history = _seed(config, 89360)
    decision = evaluate(history, make_summary((Q1, [make_offer(price=15200, total=103360)])), config)
    assert not decision.send


def test_a_drop_smaller_than_min_drop_is_ignored():
    config = build_config(raw_config(notify={"min_drop": 2000}))
    history = _seed(config, 103360)
    decision = evaluate(history, make_summary((Q1, [make_offer(price=15100, total=102360)])), config)
    assert not decision.send


def test_a_drop_at_exactly_min_drop_notifies():
    config = build_config(raw_config(notify={"min_drop": 2000}))
    history = _seed(config, 103360)
    decision = evaluate(history, make_summary((Q1, [make_offer(price=14900, total=101360)])), config)
    assert decision.send
    assert decision.kind == "new_low"


def test_changes_are_listed_cheapest_first(config):
    summary = make_summary(
        (Q1, [make_offer(price=15200, total=103360, query_key=Q1.key)]),
        (Q2, [make_offer(price=13200, total=89360, query_key=Q2.key)]),
    )
    decision = evaluate(History(), summary, config)
    assert [c.total for c in decision.changes] == [89360, 103360]
    assert all(c.is_new_low for c in decision.changes)


def test_per_query_previous_totals_are_attached(config):
    history = _seed(config, 103360)
    summary = make_summary(
        (Q1, [make_offer(price=14000, total=95000, query_key=Q1.key)]),
        (Q2, [make_offer(price=13200, total=89360, query_key=Q2.key)]),
    )
    decision = evaluate(history, summary, config)
    by_key = {c.query_key: c for c in decision.changes}
    assert by_key[Q1.key].previous_total == 103360
    assert by_key[Q1.key].delta == -8360
    assert by_key[Q2.key].previous_total is None
    assert by_key[Q2.key].is_new_low


# -- absolute threshold -----------------------------------------------------


def test_threshold_notifies_even_without_a_new_low():
    config = build_config(raw_config(notify={"on_new_low": False, "absolute_threshold": 100000}))
    history = _seed(config, 95000)
    decision = evaluate(history, make_summary((Q1, [make_offer(price=14000, total=95000)])), config)
    assert decision.send
    assert decision.kind == "threshold"
    assert decision.threshold_hit


def test_threshold_does_not_repeat_at_the_same_price():
    config = build_config(raw_config(notify={"on_new_low": False, "absolute_threshold": 100000}))
    history = _seed(config, 95000)
    history.mark_threshold_notified(95000)
    decision = evaluate(history, make_summary((Q1, [make_offer(price=14000, total=95000)])), config)
    assert not decision.send


def test_threshold_re_alerts_when_it_dips_further():
    config = build_config(raw_config(notify={"on_new_low": False, "absolute_threshold": 100000}))
    history = _seed(config, 95000)
    history.mark_threshold_notified(95000)
    decision = evaluate(history, make_summary((Q1, [make_offer(price=13000, total=88000)])), config)
    assert decision.send
    assert decision.threshold_hit


def test_a_price_above_the_threshold_does_not_trigger_it():
    config = build_config(raw_config(notify={"on_new_low": False, "absolute_threshold": 80000}))
    history = _seed(config, 95000)
    decision = evaluate(history, make_summary((Q1, [make_offer(price=14000, total=95000)])), config)
    assert not decision.send


# -- summaries and failures -------------------------------------------------


def test_always_summary_notifies_when_nothing_changed():
    config = build_config(raw_config(notify={"always_summary": True}))
    history = _seed(config, 103360)
    decision = evaluate(history, make_summary((Q1, [make_offer(price=15200, total=103360)])), config)
    assert decision.send
    assert decision.kind == "summary"


def test_a_single_failed_run_stays_quiet(config):
    decision = evaluate(History(), make_summary(errors=((Q1, "BlockedError: 人機驗證"),)), config)
    assert not decision.send
    assert decision.kind == "none"


def test_persistent_failures_raise_an_alert(config):
    history = History()
    failing = make_summary(errors=((Q1, "BlockedError: 人機驗證"),))
    history.append_run(failing, config)
    history.append_run(failing, config)
    decision = evaluate(history, failing, config)
    assert decision.send
    assert decision.kind == "failure"
    assert "連續 3 次" in decision.reasons[0]


def test_partial_failures_are_reported_alongside_results(config):
    summary = make_summary(
        (Q1, [make_offer(price=15200, total=103360)]), errors=((Q2, "timeout"),)
    )
    decision = evaluate(History(), summary, config)
    assert decision.send
    assert len(decision.failures) == 1
    assert any("1 組查詢失敗" in reason for reason in decision.reasons)


def test_a_per_seat_to_total_basis_flip_is_not_mistaken_for_a_change(config):
    """Guards the reason pricing.canonical_total exists."""
    history = History()
    history.append_run(
        make_summary((Q1, [make_offer(price=15200, basis="per_adult", total=None)])), config
    )
    flipped = make_summary((Q1, [make_offer(price=15200 * 7, basis="total", total=None)]))
    assert not evaluate(history, flipped, config).send
