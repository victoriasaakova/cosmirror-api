"""Сборка натальной карты + инсайта для онбординга."""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any, Optional, Union

from django.utils import timezone

from core.models import NatalChart
from core.services.geo import GeoLookupError, resolve_birth_geo
from core.services.insight import build_insight
from core.services.natal import NatalCalcError, calculate_natal, calculate_sky_now


def _parse_date(value: Union[str, date]) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    return date.fromisoformat(str(value)[:10])


def _parse_time(value: Union[str, time, None]) -> Optional[time]:
    if value in (None, ""):
        return None
    if isinstance(value, time):
        return value
    raw = str(value).strip()
    # "12:00" / "12:00:00"
    parts = raw.split(":")
    hour = int(parts[0])
    minute = int(parts[1]) if len(parts) > 1 else 0
    second = int(float(parts[2])) if len(parts) > 2 else 0
    return time(hour, minute, second)


def build_chart_and_insight(
    *,
    birth_date,
    birth_time=None,
    birth_place: str = "",
    birth_lat=None,
    birth_lng=None,
    timezone_name: str = "",
) -> dict[str, Any]:
    geo = resolve_birth_geo(
        place=birth_place or None,
        latitude=float(birth_lat) if birth_lat not in (None, "") else None,
        longitude=float(birth_lng) if birth_lng not in (None, "") else None,
        timezone=timezone_name or None,
    )
    natal = calculate_natal(
        birth_date=_parse_date(birth_date),
        birth_time=_parse_time(birth_time),
        latitude=geo.latitude,
        longitude=geo.longitude,
        timezone_name=geo.timezone,
        place=geo.place,
    )
    sky = calculate_sky_now()
    insight = build_insight(natal, sky)
    return {
        "geo": {
            "place": geo.place,
            "latitude": geo.latitude,
            "longitude": geo.longitude,
            "timezone": geo.timezone,
            "country": geo.country,
        },
        "natal": natal,
        "insight": insight,
    }


def calculate_and_store_chart(chart: NatalChart) -> NatalChart:
    """Пересчитать NatalChart и сохранить chart_data + insight."""
    try:
        bundle = build_chart_and_insight(
            birth_date=chart.birth_date,
            birth_time=chart.birth_time,
            birth_place=chart.birth_place,
            birth_lat=chart.birth_lat,
            birth_lng=chart.birth_lng,
            timezone_name=chart.timezone or "",
        )
    except (GeoLookupError, NatalCalcError) as exc:
        chart.status = NatalChart.Status.FAILED
        chart.error_message = str(exc)
        chart.chart_data = {}
        chart.calculated_at = None
        chart.save(
            update_fields=["status", "error_message", "chart_data", "calculated_at", "updated_at"]
        )
        raise

    geo = bundle["geo"]
    chart.birth_place = geo["place"] or chart.birth_place
    chart.birth_lat = geo["latitude"]
    chart.birth_lng = geo["longitude"]
    chart.timezone = geo["timezone"]
    chart.chart_data = {
        **bundle["natal"],
        "insight": bundle["insight"],
    }
    chart.status = NatalChart.Status.READY
    chart.error_message = ""
    chart.calculated_at = timezone.now()
    chart.save()
    return chart
