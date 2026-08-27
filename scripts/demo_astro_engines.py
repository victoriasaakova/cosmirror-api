#!/usr/bin/env python3
"""Демо: одна дата → отчёт со Swiss и без (Skyfield).

Запуск из cosmirror-api:
  .venv/bin/python scripts/demo_astro_engines.py
"""

from __future__ import annotations

import os
import sys
from datetime import date, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from core.services import swiss_engine
from core.services.insight import build_insight
from core.services.natal import _calculate_natal_skyfield, _calculate_sky_now_skyfield


BIRTH = dict(
    birth_date=date(1993, 8, 21),
    birth_time=time(9, 45),
    latitude=55.7558,
    longitude=37.6173,
    timezone_name="Europe/Moscow",
    place="Москва",
)


def _fmt_planet(p: dict) -> str:
    degree = int(p.get("degree") or 0)
    minute = int(p.get("minute") or 0)
    bits = [f"{p['sign_ru']} {degree}°{minute:02d}′"]
    if p.get("house"):
        bits.append(f"дом {p['house']}")
    if p.get("retrograde"):
        bits.append("R")
    return " · ".join(bits)


def _print_report(title: str, natal: dict, insight: dict) -> None:
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)
    print(f"engine: {natal['engine']}")
    print(f"UTC:    {natal['datetime_utc']}")
    print("\n— Карта —")
    for key in ("sun", "moon", "mercury", "venus", "mars", "jupiter", "saturn", "uranus", "neptune", "pluto"):
        print(f"  {key:10} {_fmt_planet(natal['planets'][key])}")
    if natal.get("ascendant"):
        print(f"  {'asc':10} {_fmt_planet(natal['ascendant'])}")
    if natal.get("midheaven"):
        print(f"  {'mc':10} {_fmt_planet(natal['midheaven'])}")

    print("\n— Паттерны (insight) —")
    for block in insight.get("base") or []:
        print(f"  • {block['title']}")
        print(f"    {block['text'][:160]}…")

    print("\n— Циклы —")
    for block in insight.get("cycles") or []:
        print(f"  • {block['title']}")

    print("\n— Что отзывается —")
    for block in insight.get("influences") or []:
        print(f"  • {block['title']}")
        print(f"    {block['text'][:160]}…")


def main() -> None:
    print("Демо-персона: Аня · 21.08.1993 09:45 · Москва · фокус: отношения")

    swiss = swiss_engine.calculate_natal(**BIRTH)
    sky = _calculate_natal_skyfield(**BIRTH)
    insight_s = build_insight(swiss, swiss_engine.calculate_sky_now())
    insight_k = build_insight(sky, _calculate_sky_now_skyfield())

    _print_report("С ОТЧЁТОМ НА SWISS EPHEMERIS", swiss, insight_s)
    _print_report("БЕЗ SWISS · SKYFIELD / NASA de421", sky, insight_k)

    print("\n" + "=" * 60)
    print("Разница долгот (градусы)")
    print("=" * 60)
    for key, sp in swiss["planets"].items():
        kp = sky["planets"][key]
        d = abs(sp["longitude"] - kp["longitude"])
        if d > 180:
            d = 360 - d
        print(f"  {key:10} Δ = {d:.4f}°   знаки: {sp['sign_ru']} / {kp['sign_ru']}")


if __name__ == "__main__":
    main()
