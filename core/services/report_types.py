"""
Каркас длинного персонального отчёта Cosmirror.

Два слоя, которые нельзя смешивать:

1. factual — то, что посчитано (Swiss Ephemeris + аспекты/орбы).
2. interpretive — бережная гипотеза для проверки на опыте (позже пишет модель).

Персонализация опирается на квиз онбординга, не на «знание» о жизни человека.
"""

from __future__ import annotations

# 4: вкладки «Аспекты» (натал–натал) и «Циклы» (транзиты) разведены.
SCHEMA_VERSION = 4
SYSTEM_PROMPT_ID = "paid_report"

SECTION_NATAL = "natal"
SECTION_ASPECTS = "aspects"
SECTION_CYCLES = "cycles"
SECTION_REQUEST = "request"
SECTION_PRACTICE = "practice"

WEB_TABS: list[dict[str, str]] = [
    {"id": SECTION_NATAL, "label": "Твоя карта", "hint": "Солнце, Луна, Асцендент, дома и положения"},
    {"id": SECTION_ASPECTS, "label": "Аспекты", "hint": "как темы внутри карты связаны между собой"},
    {"id": SECTION_CYCLES, "label": "Циклы", "hint": "что звучит сейчас во внешнем небе"},
    {
        "id": SECTION_REQUEST,
        "label": "Запрос",
        "hint": "как твой вопрос пересекается с картой и текущим периодом",
    },
    {
        "id": SECTION_PRACTICE,
        "label": "Практика",
        "hint": "что проверить в опыте и как исследовать найденную тему",
    },
]

PDF_OUTLINE: list[str] = [
    SECTION_NATAL,
    SECTION_ASPECTS,
    SECTION_CYCLES,
    SECTION_REQUEST,
    SECTION_PRACTICE,
]
# Порядок HTML/WeasyPrint PDF. Веб-вкладки — WEB_TABS, их не смешивать.

# --- Planets / points ----------------------------------------------------

PLANET_ORDER = (
    "sun",
    "moon",
    "mercury",
    "venus",
    "mars",
    "jupiter",
    "saturn",
    "uranus",
    "neptune",
    "pluto",
)

WHEEL_BODY_ORDER = PLANET_ORDER + (
    "north_node",
    "south_node",
    "chiron",
    "vesta",
)

# The Pattern wheel: classical planets only, no conjunction lines,
# no outer-to-outer web, no lines to nodes/Chiron/Vesta/angles.
WHEEL_ASPECT_BODIES = PLANET_ORDER
WHEEL_ASPECT_KINDS = frozenset({"square", "opposition", "trine", "sextile"})
WHEEL_ASPECT_OUTER = frozenset({"uranus", "neptune", "pluto"})
WHEEL_ASPECT_MAX_ORB = {
    "square": 6.0,
    "opposition": 6.0,
    "trine": 5.5,
    "sextile": 3.5,
}

ANGLE_ORDER = ("ascendant", "midheaven")

ENGINE_ANGLE_IDS = {
    "asc": "ascendant",
    "mc": "midheaven",
    "dsc": "descendant",
    "ic": "ic",
}

PLANET_GLYPH = {
    "sun": "☉",
    "moon": "☽",
    "mercury": "☿",
    "venus": "♀",
    "mars": "♂",
    "jupiter": "♃",
    "saturn": "♄",
    "uranus": "♅",
    "neptune": "♆",
    "pluto": "♇",
    "north_node": "☊",
    "south_node": "☋",
    "chiron": "⚷",
    "vesta": "⚶",
    "ascendant": "Asc",
    "midheaven": "MC",
    "descendant": "Ds",
    "ic": "IC",
}

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
    "north_node": "Северный узел",
    "south_node": "Южный узел",
    "chiron": "Хирон",
    "vesta": "Веста",
    "ascendant": "Асцендент",
    "midheaven": "Середина неба",
    "descendant": "Десцендент",
    "ic": "Надир",
}

# Вес точки, по которой бьёт транзит: светила и углы важнее внешних натальных.
NATAL_POINT_WEIGHT = {
    "sun": 1.0,
    "moon": 0.95,
    "ascendant": 0.9,
    "midheaven": 0.82,
    "mercury": 0.72,
    "venus": 0.78,
    "mars": 0.76,
    "jupiter": 0.62,
    "saturn": 0.64,
    "uranus": 0.5,
    "neptune": 0.48,
    "pluto": 0.52,
}

# Вес транзитной планеты в длинном отчёте: внешние задают сюжет.
TRANSIT_PLANET_WEIGHT = {
    "sun": 0.22,
    "moon": 0.12,
    "mercury": 0.18,
    "venus": 0.22,
    "mars": 0.38,
    "jupiter": 0.62,
    "saturn": 0.9,
    "uranus": 1.0,
    "neptune": 0.88,
    "pluto": 1.0,
}

ASPECTS = (
    {"angle": 0, "key": "conjunction", "ru": "соединение", "kind": "hard", "weight": 1.0},
    {"angle": 60, "key": "sextile", "ru": "секстиль", "kind": "soft", "weight": 0.55},
    {"angle": 90, "key": "square", "ru": "квадрат", "kind": "hard", "weight": 0.86},
    {"angle": 120, "key": "trine", "ru": "тригон", "kind": "soft", "weight": 0.7},
    {"angle": 180, "key": "opposition", "ru": "оппозиция", "kind": "hard", "weight": 0.92},
)

# Максимальный орб: транзит → натал. Узже, чем натальные аспекты.
TRANSIT_ORB = {
    "sun": 6.0,
    "moon": 5.0,
    "mercury": 3.5,
    "venus": 3.5,
    "mars": 4.0,
    "jupiter": 5.0,
    "saturn": 6.0,
    "uranus": 5.0,
    "neptune": 5.0,
    "pluto": 5.0,
}

NATAL_ORB = {
    "sun": 8.0,
    "moon": 8.0,
    "mercury": 6.0,
    "venus": 6.0,
    "mars": 6.0,
    "jupiter": 7.0,
    "saturn": 7.0,
    "uranus": 6.0,
    "neptune": 6.0,
    "pluto": 6.0,
    "ascendant": 7.0,
    "midheaven": 7.0,
}

POLARITY_PRESSURE = "pressure"
POLARITY_RESOURCE = "resource"
POLARITY_MIXED = "mixed"

POLARITY_RU = {
    POLARITY_PRESSURE: "напряжение",
    POLARITY_RESOURCE: "ресурс",
    POLARITY_MIXED: "смешанное",
}

# --- Quiz: персонализация ------------------------------------------------

FOCUS_HOUSES = {
    "love": (5, 7, 8),
    "money": (2, 6, 10),
    "energy": (1, 6, 12),
    "confidence": (1, 5, 10),
    "path": (1, 9, 10),
    "future": (1, 9, 10),
    "other": (1, 10),
}

FOCUS_PLANETS = {
    "love": ("venus", "moon", "mars"),
    "money": ("jupiter", "saturn", "venus", "mars"),
    "energy": ("mars", "moon", "sun", "saturn"),
    "confidence": ("sun", "mars", "saturn"),
    "path": ("sun", "jupiter", "saturn"),
    "future": ("sun", "jupiter", "saturn"),
    "other": ("sun", "moon"),
}

FOCUS_LABELS = {
    "love": "отношения и любовь",
    "money": "работа и деньги",
    "energy": "энергия и восстановление",
    "confidence": "уверенность и самооценка",
    "path": "самореализация и свой путь",
    "future": "будущее и перемены",
    "other": "личное",
}

INTENT_LABELS = {
    "life-stage": "что происходит сейчас",
    "patterns": "какие сценарии повторяются",
    "potential": "в чём мой потенциал",
    "uncertainty": "куда двигаться дальше",
    "future": "чего ждать в ближайшее время",
    "relationships": "наладить отношения",
    "other": "разобраться в себе",
}

LIFE_STAGE_LABELS = {
    "stable": "в целом всё стабильно",
    "one-sphere": "меняется одна важная сфера",
    "many-spheres": "меняется сразу несколько сфер",
    "ready-to-change": "пора что-то менять",
    "unclear": "чувствую перемены, но пока не понимаю их",
}

CHART_KNOWLEDGE_LABELS = {
    "sun-only": "знаю только свой знак",
    "big-three": "знаю Солнце, Луну и асцендент",
    "natal-chart": "читаю карту и слежу за транзитами",
    "transits": "читаю карту и слежу за транзитами",
}

TRIGGER_LABELS = {
    "understand-self": "хочет понять своё состояние",
    "person": "думает о конкретном человеке",
    "decision": "стоит перед важным выбором",
    "check-feelings": "хочет свериться с собой",
    "curious": "просто интересно",
}

KNOWLEDGE_DEPTH = {
    "sun-only": "explain_all",
    "big-three": "explain_transits",
    "natal-chart": "remind_terms",
    "transits": "deep_dive",
}

# Сколько транзитов отдаём в акценты и в промпт.
PRIMARY_LIMIT = 1
SUPPORT_LIMIT = 3
PRESSURE_LIMIT = 5
RESOURCE_LIMIT = 4
THROUGH_LINE_HITS = 6
PROMPT_TRANSIT_LIMIT = 10
PROMPT_NATAL_ASPECT_LIMIT = 8
