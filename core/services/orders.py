"""Создание заказа у нас и платёжной ссылки в Prodamus, с Idempotency-Key."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import urllib.parse
import uuid
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from core.models import OnboardingSession, Order, WaitlistLead
from core.services.prodamus import (
    ProdamusError,
    create_payment_link,
    is_configured,
    notification_url,
    our_order_id,
    payment_status_of,
    prodamus_order_id,
)

logger = logging.getLogger(__name__)

_IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9._~-]{8,128}$")
_TERMINAL = {
    Order.Status.PAID,
    Order.Status.CANCELED,
    Order.Status.DENIED,
}
# Повторный клик «оплатить» через столько секунд выпускает новую ссылку Prodamus.
_REISSUE_AFTER = timedelta(seconds=30)


class OrderError(Exception):
    def __init__(self, detail: str, status: int = 400):
        super().__init__(detail)
        self.detail = detail
        self.status = status


def validate_idempotency_key(raw: str | None) -> str:
    key = (raw or "").strip()
    if not key:
        raise OrderError("Заголовок Idempotency-Key обязателен.", 400)
    if not _IDEMPOTENCY_RE.fullmatch(key):
        raise OrderError(
            "Idempotency-Key: 8–128 символов (латиница, цифры, . _ ~ -).",
            400,
        )
    return key


def _product() -> tuple[str, str, Decimal]:
    sku = (getattr(settings, "COSMIRROR_PRODUCT_SKU", "") or "personal_report").strip()
    name = (
        getattr(settings, "COSMIRROR_PRODUCT_NAME", "")
        or "Персональный астрологический отчёт"
    ).strip()
    try:
        price = Decimal(str(getattr(settings, "COSMIRROR_PRODUCT_PRICE", "777")))
    except (InvalidOperation, TypeError) as exc:
        raise OrderError("Некорректная цена товара в настройках.", 500) from exc
    if price <= 0:
        raise OrderError("Цена товара должна быть больше нуля.", 500)
    return sku, name, price.quantize(Decimal("0.01"))


def _paid_content(product_name: str, price: Decimal) -> str:
    override = (getattr(settings, "COSMIRROR_PRODUCT_PAID_CONTENT", "") or "").strip()
    if override:
        return override[:4096]
    return (
        f"{product_name} Cosmirror за {price} ₽. "
        "Это персональный астрологический отчёт. "
        "После оплаты отчёт откроется на сайте и придёт письмом с PDF. "
        "https://cosmirror.ru"
    )[:4096]


def _request_hash(session_token: str, sku: str, promo_code: str = "") -> str:
    canonical = json.dumps(
        {
            "session": str(session_token),
            "sku": sku,
            "promo": (promo_code or "").strip().lower(),
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _discount_for_promo(code: str) -> Decimal | None:
    raw = (code or "").strip().lower()
    if not raw:
        return None
    mapping = getattr(settings, "PRODAMUS_PROMO_DISCOUNTS", "") or ""
    for part in mapping.split(","):
        part = part.strip()
        if ":" not in part:
            continue
        name, value = part.split(":", 1)
        if name.strip().lower() != raw:
            continue
        try:
            discount = Decimal(value.strip())
        except (InvalidOperation, TypeError) as exc:
            raise OrderError("Некорректная скидка промокода в настройках.", 500) from exc
        if discount <= 0:
            raise OrderError("Скидка промокода должна быть больше нуля.", 500)
        return discount.quantize(Decimal("0.01"))
    raise OrderError("Такой промокод не найден.", 400)


def _contacts(session: OnboardingSession) -> tuple[str, str, str]:
    """Email/telegram с последнего шага контактов важнее старого waitlist-лида."""
    lead: WaitlistLead | None = session.waitlist_lead
    waitlist_answer = (
        session.answers.filter(step__step_type="waitlist")
        .order_by("-updated_at")
        .first()
    )
    payload = waitlist_answer.payload if waitlist_answer else {}
    if not isinstance(payload, dict):
        payload = {}
    email = str(payload.get("email") or "").strip()
    phone = str(payload.get("phone") or "").strip()
    telegram = str(payload.get("telegram") or "").strip()
    if lead:
        email = email or (lead.email or "")
        phone = phone or (lead.phone or "")
        telegram = telegram or (lead.telegram or "")
    return email.strip().lower(), phone.strip(), telegram.strip()


def _public_frontend_base() -> str:
    """Prodamus редиректит в браузере. http://localhost он часто поднимает до https://localhost — порт 443 закрыт."""
    front = (getattr(settings, "FRONTEND_URL", "") or "").rstrip("/")
    if front.startswith("https://"):
        return front
    return ""


def _success_url(order: Order) -> str:
    base = _public_frontend_base()
    if not base:
        return ""
    return f"{base}/report/?order={order.public_id}"


def _return_url(order: Order | None = None) -> str:
    base = _public_frontend_base()
    if not base:
        return ""
    if order is not None:
        return f"{base}/pay/failed/?order={order.public_id}"
    return f"{base}/pay/failed/"


def _payment_url_is_stale(url: str) -> bool:
    if not url:
        return True
    decoded = urllib.parse.unquote(url).lower()
    if "localhost" in decoded or "127.0.0.1" in decoded:
        return True
    if "paylink=1" in decoded:
        return True
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path.strip("/")
    # Короткие https://payform.ru/xxxxx/ пропускают форму с промокодом.
    if host.endswith("payform.ru") and path and "do=pay" not in decoded:
        return True
    return False


def refresh_payment_link_if_stale(order: Order) -> Order:
    if order.status in _TERMINAL:
        return order
    return _ensure_payment_link(order)


def _ensure_payment_link(order: Order, *, discount_value: Decimal | None = None) -> Order:
    sku, name, price = _product()
    name_stale = order.product_name != name
    if order.payment_url and not _payment_url_is_stale(order.payment_url) and not name_stale:
        return order
    if name_stale:
        order.product_name = name
    if not is_configured():
        order.status = Order.Status.FAILED
        order.last_error = "Prodamus не настроен (PRODAMUS_FORM_URL / PRODAMUS_SECRET_KEY)."
        order.save(update_fields=["status", "last_error", "updated_at"])
        raise OrderError(
            "Оплата временно недоступна: не заданы ключи Prodamus.",
            503,
        )
    extra_parts = []
    extra_parts.append(
        "Персональный астрологический отчёт. Отчёт отправим письмом после оплаты."
    )
    try:
        url = create_payment_link(
            order_id=str(order.public_id),
            product_name=order.product_name,
            product_price=order.amount,
            product_sku=order.product_sku,
            customer_email=order.customer_email,
            customer_phone="",
            customer_extra=" · ".join(extra_parts),
            paid_content=_paid_content(order.product_name, order.amount),
            url_success=_success_url(order),
            url_return=_return_url(order),
            url_notification=notification_url(),
            discount_value=discount_value or "",
        )
    except ProdamusError as exc:
        order.status = Order.Status.FAILED
        order.last_error = str(exc)
        order.save(update_fields=["status", "last_error", "updated_at"])
        logger.exception("Prodamus create_payment_link failed for %s", order.public_id)
        raise OrderError("Не удалось создать платёжную ссылку в Prodamus.", 502) from exc

    order.payment_url = url
    order.status = Order.Status.AWAITING_PAYMENT
    order.last_error = ""
    order.save(
        update_fields=["product_name", "payment_url", "status", "last_error", "updated_at"]
    )
    return order


def _should_reissue_payment_link(order: Order, *, created: bool) -> bool:
    if created or order.status != Order.Status.AWAITING_PAYMENT or not order.payment_url:
        return False
    return (timezone.now() - order.updated_at) > _REISSUE_AFTER


def _retire_unpaid_order(order: Order) -> None:
    order.idempotency_key = f"retired-{order.public_id}"[:128]
    order.status = Order.Status.CANCELED
    order.last_error = "Ссылка перевыпущена после повторной попытки оплаты."
    order.save(update_fields=["idempotency_key", "status", "last_error", "updated_at"])


def create_or_resume_order(
    *,
    session: OnboardingSession,
    idempotency_key: str,
    promo_code: str = "",
) -> tuple[Order, bool]:
    """
    Создать заказ и ссылку в Prodamus.
    Повтор с тем же Idempotency-Key и тем же телом возвращает тот же заказ.
    Возвращает (order, created).
    """
    sku, name, price = _product()
    promo = (promo_code or "").strip()
    discount = _discount_for_promo(promo) if promo else None
    request_hash = _request_hash(str(session.token), sku, promo)
    email, phone, telegram = _contacts(session)
    if not email:
        raise OrderError("Сначала укажи email на шаге контактов.", 400)

    paid = (
        Order.objects.filter(
            session=session,
            product_sku=sku,
            status=Order.Status.PAID,
        )
        .order_by("-paid_at", "-created_at")
        .first()
    )
    if paid:
        return paid, False

    try:
        with transaction.atomic():
            order = Order.objects.create(
                idempotency_key=idempotency_key,
                idempotency_request_hash=request_hash,
                session=session,
                waitlist_lead=session.waitlist_lead,
                user=session.user,
                customer_email=email,
                customer_phone=phone,
                customer_telegram=telegram,
                product_sku=sku,
                product_name=name,
                amount=price,
                currency="rub",
                status=Order.Status.PENDING,
            )
        created = True
    except IntegrityError:
        existing = Order.objects.filter(idempotency_key=idempotency_key).first()
        if existing is None:
            raise OrderError("Конфликт идемпотентности, повтори запрос.", 409)
        if existing.idempotency_request_hash != request_hash:
            raise OrderError(
                "Этот Idempotency-Key уже использован для другого запроса.",
                409,
            )
        order = existing
        created = False

    if _should_reissue_payment_link(order, created=created):
        _retire_unpaid_order(order)
        return create_or_resume_order(
            session=session,
            idempotency_key=idempotency_key,
            promo_code=promo,
        )

    if order.status in _TERMINAL:
        return order, created

    with transaction.atomic():
        locked = Order.objects.select_for_update().get(pk=order.pk)
        if locked.status in _TERMINAL:
            return locked, created
        locked = _sync_order_contacts(locked, email=email, phone=phone, telegram=telegram)
        order = _ensure_payment_link(locked, discount_value=discount)
    _send_demo_report_if_needed(order)
    return order, created


def _sync_order_contacts(order: Order, *, email: str, phone: str, telegram: str) -> Order:
    """Если на онбординге сменили почту — не тащим в Prodamus старый адрес с лида."""
    new_email = (email or "").strip().lower()
    changed = False
    if new_email and (order.customer_email or "").strip().lower() != new_email:
        order.customer_email = new_email
        changed = True
    if phone and order.customer_phone != phone:
        order.customer_phone = phone
        changed = True
    if telegram and order.customer_telegram != telegram:
        order.customer_telegram = telegram
        changed = True
    if changed:
        order.payment_url = ""
        order.save(
            update_fields=[
                "customer_email",
                "customer_phone",
                "customer_telegram",
                "payment_url",
                "updated_at",
            ]
        )
    return order


def _send_demo_report_if_needed(order: Order) -> None:
    """
    В демо webhook с Prodamus на localhost не доходит.
    После нажатия «оплатить» сразу шлём письмо с hello@cosmirror.ru.
    """
    if not getattr(settings, "PRODAMUS_DEMO_MODE", False):
        return
    from core.services.fulfillment import FulfillmentError, deliver_paid_order

    try:
        deliver_paid_order(order, allow_unpaid_demo=True)
    except FulfillmentError:
        logger.exception("Demo report was not sent for %s", order.public_id)


def apply_prodamus_webhook(payload: dict) -> Order | None:
    """
    Идемпотентная обработка webhook: повтор success не меняет оплаченный заказ.
    """
    order_ref = our_order_id(payload)
    if not order_ref:
        raise OrderError("В уведомлении нет order_num.", 400)
    try:
        public_id = uuid.UUID(str(order_ref))
    except (ValueError, TypeError) as exc:
        raise OrderError("Некорректный order_num.", 400) from exc

    try:
        order = Order.objects.get(public_id=public_id)
    except Order.DoesNotExist as exc:
        raise OrderError("Заказ не найден.", 404) from exc

    status = payment_status_of(payload)
    prodamus_id = prodamus_order_id(payload)

    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order.pk)
        order.webhook_payload = payload
        if prodamus_id:
            order.prodamus_order_id = prodamus_id

        just_paid = False
        if status == "success":
            if order.status != Order.Status.PAID:
                order.status = Order.Status.PAID
                order.paid_at = timezone.now()
                order.last_error = ""
                just_paid = True
        elif status == "order_canceled":
            if order.status != Order.Status.PAID:
                order.status = Order.Status.CANCELED
        elif status == "order_denied":
            if order.status != Order.Status.PAID:
                order.status = Order.Status.DENIED
        else:
            logger.info(
                "Prodamus webhook unknown status %s for %s",
                status,
                order.public_id,
            )

        order.save(
            update_fields=[
                "webhook_payload",
                "prodamus_order_id",
                "status",
                "paid_at",
                "last_error",
                "updated_at",
            ]
        )
    if just_paid:
        from core.services.fulfillment import FulfillmentError, deliver_paid_order

        try:
            deliver_paid_order(order)
        except FulfillmentError:
            logger.exception("Demo report delivery failed for %s", order.public_id)
    return order
