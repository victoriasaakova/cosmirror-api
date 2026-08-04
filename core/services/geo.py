"""Город → координаты + таймзона (Nominatim + timezonefinder)."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Optional

from timezonefinder import TimezoneFinder

_TF = TimezoneFinder()
_USER_AGENT = "CosmirrorOnboarding/0.1 (local; contact=hello@cosmirror.app)"


@dataclass
class GeoResult:
    place: str
    latitude: float
    longitude: float
    timezone: str
    country: str = ""


class GeoLookupError(Exception):
    pass


def timezone_at(latitude: float, longitude: float) -> str:
    tz = _TF.timezone_at(lat=latitude, lng=longitude)
    if not tz:
        raise GeoLookupError("Не удалось определить таймзону по координатам.")
    return tz


def _hit_to_result(hit: dict, fallback_query: str = "") -> GeoResult:
    lat = float(hit["lat"])
    lng = float(hit["lon"])
    tz = timezone_at(lat, lng)
    address = hit.get("address") or {}
    country = address.get("country") or ""
    city = (
        address.get("city")
        or address.get("town")
        or address.get("village")
        or address.get("municipality")
        or address.get("county")
        or fallback_query
        or (hit.get("display_name") or "").split(",")[0]
    )
    place = f"{city}, {country}" if country else str(city)
    return GeoResult(
        place=place,
        latitude=lat,
        longitude=lng,
        timezone=tz,
        country=country,
    )


def _nominatim_search(query: str, *, limit: int = 1, language: str = "ru") -> list[dict]:
    q = (query or "").strip()
    if len(q) < 2:
        return []

    params = urllib.parse.urlencode(
        {
            "q": q,
            "format": "json",
            "limit": max(1, min(limit, 8)),
            "addressdetails": 1,
            "accept-language": language,
        }
    )
    url = f"https://nominatim.openstreetmap.org/search?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise GeoLookupError("Сервис геокодинга временно недоступен.") from exc

    return data if isinstance(data, list) else []


def lookup_place(query: str, *, language: str = "ru") -> GeoResult:
    """Резолв города через OpenStreetMap Nominatim."""
    q = (query or "").strip()
    if len(q) < 2:
        raise GeoLookupError("Введите название города.")

    data = _nominatim_search(q, limit=1, language=language)
    if not data:
        raise GeoLookupError("Город не найден. Попробуйте другое написание.")

    return _hit_to_result(data[0], fallback_query=q)


def suggest_places(query: str, *, language: str = "ru", limit: int = 5) -> list[GeoResult]:
    """Подсказки городов для автокомплита онбординга."""
    q = (query or "").strip()
    if len(q) < 2:
        return []

    data = _nominatim_search(q, limit=limit, language=language)
    results: list[GeoResult] = []
    seen: set[str] = set()
    for hit in data:
        item = _hit_to_result(hit, fallback_query=q)
        key = f"{item.place}|{round(item.latitude, 3)}|{round(item.longitude, 3)}"
        if key in seen:
            continue
        seen.add(key)
        results.append(item)
    return results


def resolve_birth_geo(
    *,
    place: Optional[str] = None,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    timezone: Optional[str] = None,
) -> GeoResult:
    """
    Нормализует геоданные для онбординга.
    Если есть lat/lng — таймзону добираем сами.
    Если только place — геокодим.
    """
    if latitude is not None and longitude is not None:
        tz = (timezone or "").strip() or timezone_at(float(latitude), float(longitude))
        return GeoResult(
            place=(place or "").strip() or f"{latitude},{longitude}",
            latitude=float(latitude),
            longitude=float(longitude),
            timezone=tz,
        )

    if place:
        return lookup_place(place)

    raise GeoLookupError("Нужен город или координаты рождения.")
