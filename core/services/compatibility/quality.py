"""Планка пользовательского текста Compatibility v2.

Учебные примеры задают конкретность и глубину. Дословное совпадение с ними
отклоняется: это чужой условный сюжет, не текст данной пары.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from .policy import PLANET_ROLE

_GOLD_VERBATIM = (
    "с некоторыми людьми не нужно постоянно подбирать слова",
    "ты можешь слишком стараться понравиться тому, рядом с кем хочешь быть собой",
    "самые яркие моменты не всегда становятся самыми устойчивыми отношениями",
    "рядом с ним тебе может быть проще не объяснять каждое своё чувство",
    "один хочет поддержки. другой спешит что-то исправить",
    "вам не обязательно помогать одинаково, чтобы помощь была взаимной",
    "разговор снова может превращаться в проверку на ошибки",
    "тепло между вами может сохраняться даже после сложного разговора",
    "вам могло быть тепло вместе",
    "труднее оставлять свои потребности на потом",
    "идеям максима сейчас может становиться тесно",
    "разговор помогает вашей инициативе становиться делом",
)

_ANTI = (
    "повторяющаяся тема собрана",
    "привычный ход сдвигают",
    "в контакте больше опоры, чем столкновения",
    "пропущенные точки не снижают",
    "пропущенные из-за времени рождения точки не снижают",
    "разговор помогает вашей инициативе",
)

_LABEL = re.compile(
    r"(?:^|\n)\s*(?:ты|другой человек|между вами|инсайт)\s*[:.—–-]\s",
    re.IGNORECASE,
)

_SUPPORTIVE_CONFLICT = ("конфликт", "ссор", "расстан", "обид", "предател")
_PLANET_STEMS = (
    "солнц",
    "лун",
    "меркур",
    "венер",
    "марс",
    "юпитер",
    "сатурн",
    "уран",
    "нептун",
    "плутон",
)
_ROLES = tuple(role.casefold() for role in PLANET_ROLE.values())

# Бессмысленные сочетания, а не отдельные слова. «Тесно в роли» и «по ходу разговора» сюда не входят.
_EMPTY_METAPHOR = (
    re.compile(r"ход\w{0,4}.{0,40}крупн"),
    re.compile(r"крупн\w{0,6}.{0,40}ход"),
    re.compile(r"(?:стать|становится)\s+крупн"),
    re.compile(r"тепл\w{0,6}.{0,24}тесн"),
    re.compile(r"тесн\w{0,6}.{0,24}тепл"),
    re.compile(r"маленьк\w+\s+знак"),
    re.compile(r"опор\w{0,6}.{0,28}контур"),
    re.compile(r"контур\w{0,6}.{0,28}опор"),
    re.compile(r"у опоры есть контур"),
    re.compile(r"собственный ход"),
    re.compile(r"своим ходом"),
    re.compile(r"свой ход"),
    re.compile(r"чужой контур"),
    re.compile(r"есть вес"),
    re.compile(r"(?:движени\w+|шаг\w{0,3}|ход\w{0,3}|импульс\w{0,3}).{0,28}вес"),
    re.compile(r"размер хода"),
    re.compile(r"поднимает ставку"),
    re.compile(r"превраща\w+\s+в\s+ставк"),
    re.compile(r"оказыва\w+\s+ставк"),
    re.compile(r"(?:шаг|ход|движени\w+|действ\w+).{0,32}ставк"),
    re.compile(r"масштаб\w{0,3}.{0,24}(?:ложи|принос|ход|связ)"),
    re.compile(r"приносит масштаб"),
    re.compile(r"тепл\w.{0,20}напор"),
    re.compile(r"пространство возможност"),
    re.compile(r"внутренн\w+\s+импульс"),
    re.compile(r"больш\w+\s+ставк"),
    re.compile(r"ход\w{0,3}\s+помеща"),
    re.compile(r"форма,\s+которая держит"),
    re.compile(r"над[её]жность собирается"),
    re.compile(r"договор[её]нность с контуром"),
    re.compile(r"(?:твой|свой|его|её|ее)\s+ход\b"),
    re.compile(r"\bход\s+(?:становится|может|получает|хочет|включается)"),
)


def editorial_issue(text: str) -> Optional[str]:
    """Пустая метафора, из которой неясно, какое переживание имеется в виду."""
    lowered = " ".join(text.casefold().split())
    if any(pattern.search(lowered) for pattern in _EMPTY_METAPHOR):
        return "Фраза не называет переживание, потребность, реакцию или ситуацию: это пустая метафора."
    return None


def rejection_reason(
    text: str,
    *,
    kind: str,
    polarity: Optional[str] = None,
    factors: Optional[list[dict[str, Any]]] = None,
    value: Optional[int] = None,
    omitted_factors: Optional[list[str]] = None,
) -> Optional[str]:
    """Причина отказа. None значит, что текст не попал в известный антипаттерн."""
    lowered = " ".join(text.casefold().split())
    if any(sample in lowered for sample in _GOLD_VERBATIM):
        return "Текст повторяет учебный пример. Нужно наблюдение этой пары, а не чужой формулировки."
    if any(sample in lowered for sample in _ANTI):
        return "Это техническая или общая фраза, а не персональная интерпретация."
    if _LABEL.search(text):
        return "Внутренние подписи нельзя показывать как структуру текста."
    if _role_glue(lowered):
        return "Склейка ролей планет не является наблюдением о людях."
    metaphor = editorial_issue(lowered)
    if metaphor:
        return metaphor
    if polarity == "supportive" and any(token in lowered for token in _SUPPORTIVE_CONFLICT):
        return "Поддерживающая динамика не нуждается в выдуманном конфликте."
    if kind == "index":
        if "ограничено по глубине" in lowered:
            return "Пометка ограниченной глубины остаётся у fallback, готовое объяснение её не копирует."
        if factors and not _cites_factor(lowered, factors):
            return "Объяснение не опирается на переданные факторы."
        if value == 0 and _invented_planet(lowered, factors or [], omitted_factors or []):
            return "Нулевой индекс нельзя дополнять выдуманным транзитом или аспектом."
    return None


def _role_glue(lowered: str) -> bool:
    hits = [role for role in _ROLES if role in lowered]
    return len(hits) >= 3 and lowered.count(" и ") >= 2


def _cites_factor(lowered: str, factors: list[dict[str, Any]]) -> bool:
    for factor in factors:
        aspect = str(factor.get("aspect_ru") or "").casefold()
        if any(stem in aspect and stem in lowered for stem in _PLANET_STEMS):
            return True
    return False


def _invented_planet(lowered: str, factors: list[dict[str, Any]], omitted: list[str]) -> bool:
    allowed = " ".join(
        [str(factor.get("aspect_ru") or "") for factor in factors] + [str(item) for item in omitted]
    ).casefold()
    return any(stem in lowered and stem not in allowed for stem in _PLANET_STEMS)
