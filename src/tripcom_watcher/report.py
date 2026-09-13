"""Render a run into an email subject, an HTML body and a console summary."""

from __future__ import annotations

import html
from datetime import date

from .alerts import Decision, PriceChange
from .config import Config
from .models import Offer, QueryResult, airport_label
from .pricing import is_estimated

_BG = "#f5f6f8"
_CARD = "#ffffff"
_INK = "#1b1d21"
_MUTED = "#6b7280"
_LINE = "#e3e6ea"
_GOOD = "#0f7b43"
_BAD = "#b42318"
_ACCENT = "#0b6bcb"


# -- small formatters -------------------------------------------------------


def money(amount: float | None, currency: str = "TWD") -> str:
    return "—" if amount is None else f"{currency} {amount:,.0f}"


def _short_date(value: str) -> str:
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        return value
    return f"{parsed.month}/{parsed.day}"


def trip_label(offer: Offer) -> str:
    try:
        nights = (date.fromisoformat(offer.return_date) - date.fromisoformat(offer.depart_date)).days
        length = f"{nights + 1}天{nights}夜"
    except ValueError:
        length = ""
    return f"{_short_date(offer.depart_date)} → {_short_date(offer.return_date)}" + (
        f"（{length}）" if length else ""
    )


def delta_text(change: PriceChange, currency: str) -> str:
    if change.previous_total is None:
        return "首次紀錄"
    diff = change.delta or 0
    if diff < 0:
        return f"↓ {money(abs(diff), currency)}"
    if diff > 0:
        return f"↑ {money(diff, currency)}"
    return "持平"


def subject(decision: Decision, config: Config) -> str:
    route = f"台北→{config.search.destination}"
    if decision.kind == "failure":
        return f"[機票監控] 爬取失敗警告 · {route}"
    if decision.cheapest is None:
        return f"[機票監控] 無資料 · {route}"

    price = money(decision.cheapest_total, decision.cheapest.currency)
    head = f"[機票監控] {decision.label} {price}"
    drop = decision.drop
    if decision.kind == "new_low" and drop:
        head += f"（↓{money(drop, decision.cheapest.currency)}）"
    return f"{head} · {trip_label(decision.cheapest)} · {decision.cheapest.origin}"


# -- html -------------------------------------------------------------------


def _cell(content: str, *, align: str = "left", bold: bool = False, color: str = _INK) -> str:
    weight = "600" if bold else "400"
    return (
        f'<td style="padding:10px 12px;border-bottom:1px solid {_LINE};'
        f'text-align:{align};font-weight:{weight};color:{color};'
        f'font-size:14px;white-space:nowrap">{content}</td>'
    )


def _head_cell(content: str, *, align: str = "left") -> str:
    return (
        f'<th style="padding:10px 12px;border-bottom:2px solid {_LINE};'
        f'text-align:{align};font-size:12px;letter-spacing:.04em;'
        f'text-transform:uppercase;color:{_MUTED};font-weight:600;'
        f'white-space:nowrap">{content}</th>'
    )


def _leg_rows(offer: Offer) -> str:
    rows = []
    for label, leg in (("去程", offer.outbound), ("回程", offer.inbound)):
        if leg is None:
            continue
        rows.append(
            f'<div style="font-size:14px;color:{_INK};margin-top:4px">'
            f'<span style="color:{_MUTED};margin-right:8px">{label}</span>'
            f"{html.escape(leg.describe())}</div>"
        )
    return "".join(rows)


def _hero(decision: Decision, config: Config) -> str:
    offer = decision.cheapest
    if offer is None:
        return ""
    currency = offer.currency
    note = "（以每位票價 × 佔位人數估算）" if is_estimated(offer) else "（trip.com 提供的總價）"
    previous = (
        f'<div style="font-size:13px;color:{_MUTED};margin-top:6px">'
        f"先前最低 {money(decision.previous_total, currency)}</div>"
        if decision.previous_total is not None
        else ""
    )
    link = (
        f'<a href="{html.escape(offer.deep_link, quote=True)}" '
        f'style="display:inline-block;margin-top:16px;padding:10px 18px;'
        f'background:{_ACCENT};color:#fff;border-radius:6px;text-decoration:none;'
        f'font-size:14px;font-weight:600">在 trip.com 查看這個組合 →</a>'
        if offer.deep_link
        else ""
    )
    return f"""
    <div style="background:{_CARD};border:1px solid {_LINE};border-radius:10px;padding:22px 24px;margin-bottom:18px">
      <div style="font-size:13px;color:{_MUTED};letter-spacing:.04em;text-transform:uppercase">{html.escape(decision.label)}</div>
      <div style="font-size:34px;font-weight:700;color:{_INK};margin-top:6px;line-height:1.15">{money(decision.cheapest_total, currency)}</div>
      <div style="font-size:13px;color:{_MUTED};margin-top:4px">全團 {html.escape(config.search.passengers.describe())}{note}</div>
      <div style="font-size:15px;color:{_INK};margin-top:12px">trip.com 顯示：{html.escape(offer.describe_price())}</div>
      {previous}
      <div style="height:1px;background:{_LINE};margin:16px 0"></div>
      <div style="font-size:15px;font-weight:600;color:{_INK}">
        {html.escape(airport_label(offer.origin))} → {html.escape(airport_label(offer.destination))}
        <span style="font-weight:400;color:{_MUTED}">· {html.escape(trip_label(offer))}</span>
      </div>
      {_leg_rows(offer)}
      {link}
    </div>
    """


def _table(decision: Decision, config: Config) -> str:
    if not decision.changes:
        return ""
    currency = config.search.currency
    rows = []
    for change in decision.changes:
        offer = change.offer
        diff = change.delta
        color = _GOOD if (diff is not None and diff < 0) else (_BAD if diff else _MUTED)
        stops = (
            "—"
            if offer.max_stops is None
            else ("直飛" if offer.max_stops == 0 else f"轉{offer.max_stops}")
        )
        link = (
            f'<a href="{html.escape(offer.deep_link, quote=True)}" style="color:{_ACCENT}">查看</a>'
            if offer.deep_link
            else "—"
        )
        rows.append(
            "<tr>"
            + _cell(html.escape(trip_label(offer)))
            + _cell(html.escape(offer.origin))
            + _cell(money(change.total, currency), align="right", bold=change.is_new_low)
            + _cell(html.escape(offer.describe_price()), align="right")
            + _cell(html.escape("/".join(offer.carriers) or "—"))
            + _cell(stops, align="center")
            + _cell(money(change.previous_total, currency), align="right", color=_MUTED)
            + _cell(delta_text(change, currency), align="right", color=color)
            + _cell(link, align="center")
            + "</tr>"
        )
    return f"""
    <div style="background:{_CARD};border:1px solid {_LINE};border-radius:10px;padding:6px 8px 2px;margin-bottom:18px;overflow-x:auto">
      <table role="presentation" style="width:100%;border-collapse:collapse;font-family:inherit">
        <thead><tr>
          {_head_cell("日期組合")}{_head_cell("出發")}{_head_cell("全團估算", align="right")}
          {_head_cell("trip.com 顯示", align="right")}{_head_cell("航空")}{_head_cell("轉機", align="center")}
          {_head_cell("前次最低", align="right")}{_head_cell("變化", align="right")}{_head_cell("連結", align="center")}
        </tr></thead>
        <tbody>{"".join(rows)}</tbody>
      </table>
    </div>
    """


def _failures(failures: list[QueryResult]) -> str:
    if not failures:
        return ""
    items = "".join(
        f'<li style="margin-bottom:4px">{html.escape(result.query.describe())}'
        f'<span style="color:{_BAD}"> — {html.escape(result.error or "沒有結果")}</span></li>'
        for result in failures
    )
    return f"""
    <div style="background:#fff7f5;border:1px solid #f3c9c0;border-radius:10px;padding:16px 20px;margin-bottom:18px">
      <div style="font-size:14px;font-weight:600;color:{_BAD};margin-bottom:8px">未取得報價的組合（{len(failures)}）</div>
      <ul style="margin:0;padding-left:20px;font-size:13px;color:{_INK}">{items}</ul>
    </div>
    """


def html_body(decision: Decision, config: Config, *, run_count: int = 0) -> str:
    reasons = "".join(
        f'<li style="margin-bottom:4px">{html.escape(reason)}</li>' for reason in decision.reasons
    )
    reason_block = (
        f'<ul style="margin:0 0 18px;padding-left:20px;font-size:14px;color:{_INK}">{reasons}</ul>'
        if reasons
        else ""
    )
    search = config.search
    meta = (
        f"搜尋條件：{html.escape('、'.join(search.origins))} → {html.escape(search.destination)}"
        f" · {search.window_start.isoformat()} ~ {search.window_end.isoformat()} 之間"
        f" {search.min_nights}–{search.max_nights} 夜"
        f" · {html.escape(search.passengers.describe())}"
        f" · {html.escape(search.cabin)} · {html.escape(search.currency)}"
    )
    return f"""<div style="background:{_BG};padding:24px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Noto Sans TC',Helvetica,Arial,sans-serif;color:{_INK}">
  <div style="max-width:860px;margin:0 auto">
    <div style="font-size:18px;font-weight:700;margin-bottom:16px">台北 → 富國島 機票監控</div>
    {reason_block}
    {_hero(decision, config)}
    {_table(decision, config)}
    {_failures(decision.failures)}
    <div style="font-size:12px;color:{_MUTED};line-height:1.6">
      {meta}<br>
      這是第 {run_count} 次檢查。「全團估算」在 trip.com 只提供每人票價時，以每人票價 × 佔位人數推算，僅供比價，實際金額請於 trip.com 結帳頁確認。<br>
      兒童票與行李、稅金規則依各航空公司而異，出票前請再確認。
    </div>
  </div>
</div>"""


# -- plain text -------------------------------------------------------------


def text_body(decision: Decision, config: Config, *, run_count: int = 0) -> str:
    lines = [f"台北 → 富國島 機票監控 — {decision.label}", ""]
    lines += [f"- {reason}" for reason in decision.reasons]
    if decision.cheapest is not None:
        offer = decision.cheapest
        lines += [
            "",
            f"最便宜：{money(decision.cheapest_total, offer.currency)}（全團估算，{config.search.passengers.describe()}）",
            f"trip.com 顯示：{offer.describe_price()}",
            f"{airport_label(offer.origin)} → {airport_label(offer.destination)} · {trip_label(offer)}",
        ]
        for label, leg in (("去程", offer.outbound), ("回程", offer.inbound)):
            if leg is not None:
                lines.append(f"  {label}：{leg.describe()}")
        if offer.deep_link:
            lines += ["", f"訂票連結：{offer.deep_link}"]

    if decision.changes:
        lines += ["", "所有組合："]
        for change in decision.changes:
            lines.append(
                f"  {trip_label(change.offer):<22} {change.offer.origin}  "
                f"{money(change.total, config.search.currency):>14}  "
                f"{delta_text(change, config.search.currency)}"
            )

    if decision.failures:
        lines += ["", f"未取得報價（{len(decision.failures)}）："]
        lines += [
            f"  {result.query.describe()} — {result.error or '沒有結果'}"
            for result in decision.failures
        ]

    lines += ["", f"這是第 {run_count} 次檢查。"]
    return "\n".join(lines)


def console_summary(decision: Decision, config: Config, *, run_count: int = 0) -> str:
    return text_body(decision, config, run_count=run_count)
