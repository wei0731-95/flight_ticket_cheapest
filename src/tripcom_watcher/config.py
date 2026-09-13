"""Load and validate config.yaml."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from .models import Passengers

CABIN_CODES = {
    "economy": "y",
    "premium_economy": "s",
    "business": "c",
    "first": "f",
}


class ConfigError(ValueError):
    """Raised when config.yaml is missing something we need."""


@dataclass(frozen=True)
class SearchConfig:
    origins: tuple[str, ...]
    destination: str
    window_start: date
    window_end: date
    min_nights: int
    max_nights: int
    passengers: Passengers
    cabin: str
    currency: str
    locale: str
    max_stops: int | None

    @property
    def cabin_code(self) -> str:
        return CABIN_CODES[self.cabin]


@dataclass(frozen=True)
class ScrapeConfig:
    headless: bool = True
    timeout_ms: int = 90_000
    results_timeout_ms: int = 45_000
    attempts: int = 3
    # Wall-clock budget for one whole run. Queries still pending when it is
    # spent are reported as skipped, so a slow run always finishes cleanly
    # instead of being killed by the CI job timeout.
    run_budget_s: float = 1500
    retry_backoff_s: tuple[float, ...] = (8, 25, 60)
    delay_between_queries_s: tuple[float, float] = (6, 18)
    price_sanity_min: float = 3_000
    price_sanity_max: float = 600_000
    # Pin trip.com result-card selectors here once the live markup is known;
    # empty means fall back to the structural heuristic in browser_js.py.
    card_selectors: tuple[str, ...] = ()
    debug_dump: bool = False


@dataclass(frozen=True)
class NotifyConfig:
    on_new_low: bool = True
    absolute_threshold: float | None = None
    min_drop: float = 1
    always_summary: bool = False
    failure_alert_threshold: int = 3


@dataclass(frozen=True)
class StorageConfig:
    history_path: Path = Path("data/price_history.json")
    keep_runs: int = 500


@dataclass(frozen=True)
class MailConfig:
    """Read from the environment, never from config.yaml."""

    host: str = "smtp.gmail.com"
    port: int = 587
    user: str = ""
    password: str = ""
    sender: str = ""
    recipients: tuple[str, ...] = ()

    @property
    def configured(self) -> bool:
        return bool(self.host and self.user and self.password and self.recipients)

    def missing(self) -> list[str]:
        pairs = {
            "SMTP_HOST": self.host,
            "SMTP_USER": self.user,
            "SMTP_PASSWORD": self.password,
            "MAIL_TO": self.recipients,
        }
        return [name for name, value in pairs.items() if not value]

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "MailConfig":
        env = dict(os.environ if env is None else env)
        user = env.get("SMTP_USER", "").strip()
        raw_to = env.get("MAIL_TO", "").strip()
        recipients = tuple(a.strip() for a in raw_to.replace(";", ",").split(",") if a.strip())
        try:
            port = int(env.get("SMTP_PORT", "587") or 587)
        except ValueError:
            port = 587
        return cls(
            host=env.get("SMTP_HOST", "smtp.gmail.com").strip(),
            port=port,
            user=user,
            password=env.get("SMTP_PASSWORD", ""),
            sender=env.get("MAIL_FROM", "").strip() or user,
            recipients=recipients,
        )


@dataclass(frozen=True)
class Config:
    search: SearchConfig
    scrape: ScrapeConfig = field(default_factory=ScrapeConfig)
    notify: NotifyConfig = field(default_factory=NotifyConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    root: Path = Path(".")

    @property
    def history_path(self) -> Path:
        path = self.storage.history_path
        return path if path.is_absolute() else self.root / path


def _as_date(value: Any, field_name: str) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ConfigError(f"search.{field_name} 必須是 YYYY-MM-DD 格式，收到 {value!r}") from exc


def _as_pair(value: Any, default: tuple[float, float]) -> tuple[float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return default
    low, high = float(value[0]), float(value[1])
    return (low, high) if low <= high else (high, low)


def load_config(path: str | Path = "config.yaml") -> Config:
    path = Path(path)
    if not path.exists():
        raise ConfigError(f"找不到設定檔：{path}")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ConfigError(f"{path} 的內容不是 YAML 物件")
    return build_config(raw, root=path.resolve().parent)


def build_config(raw: dict[str, Any], root: Path = Path(".")) -> Config:
    search_raw = raw.get("search") or {}
    if not isinstance(search_raw, dict):
        raise ConfigError("search 區段必須是 YAML 物件")

    origins = tuple(str(o).strip().upper() for o in search_raw.get("origins") or [])
    if not origins:
        raise ConfigError("search.origins 至少要有一個機場代碼")
    destination = str(search_raw.get("destination") or "").strip().upper()
    if not destination:
        raise ConfigError("search.destination 不可為空")

    window_start = _as_date(search_raw.get("window_start"), "window_start")
    window_end = _as_date(search_raw.get("window_end"), "window_end")
    if window_end < window_start:
        raise ConfigError("search.window_end 不可早於 search.window_start")

    min_nights = int(search_raw.get("min_nights", 1))
    max_nights = int(search_raw.get("max_nights", min_nights))
    if min_nights < 1:
        raise ConfigError("search.min_nights 至少要是 1")
    if max_nights < min_nights:
        raise ConfigError("search.max_nights 不可小於 search.min_nights")

    pax_raw = search_raw.get("passengers") or {}
    passengers = Passengers(
        adults=int(pax_raw.get("adults", 1)),
        children=int(pax_raw.get("children", 0)),
        infants=int(pax_raw.get("infants", 0)),
        child_ages=tuple(int(a) for a in pax_raw.get("child_ages") or ()),
    )
    if passengers.adults < 1:
        raise ConfigError("search.passengers.adults 至少要是 1")
    if passengers.seated > 9:
        raise ConfigError(
            f"trip.com 單筆訂單最多 9 個佔位乘客，目前是 {passengers.seated} 位"
        )

    cabin = str(search_raw.get("cabin", "economy")).strip().lower()
    if cabin not in CABIN_CODES:
        raise ConfigError(f"search.cabin 必須是 {sorted(CABIN_CODES)} 其中之一，收到 {cabin!r}")

    max_stops = search_raw.get("max_stops")
    search = SearchConfig(
        origins=origins,
        destination=destination,
        window_start=window_start,
        window_end=window_end,
        min_nights=min_nights,
        max_nights=max_nights,
        passengers=passengers,
        cabin=cabin,
        currency=str(search_raw.get("currency", "TWD")).strip().upper(),
        locale=str(search_raw.get("locale", "zh-tw")).strip(),
        max_stops=None if max_stops is None else int(max_stops),
    )

    scrape_raw = raw.get("scrape") or {}
    defaults = ScrapeConfig()
    backoff = scrape_raw.get("retry_backoff_s") or defaults.retry_backoff_s
    scrape = ScrapeConfig(
        headless=bool(scrape_raw.get("headless", defaults.headless)),
        timeout_ms=int(scrape_raw.get("timeout_ms", defaults.timeout_ms)),
        results_timeout_ms=int(
            scrape_raw.get("results_timeout_ms", defaults.results_timeout_ms)
        ),
        attempts=max(1, int(scrape_raw.get("attempts", defaults.attempts))),
        run_budget_s=float(scrape_raw.get("run_budget_s", defaults.run_budget_s)),
        retry_backoff_s=tuple(float(x) for x in backoff),
        delay_between_queries_s=_as_pair(
            scrape_raw.get("delay_between_queries_s"), defaults.delay_between_queries_s
        ),
        price_sanity_min=float(
            scrape_raw.get("price_sanity_min", defaults.price_sanity_min)
        ),
        price_sanity_max=float(
            scrape_raw.get("price_sanity_max", defaults.price_sanity_max)
        ),
        card_selectors=tuple(
            str(s) for s in scrape_raw.get("card_selectors") or defaults.card_selectors
        ),
        debug_dump=bool(scrape_raw.get("debug_dump", defaults.debug_dump)),
    )
    if scrape.price_sanity_min >= scrape.price_sanity_max:
        raise ConfigError("scrape.price_sanity_min 必須小於 scrape.price_sanity_max")

    notify_raw = raw.get("notify") or {}
    notify_defaults = NotifyConfig()
    threshold = notify_raw.get("absolute_threshold", notify_defaults.absolute_threshold)
    notify = NotifyConfig(
        on_new_low=bool(notify_raw.get("on_new_low", notify_defaults.on_new_low)),
        absolute_threshold=None if threshold is None else float(threshold),
        min_drop=float(notify_raw.get("min_drop", notify_defaults.min_drop)),
        always_summary=bool(
            notify_raw.get("always_summary", notify_defaults.always_summary)
        ),
        failure_alert_threshold=int(
            notify_raw.get("failure_alert_threshold", notify_defaults.failure_alert_threshold)
        ),
    )

    storage_raw = raw.get("storage") or {}
    storage_defaults = StorageConfig()
    storage = StorageConfig(
        history_path=Path(
            str(storage_raw.get("history_path", storage_defaults.history_path))
        ),
        keep_runs=int(storage_raw.get("keep_runs", storage_defaults.keep_runs)),
    )

    return Config(search=search, scrape=scrape, notify=notify, storage=storage, root=root)
