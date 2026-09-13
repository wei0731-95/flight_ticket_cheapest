from __future__ import annotations

from datetime import date

from tripcom_watcher import report
from tripcom_watcher.alerts import Decision, PriceChange, evaluate
from tripcom_watcher.config import MailConfig
from tripcom_watcher.models import QueryResult, SearchQuery
from tripcom_watcher.notify import build_message
from tripcom_watcher.storage import History

from .conftest import make_offer, make_summary

Q1 = SearchQuery("TPE", "PQC", date(2027, 2, 9), date(2027, 2, 13))
Q2 = SearchQuery("TSA", "PQC", date(2027, 2, 10), date(2027, 2, 14))


def _decision(config) -> Decision:
    history = History()
    history.append_run(make_summary((Q1, [make_offer(price=15200, total=103360)])), config)
    summary = make_summary(
        (Q1, [make_offer(price=13200, total=89360, query_key=Q1.key)]),
        errors=((Q2, "NoResultsError: 找不到合理票價"),),
    )
    return evaluate(history, summary, config)


def test_money_formats_with_thousands_separators():
    assert report.money(103360) == "TWD 103,360"
    assert report.money(None) == "—"


def test_trip_label_shows_the_length_of_stay():
    assert report.trip_label(make_offer(price=1, depart="2027-02-09", ret="2027-02-13")) == (
        "2/9 → 2/13（5天4夜）"
    )


def test_delta_text_marks_drops_rises_and_ties():
    offer = make_offer(price=13200, total=89360)
    assert report.delta_text(PriceChange(Q1.key, offer, 89360, 103360), "TWD").startswith("↓")
    assert report.delta_text(PriceChange(Q1.key, offer, 103360, 89360), "TWD").startswith("↑")
    assert report.delta_text(PriceChange(Q1.key, offer, 89360, 89360), "TWD") == "持平"
    assert report.delta_text(PriceChange(Q1.key, offer, 89360, None), "TWD") == "首次紀錄"


def test_subject_names_the_drop_and_the_dates(config):
    subject = report.subject(_decision(config), config)
    assert "歷史新低" in subject
    assert "89,360" in subject
    assert "14,000" in subject
    assert "2/9 → 2/13" in subject


def test_failure_subject_is_distinct(config):
    decision = Decision(send=True, kind="failure", reasons=["連續 3 次失敗"])
    assert "爬取失敗警告" in report.subject(decision, config)


def test_html_body_contains_the_price_route_and_link(config):
    body = report.html_body(_decision(config), config, run_count=7)
    assert "TWD 89,360" in body
    assert "每位成人 TWD 13,200" in body
    assert "桃園(TPE)" in body
    assert "富國島(PQC)" in body
    assert "showfarefirst" in body
    assert "第 7 次檢查" in body


def test_html_body_lists_failed_combinations(config):
    body = report.html_body(_decision(config), config)
    assert "未取得報價的組合" in body
    assert "找不到合理票價" in body


def test_html_body_escapes_scraped_text(config):
    offer = make_offer(price=13200, total=89360)
    offer.carriers = ["<script>alert(1)</script>"]
    decision = Decision(
        send=True, kind="new_low", cheapest=offer, cheapest_total=89360,
        changes=[PriceChange(Q1.key, offer, 89360, 103360)],
    )
    body = report.html_body(decision, config)
    assert "<script>" not in body
    assert "&lt;script&gt;" in body


def test_html_body_notes_when_the_total_was_estimated(config):
    offer = make_offer(price=15200, basis="per_adult", total=None)
    decision = Decision(send=True, kind="baseline", cheapest=offer, cheapest_total=15200 * 7)
    assert "估算" in report.html_body(decision, config)


def test_html_body_notes_when_the_total_came_from_tripcom(config):
    offer = make_offer(price=15200, total=103360)
    decision = Decision(send=True, kind="baseline", cheapest=offer, cheapest_total=103360)
    assert "trip.com 提供的總價" in report.html_body(decision, config)


def test_text_body_is_readable_plain_text(config):
    text = report.text_body(_decision(config), config, run_count=7)
    assert "<" not in text
    assert "TWD 89,360" in text
    assert "去程" in text and "回程" in text
    assert "未取得報價" in text


def test_text_body_survives_a_decision_with_no_offers(config):
    decision = Decision(send=True, kind="failure", reasons=["連續 3 次失敗"],
                        failures=[QueryResult(query=Q2, error="timeout")])
    text = report.text_body(decision, config)
    assert "爬取失敗警告" in text
    assert "timeout" in text


def test_message_is_multipart_with_both_bodies(config):
    decision = _decision(config)
    mail = MailConfig.from_env(
        {"SMTP_USER": "bot@gmail.com", "SMTP_PASSWORD": "x", "MAIL_TO": "me@example.com"}
    )
    message = build_message(
        mail,
        report.subject(decision, config),
        report.text_body(decision, config),
        report.html_body(decision, config),
    )
    assert message["To"] == "me@example.com"
    assert "歷史新低" in message["Subject"]
    types = {part.get_content_type() for part in message.walk()}
    assert {"text/plain", "text/html"} <= types
