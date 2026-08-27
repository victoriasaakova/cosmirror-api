"""
Pattern-like тексты для онбординга.

Не LLM: фиксированные шаблоны на пересечении натала и текущего неба.
Тон: психология + жизненный опыт, без астро-жаргона и «ИИшного» пафоса.
"""

from __future__ import annotations

from typing import Any, Optional

from .natal import SIGNS_RU, calculate_sky_now
from .natal_common import angular_distance

# Краткие «базовые» паттерны по Солнцу / Луне — не гороскопные клише.
SUN_BASE = {
    "aries": "Тебе нужно начинать. Без движения энергия скисает в раздражение.",
    "taurus": "Тебе нужна почва и «моё». Срыв без опоры выматывает сильнее, чем видно снаружи.",
    "gemini": "Тебе нужно понимать вслух. Одна роль или один ответ быстро становятся внутренним шумом.",
    "cancer": "Сначала безопасность, потом желание. Без ощущения «своих» легко уйти в защиту вместо себя.",
    "leo": "Тебе нужно быть увиденной. Игнор бьёт сильнее любых разумных доводов.",
    "virgo": "Ты замечаешь, где не сходится. Хаос забирает силы — хочется хотя бы один понятный кусок.",
    "libra": "Тебе нужен обмен, не перекос. «Я всё тяну» быстро становится фоном усталости.",
    "scorpio": "Поверхность тебе тесна. Полумера давит сильнее открытого конфликта.",
    "sagittarius": "Тебе нужен «зачем». Рутина без горизонта включает желание вырваться.",
    "capricorn": "Ты держишь результат. Легко взять лишнее — и злиться, что никто не подхватил.",
    "aquarius": "Тебе нужна своя отдельность. Давление «будь как все» включает протест.",
    "pisces": "Ты впитываешь состояния. Потом трудно понять, где ты, а где чужое.",
}

MOON_BASE = {
    "aries": "Напряжение нужно разрядить. Долгое «терпи» обычно кончается вспышкой.",
    "taurus": "Спокойствие приходит через тело и предсказуемость. Когда всё шатается, нужны не советы, а опора.",
    "gemini": "Чувства хотят слов. Если некуда их разложить, тревога растёт сама.",
    "cancer": "Настроению нужны свои. Отрыв от гнезда бьёт сильнее внешних событий.",
    "leo": "Нужно тёплое внимание. Холод ранит глубже, чем кажется.",
    "virgo": "Тревога идёт в мелочи и починки. Хочется всё поправить, вместо того чтобы почувствовать.",
    "libra": "Напряжение между людьми тебе тяжело. Мир иногда покупается ценой своих чувств.",
    "scorpio": "Чувства глубокие и не напоказ. Нарушенное доверие помнится долго.",
    "sagittarius": "Настроению нужен воздух. Мелкий контроль душит быстрее ссоры.",
    "capricorn": "Эмоции часто в форме. Усталость выглядит как «просто работаю дальше».",
    "aquarius": "Легче наблюдать чувство, чем тонуть в нём. Близость без свободы — ловушка.",
    "pisces": "Чужой фон впитывается легко. Без паузы можно принять его за своё.",
}

# Текущие циклы — общий фон (не персональный).
CYCLE_BY_SIGN = {
    "saturn": {
        "aries": {
            "title": "Сатурн в Овне",
            "text": "В воздухе тема взросления через действие: меньше отговорок, больше ответственности за свои старты. Давление может ощущаться как «надо уже решить и сделать».",
        },
        "taurus": {
            "title": "Сатурн в Тельце",
            "text": "Фон про устойчивость и реальные ресурсы: деньги, тело, привычки. То, что держалось «на честном слове», просит более честной опоры.",
        },
        "gemini": {
            "title": "Сатурн в Близнецах",
            "text": "В воздухе тема дисциплины ума и слов: меньше распыления, больше ясных договорённостей и выбранного фокуса.",
        },
        "cancer": {
            "title": "Сатурн в Раке",
            "text": "Фон про границы в близком: семья, дом, эмоциональная ответственность. Может всплывать усталость от роли «я всех держу».",
        },
        "leo": {
            "title": "Сатурн во Льве",
            "text": "Тема зрелого самовыражения: не ради реакции, а из внутреннего стержня. Легко чувствовать проверку на «а я вообще имею право».",
        },
        "virgo": {
            "title": "Сатурн в Деве",
            "text": "Фон про систему и здоровье процессов: работа, тело, быт. Хаос в мелочах сейчас дороже обычного.",
        },
        "libra": {
            "title": "Сатурн в Весах",
            "text": "В воздухе тема зрелых отношений и справедливого обмена. Перекосы «я — тебе» становятся заметнее.",
        },
        "scorpio": {
            "title": "Сатурн в Скорпионе",
            "text": "Фон про глубину и честность с тенью: контроль, ревность, власть, доверие. Поверхностные решения держатся хуже.",
        },
        "sagittarius": {
            "title": "Сатурн в Стрельце",
            "text": "Тема проверки убеждений и «большого смысла». Легко разочароваться в громких идеях — и искать более честный путь.",
        },
        "capricorn": {
            "title": "Сатурн в Козероге",
            "text": "Фон структур и длинной дистанции: карьера, статус, обязательства. То, что построено на имидже, проходит проверку на прочность.",
        },
        "aquarius": {
            "title": "Сатурн в Водолее",
            "text": "В воздухе тема свободы внутри системы: сообщества, будущее, свои правила. Давление нормы сталкивается с потребностью быть собой.",
        },
        "pisces": {
            "title": "Сатурн в Рыбах",
            "text": "Фон про границы в тумане: усталость, растворение, потребность в реальном recovery. Легко путать сострадание с самопожертвованием.",
        },
    },
    "uranus": {
        "default": {
            "title": "Уран — фон ускоренных сдвигов",
            "text": "В длинном цикле сильнее тема внезапных разворотов и желания выйти из слишком тесной роли. Не обязательно рвать всё — но игнор обычно срывается сам.",
        }
    },
    "neptune": {
        "default": {
            "title": "Нептун — фон размытых границ",
            "text": "Легче идеализировать или уставать без ясной причины. Имеет смысл чаще спрашивать: это моё чувство — или я подхватила чужое?",
        }
    },
    "pluto": {
        "default": {
            "title": "Плутон — фон глубинной перестройки",
            "text": "Длинный цикл про власть, контроль и то, что больше нельзя держать «как раньше». Перемены идут не поверхностно.",
        }
    },
}


# Птолемеевы аспекты — как в платном отчёте. Совпадение знака = только соединение.
_ASPECTS = (
    (0.0, "conjunction"),
    (60.0, "sextile"),
    (90.0, "square"),
    (120.0, "trine"),
    (180.0, "opposition"),
)
_TRANSIT_ORB = {
    "jupiter": 5.0,
    "saturn": 6.0,
    "uranus": 5.0,
    "neptune": 5.0,
    "pluto": 5.0,
}
_CYCLE_PLANETS = ("pluto", "neptune", "uranus", "saturn", "jupiter")
_NATAL_TARGETS = ("sun", "moon", "ascendant", "midheaven", "venus", "mars")
_NATAL_RANK = {key: idx for idx, key in enumerate(_NATAL_TARGETS)}

OUTER_COPY = {
    "jupiter": {
        "title": "Где жизнь просит шире",
        "text": "Сейчас легче почувствовать, где привычный масштаб уже тесен: хочется смысла, воздуха и честного «зачем». Это не призыв всё бросить — скорее заметка, куда есть живой интерес, а где ты тянешь по инерции.",
    },
    "saturn": {
        "sun": {
            "title": "Что может отзываться сейчас",
            "text": "Сейчас длинный цикл давит именно на твою тему самости и направления. Может усиливаться вопрос: «кто я, если убрать чужие ожидания и старые роли». Это не поломка — скорее период взросления стержня.",
        },
        "moon": {
            "title": "Эмоциональная нагрузка цикла",
            "text": "Фон сейчас резонирует с твоим способом чувствовать безопасность. Легче уставать от заботы о других или от ощущения, что «надо держать лицо». Имеет смысл отдельно спрашивать себя, где тебе реально нужна опора.",
        },
        "default": {
            "title": "Что может отзываться сейчас",
            "text": "Длинный цикл проверяет опору: где ты держишь всё сама и где уже нужна более честная структура. Давление обычно не про «ты плохо справляешься», а про взросление границ и приоритетов.",
        },
    },
    "uranus": {
        "title": "Тяга выйти из тесной роли",
        "text": "Сейчас небо подсвечивает твою тему свободы. Может усиливаться желание перестать быть «удобной версией себя». Не обязательно взрывать жизнь — достаточно честно заметить, где уже тесно.",
    },
    "neptune": {
        "title": "Размытие и чувствительность",
        "text": "Сейчас легче потерять границы или идеализировать сценарий. Полезно чаще возвращаться к простому вопросу: что я чувствую на самом деле — и что додумала.",
    },
    "pluto": {
        "title": "Глубинная перестройка",
        "text": "Сейчас длинный цикл может цеплять тему контроля и того, что больше не работает «по-старому». Сопротивление перемене обычно сильнее самой перемены.",
    },
}


def _sign(planet_block: dict[str, Any], key: str) -> Optional[str]:
    node = (planet_block or {}).get(key) or {}
    return node.get("sign")


def _label(sign: Optional[str]) -> str:
    if not sign:
        return ""
    return SIGNS_RU.get(sign, sign)


def _longitude(block: Any) -> Optional[float]:
    if not isinstance(block, dict) or block.get("longitude") is None:
        return None
    return float(block["longitude"]) % 360.0


def _natal_targets(natal: dict[str, Any]) -> dict[str, dict[str, Any]]:
    planets = natal.get("planets") if isinstance(natal.get("planets"), dict) else {}
    points: dict[str, dict[str, Any]] = {}
    for key in _NATAL_TARGETS:
        block = natal.get(key) if key in ("ascendant", "midheaven") else planets.get(key)
        if isinstance(block, dict) and _longitude(block) is not None:
            points[key] = block
    return points


def _best_aspect(sep: float) -> tuple[float, str]:
    angle, name = min(_ASPECTS, key=lambda item: abs(sep - item[0]))
    return abs(sep - angle), name


def _copy_for(planet: str, natal_key: str) -> dict[str, str]:
    block = OUTER_COPY[planet]
    if planet == "saturn":
        chosen = block.get(natal_key) or block["default"]
        return {"title": chosen["title"], "text": chosen["text"]}
    return {"title": block["title"], "text": block["text"]}


def _influence(planet: str, natal_key: str) -> dict[str, str]:
    copy = _copy_for(planet, natal_key)
    return {"key": f"{planet}_on_{natal_key}", "title": copy["title"], "text": copy["text"]}


def _cycle_hits(natal: dict[str, Any], now_planets: dict[str, Any]) -> list[dict[str, Any]]:
    """Персональные попадания длинных циклов: аспект по орбу, иначе ближайший."""
    targets = _natal_targets(natal)
    scored: list[tuple[float, float, str, str]] = []
    for planet in _CYCLE_PLANETS:
        t_lon = _longitude((now_planets or {}).get(planet))
        if t_lon is None:
            continue
        max_orb = _TRANSIT_ORB[planet]
        for natal_key, n_block in targets.items():
            n_lon = _longitude(n_block)
            if n_lon is None:
                continue
            orb, _aspect = _best_aspect(angular_distance(t_lon, n_lon))
            natal_rank = float(_NATAL_RANK.get(natal_key, 9))
            off_orb = 0.0 if orb <= max_orb else 10.0
            scored.append((natal_rank + off_orb, orb, planet, natal_key))

    scored.sort()
    picked: list[dict[str, str]] = []
    used_planets: set[str] = set()
    used_keys: set[str] = set()
    for natal_rank, orb, planet, natal_key in scored:
        if planet in used_planets:
            continue
        item = _influence(planet, natal_key)
        if item["key"] in used_keys:
            continue
        used_planets.add(planet)
        used_keys.add(item["key"])
        picked.append(item)
        if len(picked) >= 3:
            break
    return picked


def build_insight(natal: dict[str, Any], sky_now: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Собрать блоки для экрана онбординга."""
    sky = sky_now or calculate_sky_now()
    natal_planets = natal.get("planets") or {}
    now_planets = sky.get("planets") or {}

    sun = _sign(natal_planets, "sun")
    moon = _sign(natal_planets, "moon")
    asc = (natal.get("ascendant") or {}).get("sign")

    base: list[dict[str, str]] = []
    if sun and sun in SUN_BASE:
        base.append(
            {
                "key": "natal_sun",
                "title": f"Базовый паттерн · Солнце в {_label(sun)}",
                "text": SUN_BASE[sun],
            }
        )
    if moon and moon in MOON_BASE:
        note = ""
        if not natal.get("has_birth_time"):
            note = " Без точного времени Луна — ориентир, не приговор."
        base.append(
            {
                "key": "natal_moon",
                "title": f"Эмоциональный фон · Луна в {_label(moon)}",
                "text": MOON_BASE[moon] + note,
            }
        )
    if asc:
        base.append(
            {
                "key": "natal_asc",
                "title": f"Как ты входишь в мир · Асцендент в {_label(asc)}",
                "text": "Это не «кто ты внутри», а как тебя считывают и с чего обычно начинается твой способ быть с людьми и задачами.",
            }
        )
    elif not natal.get("has_birth_time"):
        base.append(
            {
                "key": "no_birth_time",
                "title": "Время рождения пока не указано",
                "text": "Солнце и общие циклы уже можно смотреть. Асцендент и дома появятся, когда будет точное время — без него мы их не угадываем.",
            }
        )

    cycles: list[dict[str, str]] = []
    saturn_sign = _sign(now_planets, "saturn")
    if saturn_sign and saturn_sign in CYCLE_BY_SIGN["saturn"]:
        cycles.append({"key": f"saturn_{saturn_sign}", **CYCLE_BY_SIGN["saturn"][saturn_sign]})
    for outer in ("uranus", "neptune", "pluto"):
        block = CYCLE_BY_SIGN[outer]["default"]
        sign = _sign(now_planets, outer)
        title = block["title"]
        if sign:
            title = f"{title} · сейчас в {_label(sign)}"
        cycles.append({"key": f"{outer}_now", "title": title, "text": block["text"]})

    influences = _cycle_hits(natal, now_planets)

    return {
        "tone": "pattern_psych",
        "disclaimer": "Это не прогноз будущего и не замена терапии. Это способ заметить, какие внутренние темы могут быть громче на фоне текущих циклов.",
        "base": base,
        "cycles": cycles[:4],
        "influences": influences[:3],
        "sky_now": {
            "datetime_utc": sky.get("datetime_utc"),
            "planets": {
                k: {"sign": v.get("sign"), "sign_ru": v.get("sign_ru"), "degree": v.get("degree")}
                for k, v in now_planets.items()
                if k in ("sun", "moon", "saturn", "uranus", "neptune", "pluto")
            },
        },
    }
