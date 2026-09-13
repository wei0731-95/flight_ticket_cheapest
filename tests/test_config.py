from __future__ import annotations

import pytest

from tripcom_watcher.config import ConfigError, MailConfig, build_config

from .conftest import raw_config


def test_loads_expected_values(config):
    assert config.search.origins == ("TPE", "TSA")
    assert config.search.destination == "PQC"
    assert config.search.passengers.seated == 7
    assert config.search.cabin_code == "y"


def test_window_end_before_start_is_rejected():
    with pytest.raises(ConfigError, match="window_end"):
        build_config(raw_config(search={"window_end": "2027-02-01"}))


def test_max_nights_below_min_is_rejected():
    with pytest.raises(ConfigError, match="max_nights"):
        build_config(raw_config(search={"min_nights": 5, "max_nights": 3}))


def test_unknown_cabin_is_rejected():
    with pytest.raises(ConfigError, match="cabin"):
        build_config(raw_config(search={"cabin": "sleeper"}))


def test_too_many_seated_passengers_is_rejected():
    with pytest.raises(ConfigError, match="9"):
        build_config(raw_config(search={"passengers": {"adults": 8, "children": 3}}))


def test_sanity_range_must_be_ordered():
    with pytest.raises(ConfigError, match="price_sanity_min"):
        build_config(raw_config(scrape={"price_sanity_min": 9000, "price_sanity_max": 1000}))


def test_mail_config_parses_multiple_recipients():
    mail = MailConfig.from_env(
        {
            "SMTP_USER": "bot@gmail.com",
            "SMTP_PASSWORD": "secret",
            "MAIL_TO": "a@example.com, b@example.com;c@example.com",
        }
    )
    assert mail.recipients == ("a@example.com", "b@example.com", "c@example.com")
    assert mail.sender == "bot@gmail.com"
    assert mail.configured


def test_mail_config_reports_missing_pieces():
    mail = MailConfig.from_env({"SMTP_USER": "bot@gmail.com"})
    assert not mail.configured
    assert set(mail.missing()) == {"SMTP_PASSWORD", "MAIL_TO"}


def test_mail_config_falls_back_to_default_port_on_garbage():
    assert MailConfig.from_env({"SMTP_PORT": "not-a-port"}).port == 587
