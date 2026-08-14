"""После оплаты: один раз отправить демо-отчёт на email заказа."""

from __future__ import annotations

import html
import logging
from typing import Any

from django.conf import settings
from django.utils import timezone

from core.models import NatalChart, Order
from core.services.mailer import MailerError, send_email

logger = logging.getLogger(__name__)


class FulfillmentError(Exception):
    pass


def deliver_paid_order(order: Order, *, force: bool = False, allow_unpaid_demo: bool = False) -> bool:
    """
    Отправить демо-отчёт. Повтор с тем же заказом не шлёт второе письмо,
    пока не передан force=True.
    """
    unpaid_ok = allow_unpaid_demo and bool(getattr(settings, "PRODAMUS_DEMO_MODE", False))
    if order.status != Order.Status.PAID and not force and not unpaid_ok:
        raise FulfillmentError("Заказ ещё не оплачен.")
    if order.fulfilled_at and not force:
        return False
    to = (order.customer_email or "").strip()
    if not to:
        raise FulfillmentError("У заказа нет email.")

    name = _customer_name(order)
    insight = _insight_for(order)
    subject = "Демо-версия астрологического отчёта — Cosmirror"
    text = _plain_body(name=name, insight=insight, order=order)
    html_body = _html_body(name=name, insight=insight, order=order)
    try:
        send_email(to=to, subject=subject, text=text, html=html_body)
    except MailerError as exc:
        order.fulfillment_error = str(exc)
        order.save(update_fields=["fulfillment_error", "updated_at"])
        raise FulfillmentError(str(exc)) from exc

    order.fulfilled_at = timezone.now()
    order.fulfillment_error = ""
    order.save(update_fields=["fulfilled_at", "fulfillment_error", "updated_at"])
    logger.info("Demo report sent for order %s to %s", order.public_id, to)
    return True


def mark_paid_and_deliver(order: Order, *, force: bool = False) -> bool:
    if order.status != Order.Status.PAID:
        order.status = Order.Status.PAID
        order.paid_at = order.paid_at or timezone.now()
        order.last_error = ""
        order.save(update_fields=["status", "paid_at", "last_error", "updated_at"])
    return deliver_paid_order(order, force=force)


def _customer_name(order: Order) -> str:
    lead = order.waitlist_lead
    if lead and (lead.name or "").strip():
        return lead.name.strip()
    session = order.session
    if session and session.waitlist_lead and (session.waitlist_lead.name or "").strip():
        return session.waitlist_lead.name.strip()
    return ""


def _insight_for(order: Order) -> dict[str, Any]:
    chart = NatalChart.objects.filter(session=order.session).first()
    if not chart or not isinstance(chart.chart_data, dict):
        return {}
    insight = chart.chart_data.get("insight")
    return insight if isinstance(insight, dict) else {}


def _plain_body(*, name: str, insight: dict[str, Any], order: Order) -> str:
    hello = f"Привет, {name}." if name else "Привет."
    opening = _opening_text(insight)
    body = str(insight.get("body") or "").strip()
    blocks = _section_texts(insight)
    parts = [
        hello,
        "",
        "Это демо-версия персонального астрологического отчёта Cosmirror — короткий срез того, что уже собрали по твоим ответам.",
        "",
    ]
    if opening:
        parts.extend([opening, ""])
    if body:
        parts.extend([body, ""])
    for title, text in blocks:
        parts.extend([title, text, ""])
    parts.extend(
        [
            "Полный отчёт будет глубже: паттерны, циклы и опора для выбора.",
            f"Заказ {str(order.public_id)[:8]}.",
            "",
            "Cosmirror",
            "https://cosmirror.ru",
        ]
    )
    return "\n".join(parts)


def _html_body(*, name: str, insight: dict[str, Any], order: Order) -> str:
    hello = f"Привет, {html.escape(name)}." if name else "Привет."
    opening = html.escape(_opening_text(insight))
    body = html.escape(str(insight.get("body") or "").strip())
    sections = ""
    for title, text in _section_texts(insight):
        sections += (
            f"<h2 style=\"margin:28px 0 8px;font-size:13px;letter-spacing:.16em;"
            f"text-transform:uppercase;color:#F6E7A1;font-weight:500;\">{html.escape(title)}</h2>"
            f"<p style=\"margin:0;line-height:1.6;color:rgba(255,255,255,.82);\">{html.escape(text)}</p>"
        )
    opening_html = (
        f"<p style=\"margin:0 0 16px;line-height:1.6;color:#fff;\">{opening}</p>" if opening else ""
    )
    body_html = (
        f"<p style=\"margin:0 0 8px;line-height:1.6;color:rgba(255,255,255,.82);\">{body}</p>"
        if body
        else ""
    )
    return f"""<!DOCTYPE html>
<html><body style="margin:0;background:#050d4a;color:#fff;font-family:Georgia,'Times New Roman',serif;">
  <div style="max-width:560px;margin:0 auto;padding:40px 24px 48px;">
    <p style="margin:0 0 28px;font-size:18px;letter-spacing:.04em;">Cosmirror</p>
    <p style="margin:0 0 8px;font-size:13px;letter-spacing:.18em;text-transform:uppercase;color:#F6E7A1;">
      Демо-версия отчёта
    </p>
    <h1 style="margin:0 0 24px;font-size:28px;font-weight:400;line-height:1.25;">
      Персональный астрологический отчёт
    </h1>
    <p style="margin:0 0 16px;line-height:1.6;">{hello}</p>
    <p style="margin:0 0 20px;line-height:1.6;color:rgba(255,255,255,.82);">
      Это короткий срез того, что уже собрали по твоим ответам. Не фискальный чек Prodamus —
      письмо от Cosmirror после оплаты.
    </p>
    {opening_html}{body_html}{sections}
    <p style="margin:32px 0 0;line-height:1.6;color:rgba(255,255,255,.55);font-size:14px;">
      Полный отчёт будет глубже: паттерны, циклы и опора для выбора.<br>
      Заказ {html.escape(str(order.public_id)[:8])}.
    </p>
    <p style="margin:24px 0 0;"><a href="https://cosmirror.ru" style="color:#F6E7A1;">cosmirror.ru</a></p>
  </div>
</body></html>"""


def _opening_text(insight: dict[str, Any]) -> str:
    opening = insight.get("opening")
    if not isinstance(opening, dict):
        return ""
    bridge = str(opening.get("bridge") or "").strip()
    observation = str(opening.get("insight") or "").strip()
    return " ".join(part for part in (bridge, observation) if part)


def _section_texts(insight: dict[str, Any]) -> list[tuple[str, str]]:
    items: list[tuple[str, str]] = []
    for key in ("influences", "cycles", "base"):
        rows = insight.get(key)
        if not isinstance(rows, list):
            continue
        for row in rows[:2]:
            if not isinstance(row, dict):
                continue
            title = str(row.get("title") or "").strip()
            text = str(row.get("text") or "").strip()
            if title and text:
                items.append((title, text))
        if items:
            break
    return items[:3]
