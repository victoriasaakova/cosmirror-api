"""Черновик synastry_orbs_v1 и bond_taxonomy_v1.

Числа взяты из compatibility/docs/ASTRO_POLICY_DRAFT.md.
Это не natal-orbs-v1 и не утверждённая астрологом формула ярлыка пары.
"""

from __future__ import annotations

SCHEMA_VERSION = "compatibility-v1"
SYNASTRY_POLICY_VERSION = "synastry-orbs-v1"
TAXONOMY_VERSION = "bond-taxonomy-v1"
WRITER_VERSION = "compatibility-writers-v2"

HORIZON_PAST_DAYS = 0
HORIZON_FUTURE_MONTHS = 18

# aspect, exact angle, base orb
ASPECTS: tuple[tuple[str, float, float], ...] = (
    ("conjunction", 0.0, 5.0),
    ("sextile", 60.0, 3.0),
    ("square", 90.0, 4.0),
    ("trine", 120.0, 4.0),
    ("opposition", 180.0, 5.0),
)

ANGLE_ORB_CAP = 3.0
NODE_ORB_CAP = 3.0

PERSONAL = frozenset({"sun", "moon", "mercury", "venus", "mars"})
SOCIAL = frozenset({"jupiter", "saturn"})
SLOW = frozenset({"uranus", "neptune", "pluto"})
ANGLES = frozenset({"asc", "mc"})
NODES = frozenset({"north_node", "south_node"})

CHART_BODIES: tuple[str, ...] = (
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
    "north_node",
    "south_node",
    "chiron",
)

SIGN_POINTS: tuple[str, ...] = ("sun", "moon", "mercury", "venus", "mars")
OVERLAY_BODIES: tuple[str, ...] = (
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
    "chiron",
)

BOND_CATEGORIES: tuple[str, ...] = (
    "life_changing",
    "amazing",
    "attraction",
    "notables",
    "frustration",
    "trials",
)

# Пары, которые черновик относит к притяжению. Один аспект — одна категория.
ATTRACTION_PAIRS = frozenset(
    {
        ("mars", "venus"),
        ("venus", "venus"),
        ("mars", "moon"),
        ("sun", "venus"),
        ("asc", "venus"),
        ("asc", "mars"),
        ("mc", "venus"),
    }
)

BODY_RU = {
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
    "asc": "Асцендент",
    "mc": "MC",
}

ASPECT_RU = {
    "conjunction": "соединение",
    "sextile": "секстиль",
    "square": "квадрат",
    "trine": "тригон",
    "opposition": "оппозиция",
}

SIGN_FUNCTION_RU = {
    "sun": "направление и способ проявляться",
    "moon": "эмоциональный ритм и потребность в безопасности",
    "mercury": "способ думать и объяснять",
    "venus": "способ выбирать близкое и приятное",
    "mars": "способ начинать и добиваться",
    "asc": "способ входить в контакт",
}

CATEGORY_TITLE = {
    "life_changing": "Связка, которая может сдвигать привычное",
    "amazing": "То, что между вами легче поддерживается",
    "attraction": "Интерес и ответное движение",
    "notables": "Заметная связь",
    "frustration": "Разница ритма",
    "trials": "Тема усилия и предела",
}
