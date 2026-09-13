from __future__ import annotations

import json
from datetime import date

from tripcom_watcher.models import SearchQuery
from tripcom_watcher.storage import OVERALL_KEY, History

from .conftest import make_offer, make_summary

Q1 = SearchQuery("TPE", "PQC", date(2027, 2, 9), date(2027, 2, 13))
Q2 = SearchQuery("TPE", "PQC", date(2027, 2, 10), date(2027, 2, 14))


def test_missing_file_starts_an_empty_history(tmp_path):
    history = History.load(tmp_path / "nope.json")
    assert history.run_count == 0
    assert history.overall_best() is None


def test_save_then_load_round_trips(config):
    history = History()
    offer = make_offer(price=15200, total=103360)
    history.append_run(make_summary((Q1, [offer])), config)
    history.save(config.history_path)

    reloaded = History.load(config.history_path)
    assert reloaded.run_count == 1
    assert reloaded.overall_best().total == 103360
    assert reloaded.overall_best().offer.carriers == ["VJ"]


def test_corrupt_file_is_set_aside_not_fatal(config):
    config.history_path.parent.mkdir(parents=True, exist_ok=True)
    config.history_path.write_text("{definitely not json", encoding="utf-8")

    history = History.load(config.history_path)
    assert history.run_count == 0
    assert config.history_path.with_suffix(".json.corrupt").exists()


def test_best_is_tracked_per_query_and_overall(config):
    history = History()
    history.append_run(
        make_summary(
            (Q1, [make_offer(price=15200, total=103360, query_key=Q1.key)]),
            (Q2, [make_offer(price=13200, total=89360, query_key=Q2.key, depart="2027-02-10", ret="2027-02-14")]),
        ),
        config,
    )
    assert history.best(Q1.key).total == 103360
    assert history.best(Q2.key).total == 89360
    assert history.best(OVERALL_KEY).total == 89360


def test_a_more_expensive_run_does_not_overwrite_the_best(config):
    history = History()
    history.append_run(make_summary((Q1, [make_offer(price=13200, total=89360)])), config)
    history.append_run(make_summary((Q1, [make_offer(price=15200, total=103360)])), config)
    assert history.overall_best().total == 89360
    assert history.run_count == 2


def test_record_best_reports_whether_it_improved(config):
    history = History()
    assert history.record_best("k", make_offer(price=15200, total=103360), config) is True
    assert history.record_best("k", make_offer(price=15200, total=103360), config) is False
    assert history.record_best("k", make_offer(price=13200, total=89360), config) is True


def test_consecutive_failures_are_counted_and_reset(config):
    history = History()
    failing = make_summary(errors=((Q1, "BlockedError: 人機驗證"),))
    history.append_run(failing, config)
    history.append_run(failing, config)
    assert history.consecutive_failed_runs == 2

    history.append_run(make_summary((Q1, [make_offer(price=15200, total=103360)])), config)
    assert history.consecutive_failed_runs == 0


def test_partial_success_does_not_count_as_a_failed_run(config):
    history = History()
    history.append_run(
        make_summary((Q1, [make_offer(price=15200, total=103360)]), errors=((Q2, "timeout"),)),
        config,
    )
    assert history.consecutive_failed_runs == 0


def test_runs_are_trimmed_to_keep_runs(config):
    history = History()
    for _ in range(8):
        history.append_run(make_summary((Q1, [make_offer(price=15200, total=103360)])), config)
    history.save(config.history_path, keep_runs=3)
    assert len(json.loads(config.history_path.read_text(encoding="utf-8"))["runs"]) == 3


def test_totals_series_exposes_recent_cheapest_values(config):
    history = History()
    for total in (103360, 95000, 89360):
        history.append_run(make_summary((Q1, [make_offer(price=total / 7, total=total)])), config)
    assert [value for _, value in history.totals_series()] == [103360, 95000, 89360]


def test_failed_run_records_a_null_cheapest(config):
    history = History()
    history.append_run(make_summary(errors=((Q1, "timeout"),)), config)
    assert history.totals_series() == [(history.data["updated_at"], None)]


def test_saving_creates_the_parent_directory(tmp_path):
    target = tmp_path / "nested" / "deeper" / "history.json"
    History().save(target)
    assert target.exists()
