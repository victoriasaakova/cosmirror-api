"""После оплаты: отчёт на сайте и PDF в письме."""

from __future__ import annotations

import html
import logging

from django.conf import settings
from django.utils import timezone

from core.models import Order
from core.services.mailer import MailerError, send_email
from core.services.pdf_report import render_report_pdf
from core.services.report import build_paid_report, report_page_url

logger = logging.getLogger(__name__)


class FulfillmentError(Exception):
    pass


def deliver_paid_order(order: Order, *, force: bool = False, allow_unpaid_demo: bool = False) -> bool:
    """
    Собрать PDF и отправить письмо. Отчёт на сайте не зависит от почты:
    если адрес пустой или письмо не ушло, заказ всё равно оплачен.
    """
    unpaid_ok = allow_unpaid_demo and bool(getattr(settings, "PRODAMUS_DEMO_MODE", False))
    if order.status != Order.Status.PAID and not force and not unpaid_ok:
        raise FulfillmentError("Заказ ещё не оплачен.")
    if order.fulfilled_at and not force:
        return False

    report = build_paid_report(order)
    pdf = render_report_pdf(report)
    page_url = report_page_url(order)
    to = (order.customer_email or "").strip()
    if not to:
        order.fulfillment_error = "Нет email — отчёт доступен на странице после оплаты."
        order.save(update_fields=["fulfillment_error", "updated_at"])
        raise FulfillmentError(order.fulfillment_error)

    name = _customer_name(order)
    subject = "Персональный астрологический отчёт — Cosmirror"
    text = _plain_body(name=name, page_url=page_url)
    html_body = _html_body(name=name, page_url=page_url)
    try:
        send_email(
            to=to,
            subject=subject,
            text=text,
            html=html_body,
            attachments=[("cosmirror-report.pdf", pdf, "application/pdf")],
        )
    except MailerError as exc:
        order.fulfillment_error = str(exc)
        order.save(update_fields=["fulfillment_error", "updated_at"])
        raise FulfillmentError(str(exc)) from exc

    order.fulfilled_at = timezone.now()
    order.fulfillment_error = ""
    order.save(update_fields=["fulfilled_at", "fulfillment_error", "updated_at"])
    logger.info("Report emailed for order %s to %s", order.public_id, to)
    return True


def mark_paid_and_deliver(order: Order, *, force: bool = False) -> bool:
    if order.status != Order.Status.PAID:
        order.status = Order.Status.PAID
        order.paid_at = order.paid_at or timezone.now()
        order.last_error = ""
        order.save(update_fields=["status", "paid_at", "last_error", "updated_at"])
    return deliver_paid_order(order, force=force)


def update_order_email_and_resend(order: Order, email: str) -> Order:
    address = (email or "").strip().lower()
    if "@" not in address or "." not in address.split("@")[-1]:
        raise FulfillmentError("Укажи нормальный email.")
    if order.status != Order.Status.PAID:
        raise FulfillmentError("Сначала нужна успешная оплата.")
    order.customer_email = address
    order.save(update_fields=["customer_email", "updated_at"])
    deliver_paid_order(order, force=True)
    return order


def _customer_name(order: Order) -> str:
    lead = order.waitlist_lead
    if lead and (lead.name or "").strip():
        return lead.name.strip()
    session = order.session
    if session and session.waitlist_lead and (session.waitlist_lead.name or "").strip():
        return session.waitlist_lead.name.strip()
    return ""


def _plain_body(*, name: str, page_url: str) -> str:
    hello = f"Привет, {name}." if name else "Привет."
    return "\n".join(
        [
            hello,
            "",
            "Персональный астрологический отчёт Cosmirror во вложении — PDF, его можно скачать и сохранить.",
            "Тот же отчёт открыт на сайте:",
            page_url,
            "",
            "Если письмо пришло не на ту почту, открой ссылку и укажи другой адрес — отправим ещё раз.",
            "",
            "Cosmirror",
            "https://cosmirror.ru",
        ]
    )


def _html_body(*, name: str, page_url: str) -> str:
    hello = f"Привет, {html.escape(name)}." if name else "Привет."
    url = html.escape(page_url)
    return f"""<!DOCTYPE html>
<html><body style="margin:0;background:#050d4a;color:#fff;font-family:Georgia,'Times New Roman',serif;">
  <div style="max-width:560px;margin:0 auto;padding:40px 24px 48px;">
    <p style="margin:0 0 28px;font-size:18px;letter-spacing:.04em;">Cosmirror</p>
    <h1 style="margin:0 0 16px;font-size:26px;font-weight:400;line-height:1.3;">
      Персональный астрологический отчёт
    </h1>
    <p style="margin:0 0 16px;line-height:1.6;">{hello}</p>
    <p style="margin:0 0 16px;line-height:1.6;color:rgba(255,255,255,.82);">
      PDF во вложении — его можно скачать. Тот же отчёт открыт на сайте.
    </p>
    <p style="margin:0 0 24px;">
      <a href="{url}" style="color:#F6E7A1;">Открыть отчёт на Cosmirror</a>
    </p>
    <p style="margin:0;line-height:1.6;color:rgba(255,255,255,.55);font-size:14px;">
      Если это не та почта, открой ссылку и укажи другой адрес — отправим ещё раз.
    </p>
  </div>
</body></html>"""
