"""После оплаты: отчёт на сайте и PDF в письме."""

from __future__ import annotations

import html
import logging
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from core.models import Order
from core.services.mailer import MailerError, send_email
from core.services.pdf_report import render_report_pdf
from core.services.report import build_paid_report, report_page_url

logger = logging.getLogger(__name__)

_EYE_CID = "cosmirror-eye"
_EYE_PATH = Path(__file__).resolve().parent.parent / "assets" / "email_eye.png"
_BODY_LEAD = (
    "Твой персональный астрологический отчёт готов, ты можешь скачать PDF "
    "из вложения или открыть интерактивную версию "
)
_BODY_LINK_LABEL = "на сайте Cosmirror"


class FulfillmentError(Exception):
    pass


def deliver_paid_order(order: Order, *, force: bool = False, allow_unpaid_demo: bool = False) -> bool:
    """
    Собрать PDF и отправить письмо. Если LLM ещё не готов, kickoff
    стартует job, а письмо уходит после него — чтобы PDF был с текстами модели.
    Отчёт на сайте не зависит от почты: если адрес пустой или письмо не ушло,
    заказ всё равно оплачен.
    """
    unpaid_ok = allow_unpaid_demo and bool(getattr(settings, "PRODAMUS_DEMO_MODE", False))
    if order.status != Order.Status.PAID and not force and not unpaid_ok:
        raise FulfillmentError("Заказ ещё не оплачен.")
    if order.fulfilled_at and not force:
        return False

    from core.services.report_jobs import (
        kickoff_paid_report_for_order,
        should_defer_fulfillment_email,
    )

    kickoff_paid_report_for_order(order, retry_failed=True)
    if not force and should_defer_fulfillment_email(order):
        return False

    return email_paid_report(order, force=force, allow_unpaid_demo=allow_unpaid_demo)


def email_paid_report(order: Order, *, force: bool = False, allow_unpaid_demo: bool = False) -> bool:
    """Собрать текущий отчёт в PDF и отправить письмо. Без kickoff LLM."""
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
            inline_images=_inline_images(),
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
    session = order.session
    if session is not None:
        from core.services.personalize import quiz_from_session

        quiz_name = str(quiz_from_session(session).get("name") or "").strip()
        if quiz_name:
            return quiz_name
    lead = order.waitlist_lead
    if lead and (lead.name or "").strip():
        return lead.name.strip()
    if session and session.waitlist_lead and (session.waitlist_lead.name or "").strip():
        return session.waitlist_lead.name.strip()
    return ""


def _greeting(name: str) -> str:
    return f"Привет, {name}" if name else "Привет"


def _plain_body(*, name: str, page_url: str) -> str:
    return "\n".join(
        [
            _greeting(name),
            "",
            f"{_BODY_LEAD}{_BODY_LINK_LABEL}:",
            page_url,
            "",
            "Открыть отчёт:",
            page_url,
        ]
    )


def _inline_images() -> list[tuple[str, str, bytes, str]]:
    if not _EYE_PATH.is_file():
        return []
    return [(_EYE_CID, "email_eye.png", _EYE_PATH.read_bytes(), "image/png")]


def _html_body(*, name: str, page_url: str) -> str:
    hello = html.escape(_greeting(name))
    url = html.escape(page_url, quote=True)
    lead = html.escape(_BODY_LEAD)
    link_label = html.escape(_BODY_LINK_LABEL)
    navy = "#050d4a"
    gold = "#F6E7A1"
    ink = "#0a1a3a"
    display = "'Playfair Display', Georgia, 'Times New Roman', serif"
    grotesk = "Onest, Arial, Helvetica, sans-serif"
    return f"""<!DOCTYPE html>
<html lang="ru" xmlns="http://www.w3.org/1999/xhtml">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light only">
  <meta name="supported-color-schemes" content="light">
  <title>Cosmirror</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Onest:wght@400;500&family=Playfair+Display:ital@1&display=swap" rel="stylesheet">
  <style type="text/css">
    :root {{ color-scheme: light only; }}
    body, table, td, a {{ -webkit-text-size-adjust: 100%; -ms-text-size-adjust: 100%; }}
    body {{ margin: 0; padding: 0; background-color: {navy} !important; }}
    .email-bg {{ background-color: {navy} !important; }}
    .wordmark {{ font-family: {display}; font-style: italic; color: #ffffff !important; }}
    .body-text {{ font-family: {grotesk}; color: #ffffff !important; }}
    .muted {{ font-family: {grotesk}; color: #d8d4cc !important; }}
    .site-link {{ color: {gold} !important; text-decoration: underline; font-family: {display}; font-style: italic; }}
    .btn-cell {{ background-color: {gold} !important; }}
    .btn-text {{ color: {ink} !important; text-decoration: none; }}
    @media (prefers-color-scheme: dark) {{
      body, .email-bg, .email-card {{ background-color: {navy} !important; }}
      .wordmark, .body-text {{ color: #ffffff !important; }}
      .muted {{ color: #d8d4cc !important; }}
      .site-link {{ color: {gold} !important; }}
      .btn-cell {{ background-color: {gold} !important; }}
      .btn-text {{ color: {ink} !important; }}
    }}
  </style>
</head>
<body bgcolor="{navy}" style="margin:0;padding:0;background-color:{navy};">
  <div style="display:none;max-height:0;overflow:hidden;opacity:0;">
    Персональный астрологический отчёт Cosmirror готов
  </div>
  <table role="presentation" class="email-bg" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="{navy}" style="background-color:{navy};">
    <tr>
      <td align="center" bgcolor="{navy}" class="email-bg" style="padding:48px 24px 56px;background-color:{navy};">
        <table role="presentation" class="email-card" width="560" cellpadding="0" cellspacing="0" border="0" bgcolor="{navy}" style="max-width:560px;width:100%;background-color:{navy};">
          <tr>
            <td align="center" bgcolor="{navy}" style="padding:0 0 10px;background-color:{navy};">
              <img src="cid:{_EYE_CID}" width="88" alt="" style="display:block;width:88px;height:auto;border:0;outline:none;">
            </td>
          </tr>
          <tr>
            <td align="center" bgcolor="{navy}" class="wordmark" style="padding:0 0 40px;background-color:{navy};font-family:{display};font-style:italic;font-size:28px;line-height:1.2;color:#ffffff;letter-spacing:-0.02em;">
              Cosmirror
            </td>
          </tr>
          <tr>
            <td bgcolor="{navy}" class="body-text" style="padding:0 0 18px;background-color:{navy};font-family:{grotesk};font-size:18px;line-height:1.5;color:#ffffff;">
              {hello}
            </td>
          </tr>
          <tr>
            <td bgcolor="{navy}" class="muted" style="padding:0 0 32px;background-color:{navy};font-family:{grotesk};font-size:16px;line-height:1.65;color:#d8d4cc;">
              {lead}<a href="{url}" class="site-link" style="color:{gold};text-decoration:underline;font-family:{display};font-style:italic;">{link_label}</a>
            </td>
          </tr>
          <tr>
            <td align="center" bgcolor="{navy}" style="padding:0;background-color:{navy};">
              <table role="presentation" cellpadding="0" cellspacing="0" border="0" align="center">
                <tr>
                  <td align="center" bgcolor="{gold}" class="btn-cell" style="background-color:{gold};border-radius:999px;">
                    <a href="{url}" class="btn-text" style="display:inline-block;padding:14px 40px;font-family:{grotesk};font-size:17px;font-weight:500;line-height:1;color:{ink};text-decoration:none;border-radius:999px;">
                      Открыть отчёт
                    </a>
                  </td>
                </tr>
              </table>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""
