"""Тестовый персональный отчёт: натал Swiss Ephemeris + текущие циклы."""

from __future__ import annotations

from datetime import date
from typing import Any

from django.conf import settings

from core.models import NatalChart, Order
from core.services.insight import MOON_BASE, SUN_BASE, build_insight
from core.services.natal import SIGNS_RU, calculate_sky_now
from core.services.natal_common import whole_sign_houses

PLANET_RU = {
    "sun": "Солнце",
    "moon": "Луна",
    "mercury": "Меркурий",
    "venus": "Венера",
    "mars": "Марс",
    "jupiter": "Юпитер",
    "saturn": "Сатурн",
    "uranus": "Уран",
    "neptune": "Нептун",
    "pluto": "Плутон",
}

ASC_MEANINGS = {
    "aries": "В мир ты обычно входишь прямо и быстро: сначала действие, потом объяснения. Люди считывают решительность — и давление «реши уже».",
    "taurus": "Сначала тебе нужна почва: темп, тело, ощущение «можно не спешить». Резкий вход в задачу или разговор выбивает сильнее, чем кажется.",
    "gemini": "Ты входишь через слова, вопросы, переключение. Когда нельзя проговорить или выбрать, появляется внутренний шум.",
    "cancer": "Сначала считывается атмосфера: безопасно ли здесь. Если нет — легко уйти в заботу или защиту вместо своего желания.",
    "leo": "Вход часто через присутствие: тебя должно быть видно. Игнор в начале контакта бьёт по тонусу сильнее рациональных доводов.",
    "virgo": "Ты заходишь через детали и точность. Хаос на входе забирает силы — хочется сразу навести хотя бы один понятный порядок.",
    "libra": "Сначала важен обмен и тон разговора. Дисбаланс «я подстраиваюсь» появляется быстро, если с порога нет взаимности.",
    "scorpio": "Ты не любишь поверхностный вход. Полумера и недоговорённость в начале обычно давят сильнее открытого конфликта.",
    "sagittarius": "Ты входишь с горизонтом: зачем это, куда ведёт. Узкая рамка без смысла быстро включает желание выйти.",
    "capricorn": "Снаружи часто видна собранность и ответственность. Легко сразу взять на себя слишком много — ещё до того, как спросили.",
    "aquarius": "Ты держишь дистанцию и свою отдельность. Давление «будь как все» на входе включает внутренний протест.",
    "pisces": "Граница на входе тонкая: легко впитать чужое состояние. Потом сложно понять, где ты, а где атмосфера комнаты.",
}

HOUSE_MEANINGS = {
    1: "Как ты являешься в мир: тело, первое впечатление, способ начинать.",
    2: "Опора и «моё»: деньги, навыки, чувство ценности, что даёт устойчивость.",
    3: "Ближний круг речи: мысли, переписка, сёстры/братья, короткие маршруты.",
    4: "Корень и гнездо: дом, семья, внутреннее ощущение безопасности.",
    5: "Живое самовыражение: радость, творчество, романтика, риск быть собой.",
    6: "Ритм дня: тело, работа, обязанности, то, как ты себя содержишь.",
    7: "Зеркало отношений: партнёрство, договоры, кого ты притягиваешь рядом.",
    8: "Глубина и общее: доверие, кризисы, чужие ресурсы, то, что нельзя держать на поверхности.",
    9: "Смысл и горизонт: убеждения, учёба, дальняя дорога, «зачем».",
    10: "Вклад в мире: направление, видимость, как тебя считывают по делу.",
    11: "Свои люди и будущее: сообщество, замыслы, место, где можно быть не только «полезной».",
    12: "Пауза и невидимое: усталость, сны, растворение границ, то, что просится в тишину.",
}


def report_page_url(order: Order) -> str:
    base = (getattr(settings, "FRONTEND_URL", "") or "").rstrip("/")
    if not base.startswith("https://"):
        base = "https://cosmirror.ru"
    return f"{base}/report/?order={order.public_id}"


def build_paid_report(order: Order) -> dict[str, Any]:
    natal = _natal_for(order)
    insight: dict[str, Any] = {}
    if natal.get("planets"):
        try:
            insight = build_insight(natal, calculate_sky_now())
        except Exception:
            cached = natal.get("insight")
            insight = cached if isinstance(cached, dict) else {}

    person = _person_block(order, natal)
    core = _core_blocks(natal)
    houses = _house_blocks(natal)
    cycles = _cycle_blocks(natal, insight)
    recs = _recommendation_blocks(natal, insight)

    return {
        "title": "Персональный астрологический отчёт",
        "subtitle": "Тестовая сборка по Swiss Ephemeris. Форму отчёта ещё уточним.",
        "person": person,
        "sections": [
            {"id": "person", "title": "О тебе", "blocks": _person_story(person, natal)},
            {"id": "core", "title": "Солнце, Луна, Асцендент", "blocks": core},
            {"id": "houses", "title": "Дома", "blocks": houses},
            {"id": "cycles", "title": "Текущие циклы и как они могут отзываться", "blocks": cycles},
            {"id": "recommendations", "title": "Что с этим делать", "blocks": recs},
        ],
        "disclaimer": (
            "Это не прогноз будущего и не замена терапии. "
            "Расчёт карты — Swiss Ephemeris, тексты — фиксированные шаблоны Cosmirror."
        ),
    }


def _natal_for(order: Order) -> dict[str, Any]:
    chart = NatalChart.objects.filter(session=order.session).first()
    if chart and isinstance(chart.chart_data, dict) and chart.chart_data.get("planets"):
        data = dict(chart.chart_data)
        data.setdefault("location", {})
        if chart.birth_place and not data["location"].get("place"):
            data["location"]["place"] = chart.birth_place
        return data
    session = order.session
    if session and session.birth_date:
        from core.services.onboarding_astro import build_chart_and_insight

        try:
            bundle = build_chart_and_insight(
                birth_date=session.birth_date,
                birth_time=session.birth_time,
                birth_place=session.birth_place,
                birth_lat=session.birth_lat,
                birth_lng=session.birth_lng,
                timezone_name=session.timezone or "",
            )
            return {**bundle["natal"], "insight": bundle["insight"]}
        except Exception:
            return {}
    return {}


def _person_block(order: Order, natal: dict[str, Any]) -> dict[str, Any]:
    name = ""
    lead = order.waitlist_lead or (order.session.waitlist_lead if order.session else None)
    if lead and (lead.name or "").strip():
        name = lead.name.strip()
    location = natal.get("location") if isinstance(natal.get("location"), dict) else {}
    session = order.session
    birth_date = ""
    birth_time = ""
    if session and session.birth_date:
        birth_date = session.birth_date.isoformat()
        if session.birth_time:
            birth_time = session.birth_time.strftime("%H:%M")
    chart = NatalChart.objects.filter(session=order.session).first()
    if chart:
        birth_date = chart.birth_date.isoformat()
        if chart.birth_time:
            birth_time = chart.birth_time.strftime("%H:%M")
    return {
        "name": name,
        "birth_date": birth_date,
        "birth_time": birth_time,
        "birth_place": (location.get("place") or (session.birth_place if session else "") or "").strip(),
        "timezone": natal.get("timezone") or (session.timezone if session else "") or "",
        "has_birth_time": bool(natal.get("has_birth_time")),
        "engine": natal.get("engine") or "",
    }


def _fmt_date(raw: str) -> str:
    if not raw:
        return "не указана"
    try:
        return date.fromisoformat(raw[:10]).strftime("%d.%m.%Y")
    except ValueError:
        return raw


def _person_story(person: dict[str, Any], natal: dict[str, Any]) -> list[dict[str, str]]:
    time_bit = person.get("birth_time") or "время не указано"
    place = person.get("birth_place") or "место не указано"
    name = person.get("name") or "ты"
    engine = "Swiss Ephemeris" if "swiss" in str(person.get("engine") or "") else "натальный расчёт Cosmirror"
    notes = natal.get("notes") or []
    text = (
        f"{name.capitalize() if name != 'ты' else 'Ты'}: дата рождения {_fmt_date(person.get('birth_date') or '')}, "
        f"{time_bit}, {place}."
    )
    if person.get("timezone"):
        text += f" Часовой пояс {person['timezone']}."
    text += f" Карта посчитана через {engine}."
    if notes:
        text += " " + " ".join(str(n) for n in notes if n)
    return [{"title": "Исходные данные", "text": text}]


def _placement(block: dict[str, Any] | None) -> str:
    if not isinstance(block, dict) or not block.get("sign_ru"):
        return ""
    degree = block.get("degree")
    house = block.get("house")
    bits = [str(block["sign_ru"])]
    if isinstance(degree, (int, float)):
        bits.append(f"{float(degree):.1f}°")
    if house:
        bits.append(f"дом {house}")
    if block.get("retrograde"):
        bits.append("ретроград")
    return " · ".join(bits)


def _core_blocks(natal: dict[str, Any]) -> list[dict[str, str]]:
    planets = natal.get("planets") or {}
    sun = planets.get("sun") if isinstance(planets, dict) else None
    moon = planets.get("moon") if isinstance(planets, dict) else None
    asc = natal.get("ascendant") if isinstance(natal.get("ascendant"), dict) else None
    blocks: list[dict[str, str]] = []
    if isinstance(sun, dict) and sun.get("sign"):
        sign = sun["sign"]
        extra = ""
        if sun.get("house"):
            extra = f" В карте оно стоит в {sun['house']}-м доме: {HOUSE_MEANINGS.get(int(sun['house']), '')}"
        blocks.append(
            {
                "title": f"Солнце · {_placement(sun)}",
                "text": (SUN_BASE.get(sign) or "") + extra,
            }
        )
    if isinstance(moon, dict) and moon.get("sign"):
        sign = moon["sign"]
        note = ""
        if not natal.get("has_birth_time"):
            note = " Без точного времени Луна — ориентир: за сутки она проходит около 13°."
        extra = ""
        if moon.get("house"):
            extra = f" Дом {moon['house']}: {HOUSE_MEANINGS.get(int(moon['house']), '')}"
        blocks.append(
            {
                "title": f"Луна · {_placement(moon)}",
                "text": (MOON_BASE.get(sign) or "") + extra + note,
            }
        )
    if asc and asc.get("sign"):
        sign = asc["sign"]
        blocks.append(
            {
                "title": f"Асцендент · {_placement(asc)}",
                "text": ASC_MEANINGS.get(sign)
                or "Это не «кто ты внутри», а как тебя считывают и с чего начинается твой способ быть с людьми и задачами.",
            }
        )
    elif not natal.get("has_birth_time"):
        blocks.append(
            {
                "title": "Асцендент и дома",
                "text": "Время рождения не указано — Асцендент и дома не угадываем. Солнце и общие циклы уже можно смотреть.",
            }
        )
    return blocks


def _house_blocks(natal: dict[str, Any]) -> list[dict[str, str]]:
    houses = natal.get("houses")
    if not isinstance(houses, list) or not houses:
        asc = natal.get("ascendant") if isinstance(natal.get("ascendant"), dict) else None
        if asc and isinstance(asc.get("sign_index"), int):
            houses = whole_sign_houses(int(asc["sign_index"]))
        else:
            return [
                {
                    "title": "Дома не считали",
                    "text": "Без времени рождения система домов пустая. Когда будет точное время — здесь появятся 12 домов.",
                }
            ]
    occupants: dict[int, list[str]] = {}
    planets = natal.get("planets") or {}
    if isinstance(planets, dict):
        for key, block in planets.items():
            if not isinstance(block, dict) or not block.get("house"):
                continue
            occupants.setdefault(int(block["house"]), []).append(PLANET_RU.get(key, key))
    blocks: list[dict[str, str]] = []
    for row in houses:
        if not isinstance(row, dict):
            continue
        number = int(row.get("house") or 0)
        if number < 1:
            continue
        sign_ru = row.get("sign_ru") or SIGNS_RU.get(str(row.get("sign") or ""), "")
        who = occupants.get(number) or []
        who_text = f" Здесь сейчас в карте: {', '.join(who)}." if who else ""
        blocks.append(
            {
                "title": f"{number}-й дом · {sign_ru}",
                "text": (HOUSE_MEANINGS.get(number) or "") + who_text,
            }
        )
    return blocks


def _cycle_blocks(natal: dict[str, Any], insight: dict[str, Any]) -> list[dict[str, str]]:
    blocks: list[dict[str, str]] = []
    for key in ("cycles", "influences"):
        rows = insight.get(key) if isinstance(insight, dict) else None
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            title = str(row.get("title") or "").strip()
            text = str(row.get("text") or "").strip()
            if title and text:
                blocks.append({"title": title, "text": text})
    if not blocks:
        blocks.append(
            {
                "title": "Текущее небо",
                "text": "Длинные циклы сейчас идут своим ходом. Смотри, где в жизни уже тесно, а где просится честный темп — даже без жёсткого попадания в светила.",
            }
        )
    sun = ((natal.get("planets") or {}) if isinstance(natal.get("planets"), dict) else {}).get("sun") or {}
    if isinstance(sun, dict) and sun.get("sign_ru"):
        blocks.append(
            {
                "title": "Как это стыкуется с твоей картой",
                "text": (
                    f"Натальное Солнце в {sun['sign_ru']} — это стержень, через который циклы либо давят в точку, "
                    "либо проходят фоном. Если тема цикла совпадает со знаком Солнца или Луны, она звучит личнее: "
                    "не «мир такой», а «это про меня сейчас»."
                ),
            }
        )
    return blocks


def _recommendation_blocks(natal: dict[str, Any], insight: dict[str, Any]) -> list[dict[str, str]]:
    planets = natal.get("planets") if isinstance(natal.get("planets"), dict) else {}
    sun = (planets or {}).get("sun") or {}
    moon = (planets or {}).get("moon") or {}
    influences = insight.get("influences") if isinstance(insight, dict) else []
    keys = {str(row.get("key")) for row in influences} if isinstance(influences, list) else set()

    items: list[dict[str, str]] = []
    if isinstance(sun, dict) and sun.get("sign") in SUN_BASE:
        items.append(
            {
                "title": "Опора на стержень",
                "text": (
                    "Раз в неделю спрашивай себя без аудитории: что из того, что я тяну, правда моё — "
                    "а что держится чужим ожиданием. Солнцу нужна не мотивация, а честный контур."
                ),
            }
        )
    if isinstance(moon, dict) and moon.get("sign") in MOON_BASE:
        items.append(
            {
                "title": "Эмоциональная гигиена цикла",
                "text": (
                    "Пока длинные циклы шумят, Луне нужен простой ритуал восстановления: сон, еда, один безопасный разговор. "
                    "Не как награда, а как условие, без которого решения становятся жёстче, чем жизнь."
                ),
            }
        )
    if "saturn_on_sun" in keys or "saturn_on_moon" in keys:
        items.append(
            {
                "title": "Как пройти давление Сатурна",
                "text": (
                    "Не ускоряйся из стыда и не замирай из страха ошибиться. Возьми одну конкретную ответственность "
                    "на 30 дней — маленькую, видимую тебе самой. Сатурн уважает повтор, не героизм."
                ),
            }
        )
    else:
        items.append(
            {
                "title": "Как идти в текущем фоне",
                "text": (
                    "Даже без прямого удара по светилам внешние планеты меняют климат. "
                    "Замечай, где ты автоматически соглашаешься и где уже нет сил. Это и есть вход в цикл — не гороскоп, а выбор."
                ),
            }
        )
    if any(k.startswith("uranus_") for k in keys):
        items.append(
            {
                "title": "Свобода без взрыва",
                "text": "Где уже тесно — назови это вслух себе. Можно сменить правило, а не всю жизнь. Урану достаточно честной щели.",
            }
        )
    items.append(
        {
            "title": "Практика на ближайшие недели",
            "text": (
                "Выбери один дом, который сейчас ноет (деньги, отношения, ритм, смысл) и одно маленькое действие в нём. "
                "Цикл проживается не пониманием карты, а тем, что ты перестаёшь делать на автомате."
            ),
        }
    )
    return items[:5]
