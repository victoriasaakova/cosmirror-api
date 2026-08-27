"""
Фоновая генерация LLM-слоёв платного отчёта.

Логин и оплата стартуют job. GET только читает кэш. Браузер не дергает
generate-эндпоинты: иначе 401, гонки сохранения и пять вызовов Polza подряд.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from django.db import DatabaseError, close_old_connections
from django.utils.dateparse import parse_datetime

from core.models import Order
from core.services import llm_client

logger = logging.getLogger(__name__)

LAYERS = ("natal", "aspects", "cycles", "request", "practice")
STALE_RUNNING = timedelta(minutes=20)

_schedule_guard = threading.Lock()
_inflight_orders: set[int] = set()
_save_guard = threading.Lock()
_section_guard = threading.Lock()
_section_inflight: set[str] = set()


def _running_tests() -> bool:
    return "test" in sys.argv or bool(os.environ.get("PYTEST_CURRENT_TEST"))


def layers_need_llm(order: Order) -> bool:
    store = order.interpretive if isinstance(order.interpretive, dict) else {}
    for key in LAYERS:
        layer = store.get(key)
        if not isinstance(layer, dict) or layer.get("source") != "llm":
            return True
    return False


def _job_stale(job: dict[str, Any]) -> bool:
    raw = str(job.get("started_at") or "")
    started = parse_datetime(raw) if raw else None
    if started is None:
        return True
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - started > STALE_RUNNING


def should_start_generation(order: Order, *, retry_failed: bool = False) -> bool:
    if not llm_client.is_configured():
        return False
    if order.status != Order.Status.PAID:
        return False
    if not layers_need_llm(order):
        return False
    store = order.interpretive if isinstance(order.interpretive, dict) else {}
    job = store.get("generation")
    if isinstance(job, dict):
        status = str(job.get("status") or "")
        if status == "running" and not _job_stale(job):
            return False
        if status == "done" and not retry_failed:
            return False
    return True


def save_interpretive_layer(
    order: Order,
    key: str,
    layer: dict[str, Any],
    *,
    extra: Optional[dict[str, Any]] = None,
) -> None:
    """Атомарно влить один слой, не затирая остальные. Повтор при гонке SQLite."""
    with _save_guard:
        _write_interpretive(order, key, layer, extra=extra)


def _write_interpretive(
    order: Order,
    key: str,
    layer: dict[str, Any],
    *,
    extra: Optional[dict[str, Any]] = None,
) -> None:
    fresh = Order.objects.filter(pk=order.pk).first()
    if fresh is None:
        logger.warning("Skip interpretive save: order %s is gone", order.pk)
        return
    store = dict(fresh.interpretive or {}) if isinstance(fresh.interpretive, dict) else {}
    store[key] = layer
    if extra:
        store.update(extra)
    fresh.interpretive = store
    try:
        fresh.save(update_fields=["interpretive", "updated_at"])
    except DatabaseError:
        logger.warning("Interpretive save raced for order %s; retrying", order.pk)
        fresh = Order.objects.filter(pk=order.pk).first()
        if fresh is None:
            return
        store = dict(fresh.interpretive or {}) if isinstance(fresh.interpretive, dict) else {}
        store[key] = layer
        if extra:
            store.update(extra)
        fresh.interpretive = store
        fresh.save(update_fields=["interpretive", "updated_at"])
    order.interpretive = fresh.interpretive


def mark_generation_status(order: Order, status: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with _save_guard:
        fresh = Order.objects.filter(pk=order.pk).first()
        if fresh is None:
            return
        store = dict(fresh.interpretive or {}) if isinstance(fresh.interpretive, dict) else {}
        job = dict(store.get("generation") or {}) if isinstance(store.get("generation"), dict) else {}
        job["status"] = status
        if status == "running":
            job["started_at"] = now
            job.pop("finished_at", None)
        elif status == "done":
            job["finished_at"] = now
            job.setdefault("started_at", now)
        store["generation"] = job
        fresh.interpretive = store
        try:
            fresh.save(update_fields=["interpretive", "updated_at"])
        except DatabaseError:
            return
        order.interpretive = fresh.interpretive


def acquire_section(order_id: int, section: str) -> bool:
    key = f"{order_id}:{section}"
    with _section_guard:
        if key in _section_inflight:
            return False
        _section_inflight.add(key)
        return True


def release_section(order_id: int, section: str) -> None:
    key = f"{order_id}:{section}"
    with _section_guard:
        _section_inflight.discard(key)


def kickoff_paid_report_for_order(order: Order, *, retry_failed: bool = False) -> None:
    if order is None or order.status != Order.Status.PAID:
        return
    schedule_paid_report_generation(order.pk, retry_failed=retry_failed)


def kickoff_paid_report_for_user(user, *, retry_failed: bool = True) -> None:
    if user is None:
        return
    from django.db.models import Q

    order = (
        Order.objects.filter(Q(user=user) | Q(session__user=user), status=Order.Status.PAID)
        .order_by("-paid_at", "-created_at")
        .first()
    )
    if order is None:
        return
    schedule_paid_report_generation(order.pk, retry_failed=retry_failed)


def schedule_paid_report_generation(order_id: int, *, retry_failed: bool = False) -> None:
    if _running_tests() or not llm_client.is_configured():
        return
    order = Order.objects.filter(pk=order_id).first()
    if order is None or not should_start_generation(order, retry_failed=retry_failed):
        return
    with _schedule_guard:
        if order_id in _inflight_orders:
            return
        _inflight_orders.add(order_id)
    thread = threading.Thread(
        target=_run_paid_report_generation,
        args=(order_id,),
        daemon=True,
        name=f"report-{order_id}",
    )
    thread.start()


def generate_missing_interpretive_layers(order: Order) -> None:
    """Синхронно дособрать слои. Для фона и тестов с моком LLM."""
    from core.services.report import (
        generate_aspects_section,
        generate_cycles_section,
        generate_natal_section,
        generate_practice_section,
        generate_request_section,
    )

    mark_generation_status(order, "running")
    try:
        generate_natal_section(order, force=False)
        order.refresh_from_db()
        generate_aspects_section(order, force=False)
        order.refresh_from_db()
        generate_cycles_section(order, force=False)
        order.refresh_from_db()
        generate_request_section(order, force=False)
        order.refresh_from_db()
        generate_practice_section(order, force=False)
    finally:
        order.refresh_from_db()
        mark_generation_status(order, "done")


def _run_paid_report_generation(order_id: int) -> None:
    close_old_connections()
    try:
        order = Order.objects.filter(pk=order_id).first()
        if order is None or order.status != Order.Status.PAID:
            return
        generate_missing_interpretive_layers(order)
    except Exception:
        logger.exception("Background paid-report generation failed for order %s", order_id)
        order = Order.objects.filter(pk=order_id).first()
        if order is not None:
            mark_generation_status(order, "done")
    finally:
        with _schedule_guard:
            _inflight_orders.discard(order_id)
        close_old_connections()
