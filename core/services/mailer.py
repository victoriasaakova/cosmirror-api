"""Отправка писем: Resend API или Django EMAIL_BACKEND."""

from __future__ import annotations

import base64
import json
import logging
import urllib.error
import urllib.request

from django.conf import settings
from django.core.mail import EmailMultiAlternatives

logger = logging.getLogger(__name__)


class MailerError(Exception):
    pass


def from_address() -> str:
    return (getattr(settings, "EMAIL_FROM", "") or "Cosmirror <hello@cosmirror.ru>").strip()


def is_configured() -> bool:
    if (getattr(settings, "RESEND_API_KEY", "") or "").strip():
        return True
    if (getattr(settings, "EMAIL_HOST_PASSWORD", "") or "").strip():
        return True
    backend = (getattr(settings, "EMAIL_BACKEND", "") or "")
    return "locmem" in backend


def bcc_address() -> str:
    return (getattr(settings, "EMAIL_BCC", "") or "").strip()


def send_email(
    *,
    to: str,
    subject: str,
    text: str,
    html: str,
    attachments: list[tuple[str, bytes, str]] | None = None,
    inline_images: list[tuple[str, str, bytes, str]] | None = None,
) -> None:
    to = (to or "").strip()
    if not to:
        raise MailerError("Нет адреса получателя.")
    if not is_configured():
        raise MailerError(
            "Почта Cosmirror не настроена: нужен пароль ящика hello@cosmirror.ru (EMAIL_HOST_PASSWORD)."
        )
    api_key = (getattr(settings, "RESEND_API_KEY", "") or "").strip()
    if api_key:
        _send_resend(
            api_key,
            to=to,
            subject=subject,
            text=text,
            html=html,
            attachments=attachments,
            inline_images=inline_images,
        )
        return
    _send_django(
        to=to,
        subject=subject,
        text=text,
        html=html,
        attachments=attachments,
        inline_images=inline_images,
    )


def _send_resend(
    api_key: str,
    *,
    to: str,
    subject: str,
    text: str,
    html: str,
    attachments: list[tuple[str, bytes, str]] | None = None,
    inline_images: list[tuple[str, str, bytes, str]] | None = None,
) -> None:
    bcc = bcc_address()
    payload_data: dict = {
        "from": from_address(),
        "to": [to],
        "subject": subject,
        "text": text,
        "html": html,
    }
    if bcc and bcc.lower() != to.lower():
        payload_data["bcc"] = [bcc]
    if attachments:
        payload_data["attachments"] = [
            {
                "filename": name,
                "content": base64.b64encode(content).decode("ascii"),
                "content_type": mime,
            }
            for name, content, mime in attachments
        ]
    else:
        payload_data["attachments"] = []
    for cid, name, content, mime in inline_images or []:
        payload_data["attachments"].append(
            {
                "filename": name,
                "content": base64.b64encode(content).decode("ascii"),
                "content_type": mime,
                "content_id": cid,
            }
        )
    if not payload_data["attachments"]:
        del payload_data["attachments"]
    payload = json.dumps(payload_data).encode("utf-8")
    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise MailerError(f"Resend HTTP {exc.code}: {raw[:400]}") from exc
    except urllib.error.URLError as exc:
        raise MailerError(f"Не удалось связаться с Resend: {exc}") from exc
    logger.info("Resend accepted email to %s: %s", to, raw[:200])


def _send_django(
    *,
    to: str,
    subject: str,
    text: str,
    html: str,
    attachments: list[tuple[str, bytes, str]] | None = None,
    inline_images: list[tuple[str, str, bytes, str]] | None = None,
) -> None:
    from email.mime.image import MIMEImage

    bcc = bcc_address()
    message = EmailMultiAlternatives(
        subject=subject,
        body=text,
        from_email=from_address(),
        to=[to],
        bcc=[bcc] if bcc and bcc.lower() != to.lower() else [],
    )
    if html:
        message.attach_alternative(html, "text/html")
    if inline_images:
        message.mixed_subtype = "related"
        for cid, name, content, mime in inline_images:
            subtype = (mime.split("/")[-1] if "/" in mime else "png").lower()
            image = MIMEImage(content, _subtype=subtype)
            image.add_header("Content-ID", f"<{cid}>")
            image.add_header("Content-Disposition", "inline", filename=name)
            message.attach(image)
    for name, content, mime in attachments or []:
        message.attach(name, content, mime)
    sent = message.send(fail_silently=False)
    if not sent:
        raise MailerError("Django mail backend не отправил письмо.")
