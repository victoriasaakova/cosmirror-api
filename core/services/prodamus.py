"""
Клиент Prodamus Payform.

Документация:
https://help.prodamus.ru/payform/integracii/rest-api/instrukcii-dlya-samostoyatelnaya-integracii-servisov

Бэкенд — драйвер заказа: подписанный do=pay с товаром и order_id.
Короткая do=link сразу открывает способы оплаты и прячет промокод Prodamus.
Подтверждение — webhook с Sign.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal
from typing import Any, Optional

from django.conf import settings

logger = logging.getLogger(__name__)

_DEMO_SECRET_SUFFIX = "demo"


class ProdamusError(Exception):
    """Ошибка вызова Prodamus или проверки подписи."""


def _to_strings(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _to_strings(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_strings(v) for v in value]
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else ""
    if isinstance(value, Decimal):
        return format(value, "f")
    return str(value)


def dump_for_signature(data: dict) -> str:
    """
    Алгоритм Prodamus:
    значения → строки, ключи по алфавиту (вглубь), JSON, экранировать `/`, HMAC-SHA256.
    """
    prepared = _to_strings(data)
    payload = json.dumps(prepared, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return payload.replace("/", "\\/")


def sign(data: dict, secret: str) -> str:
    body = dump_for_signature(data)
    return hmac.new(
        secret.encode("utf-8"),
        body.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _signatures_match(expected: str, received: str) -> bool:
    if not expected or not received:
        return False
    left = expected.lower()
    right = received.lower()
    if len(left) != len(right):
        return False
    return hmac.compare_digest(left, right)


def verify(data: dict, secret: str, signature: str) -> bool:
    if not isinstance(data, dict) or not secret or not signature:
        return False
    return _signatures_match(sign(data, secret), signature)


def verify_webhook(payload: dict, secret: str, signature: str, *, allow_demo: bool = False) -> bool:
    """
    Вебхук: Sign считается по телу (часто по полю submit).
    Демо-платежи подписываются ключом с суффиксом demo и в бою должны отвергаться.
    """
    candidates: list[dict] = []
    if isinstance(payload, dict):
        candidates.append(payload)
        submit = payload.get("submit")
        if isinstance(submit, dict):
            candidates.insert(0, submit)

    secrets = [secret]
    if allow_demo:
        secrets.append(f"{secret}{_DEMO_SECRET_SUFFIX}")

    for body in candidates:
        for key in secrets:
            if verify(body, key, signature):
                if key.endswith(_DEMO_SECRET_SUFFIX) and key != secret:
                    logger.info("Prodamus webhook verified with demo secret suffix")
                return True
    return False


def flatten_php(data: Any, prefix: str = "") -> list[tuple[str, str]]:
    """PHP http_build_query-стиль: products[0][name]=..."""
    items: list[tuple[str, str]] = []
    if isinstance(data, dict):
        for key, value in data.items():
            path = f"{prefix}[{key}]" if prefix else str(key)
            items.extend(flatten_php(value, path))
        return items
    if isinstance(data, (list, tuple)):
        for index, value in enumerate(data):
            path = f"{prefix}[{index}]"
            items.extend(flatten_php(value, path))
        return items
    items.append((prefix, "" if data is None else str(data)))
    return items


def _form_url() -> str:
    url = (getattr(settings, "PRODAMUS_FORM_URL", "") or "").strip()
    if not url:
        raise ProdamusError("PRODAMUS_FORM_URL не задан")
    return url if url.endswith("/") else f"{url}/"


def _secret() -> str:
    secret = (getattr(settings, "PRODAMUS_SECRET_KEY", "") or "").strip()
    if not secret:
        raise ProdamusError("PRODAMUS_SECRET_KEY не задан")
    return secret


def is_configured() -> bool:
    return bool(
        (getattr(settings, "PRODAMUS_FORM_URL", "") or "").strip()
        and (getattr(settings, "PRODAMUS_SECRET_KEY", "") or "").strip()
    )


def _parse_link_response(raw: str) -> str:
    text = (raw or "").strip().strip('"').strip("'")
    if not text:
        raise ProdamusError("Prodamus вернул пустой ответ")
    if text.startswith("{"):
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ProdamusError(f"Prodamus вернул невалидный JSON: {text[:300]}") from exc
        if not isinstance(data, dict):
            raise ProdamusError(f"Неожиданный JSON от Prodamus: {text[:300]}")
        for key in ("payment_link", "link", "url", "paymentUrl"):
            value = data.get(key)
            if isinstance(value, str) and value.startswith("http"):
                return value.strip()
        raise ProdamusError(f"В JSON Prodamus нет ссылки: {text[:300]}")
    match = re.search(r"https?://[^\s\"'<>]+", text)
    if match:
        return match.group(0).rstrip(".,;)")
    raise ProdamusError(f"Prodamus не вернул ссылку: {text[:300]}")


def notification_url() -> str:
    override = (getattr(settings, "PRODAMUS_NOTIFICATION_URL", "") or "").strip()
    if override:
        return override
    base = (getattr(settings, "PUBLIC_API_URL", "") or "").rstrip("/")
    if not base:
        return ""
    host = base.lower()
    if "127.0.0.1" in host or "localhost" in host:
        return ""
    return f"{base}/api/payments/prodamus/webhook/"


def build_checkout_payload(
    *,
    order_id: str,
    product_name: str,
    product_price: Decimal | str,
    product_sku: str,
    customer_email: str = "",
    customer_phone: str = "",
    customer_extra: str = "",
    paid_content: str = "",
    url_success: str = "",
    url_return: str = "",
    url_notification: str = "",
    discount_value: Decimal | str = "",
    action: str = "pay",
) -> dict[str, Any]:
    """Параметры персональной оплаты: товар, сумма, order_id, возврат на наш сайт."""
    payload: dict[str, Any] = {
        "do": action,
        "order_id": str(order_id),
        "products": [
            {
                "name": product_name,
                "price": format(Decimal(str(product_price)), "f"),
                "quantity": "1",
                "sku": product_sku,
                "type": "service",
            }
        ],
        "currency": "rub",
        "payments_limit": "1",
        "callbackType": "json",
        "npd_income_type": "FROM_INDIVIDUAL",
    }
    if customer_email:
        payload["customer_email"] = customer_email
    if customer_phone:
        payload["customer_phone"] = customer_phone
    if customer_extra:
        payload["customer_extra"] = customer_extra
    if paid_content:
        payload["paid_content"] = paid_content[:4096]
    if url_success:
        payload["urlSuccess"] = url_success
    if url_return:
        payload["urlReturn"] = url_return
    if url_notification:
        payload["urlNotification"] = url_notification
    if discount_value not in ("", None):
        payload["discount_value"] = format(Decimal(str(discount_value)), "f")
    sys_code = (getattr(settings, "PRODAMUS_SYS", "") or "").strip()
    if sys_code:
        payload["sys"] = sys_code
    if getattr(settings, "PRODAMUS_DEMO_MODE", False):
        payload["demo_mode"] = "1"
        # В демо работает только карта РФ. СБП/рассрочка на тестовой форме часто ломают вкладку.
        payload["available_payment_methods"] = "AC"
        payload["installments_disabled"] = "1"
    return payload


def signed_checkout_url(payload: dict[str, Any]) -> str:
    """GET-ссылка на cosmirror.payform.ru с подписью — форма заказа и промокод."""
    secret = _secret()
    signed = dict(payload)
    signed["signature"] = sign(payload, secret)
    query = urllib.parse.urlencode(flatten_php(signed), doseq=True)
    return f"{_form_url()}?{query}"


def _fetch_short_link(payload: dict[str, Any]) -> str:
    """do=link: Prodamus возвращает короткую https://payform.ru/xxxxx/."""
    req = urllib.request.Request(
        signed_checkout_url(payload),
        headers={
            "Accept": "text/plain, application/json, */*",
            "User-Agent": "Cosmirror/1.0",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise ProdamusError(f"Prodamus HTTP {exc.code}: {raw[:300]}") from exc
    except urllib.error.URLError as exc:
        raise ProdamusError(f"Не удалось связаться с Prodamus: {exc}") from exc
    return _parse_link_response(raw)


def create_payment_link(
    *,
    order_id: str,
    product_name: str,
    product_price: Decimal | str,
    product_sku: str,
    customer_email: str = "",
    customer_phone: str = "",
    customer_extra: str = "",
    paid_content: str = "",
    url_success: str = "",
    url_return: str = "",
    url_notification: str = "",
    discount_value: Decimal | str = "",
) -> str:
    """
    Подписанный do=pay: форма Prodamus с полем промокода.
    Короткая do=link (paylink=1) сразу открывает СБП и блокирует промокод.
    Телефон в ссылку лучше не класть — иначе форма тоже пропускается.
    """
    payload = build_checkout_payload(
        order_id=order_id,
        product_name=product_name,
        product_price=product_price,
        product_sku=product_sku,
        customer_email=customer_email,
        customer_phone=customer_phone,
        customer_extra=customer_extra,
        paid_content=paid_content,
        url_success=url_success,
        url_return=url_return,
        url_notification=url_notification,
        discount_value=discount_value,
        action="pay",
    )
    return signed_checkout_url(payload)


def extract_sign(headers) -> str:
    if headers is None:
        return ""
    for key in ("Sign", "sign", "SIGN"):
        value = headers.get(key)
        if value:
            return str(value).strip()
    return ""


def parse_webhook_payload(data: Any) -> dict:
    if isinstance(data, dict):
        keys = list(data.keys())
        if keys and any("[" in str(k) for k in keys):
            result: dict[str, Any] = {}
            for key in keys:
                value = data.get(key)
                if hasattr(data, "getlist"):
                    values = data.getlist(key)
                    value = values[-1] if values else value
                if isinstance(value, (dict, list)):
                    result[str(key)] = value
                else:
                    _assign_bracket(result, str(key), "" if value is None else str(value))
            return result
        return dict(data)
    if isinstance(data, str):
        text = data.strip()
        if not text:
            return {}
        if text.startswith("{") or text.startswith("["):
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else {}
        return _parse_php_query(text)
    return {}


def _parse_php_query(body: str) -> dict:
    pairs = urllib.parse.parse_qsl(body, keep_blank_values=True)
    result: dict[str, Any] = {}
    for key, value in pairs:
        _assign_bracket(result, key, value)
    return result


def _assign_bracket(root: dict, key: str, value: str) -> None:
    parts = re.findall(r"[^\[\]]+", key)
    if not parts:
        root[key] = value
        return
    current: Any = root
    for i, part in enumerate(parts):
        last = i == len(parts) - 1
        next_part = parts[i + 1] if not last else None
        next_is_index = next_part is not None and next_part.isdigit()
        if last:
            if isinstance(current, list):
                idx = int(part) if part.isdigit() else 0
                while len(current) <= idx:
                    current.append(value if last else {})
                current[idx] = value
            else:
                current[part] = value
            return
        if isinstance(current, list):
            idx = int(part) if part.isdigit() else 0
            while len(current) <= idx:
                current.append([] if next_is_index else {})
            if not isinstance(current[idx], (dict, list)):
                current[idx] = [] if next_is_index else {}
            current = current[idx]
            continue
        if part not in current or not isinstance(current[part], (dict, list)):
            current[part] = [] if next_is_index else {}
        current = current[part]


def payment_status_of(payload: dict) -> str:
    status = payload.get("payment_status")
    if not status and isinstance(payload.get("submit"), dict):
        status = payload["submit"].get("payment_status")
    return str(status or "").strip().lower()


def our_order_id(payload: dict) -> str:
    """order_id, который мы отправили, в вебхуке приходит как order_num."""
    for source in (payload, payload.get("submit") if isinstance(payload.get("submit"), dict) else {}):
        if not isinstance(source, dict):
            continue
        for key in ("order_num", "orderNum"):
            value = source.get(key)
            if value:
                return str(value).strip()
    return ""


def prodamus_order_id(payload: dict) -> str:
    for source in (payload, payload.get("submit") if isinstance(payload.get("submit"), dict) else {}):
        if not isinstance(source, dict):
            continue
        value = source.get("order_id")
        if value:
            return str(value).strip()
    return ""
