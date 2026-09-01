"""Teaser copy for locked report tabs. Not the paid reading."""

from __future__ import annotations

from typing import Any

from core.services.cabinet import LOCKED_SECTIONS, session_for_user
from core.services.report import natal_from_session, natal_from_user
from core.services.report_types import (
    SECTION_ASPECTS,
    SECTION_CYCLES,
    SECTION_NATAL,
    SECTION_PRACTICE,
    SECTION_REQUEST,
)


def locked_preview_payload(user, section: str) -> dict[str, Any] | None:
    if section not in LOCKED_SECTIONS:
        return None
    session = session_for_user(user)
    natal = natal_from_session(session) if session else natal_from_user(user)
    if not natal.get("planets"):
        return None
    cards = _cards_for(section, natal)
    return {
        "section": section,
        "cards": [{"title": title, "text": text} for title, text in cards],
    }


def _point(natal: dict[str, Any], key: str) -> dict[str, Any]:
    planets = natal.get("planets") if isinstance(natal.get("planets"), dict) else {}
    row = planets.get(key) if isinstance(planets, dict) else None
    if isinstance(row, dict):
        return row
    if key == "ascendant" and isinstance(natal.get("ascendant"), dict):
        return natal["ascendant"]
    return {}


def _sign_ru(natal: dict[str, Any], key: str) -> str:
    row = _point(natal, key)
    return str(row.get("sign_ru") or row.get("sign") or "карте")


def _cards_for(section: str, natal: dict[str, Any]) -> list[tuple[str, str]]:
    sun = _sign_ru(natal, "sun")
    moon = _sign_ru(natal, "moon")
    mercury = _sign_ru(natal, "mercury")
    venus = _sign_ru(natal, "venus")
    mars = _sign_ru(natal, "mars")
    saturn = _sign_ru(natal, "saturn")
    if section == SECTION_NATAL:
        return [
            ("Солнце и Луна", f"Солнце в знаке {sun} и Луна в знаке {moon} задают тон характера. Полный слой читает, как это уже живёт в привычках."),
            ("Как ты входишь в ситуации", f"Марс в знаке {mars} и Венера в знаке {venus} показывают волю и близость. Здесь раскрывается, где карта отвечает, а не таблица положений."),
            ("Где опора", f"Меркурий в знаке {mercury} и Сатурн в знаке {saturn} держат мысль и предел. Разбор собирает это в связный текст, а не в список фактов."),
            ("Сквозная тема", "После оплаты появляется чтение карты целиком: где трение, где ресурс, что стоит проверить на своём опыте."),
        ]
    if section == SECTION_ASPECTS:
        return [
            ("Связи внутри карты", f"Солнце в знаке {sun} и Луна в знаке {moon} уже сцеплены. В полном разборе видно, где это трение, а где опора."),
            ("Напряжение", f"Марс в знаке {mars} и Сатурн в знаке {saturn} задают ритм усилия. Здесь открывается, какую цену ты платишь за контроль."),
            ("Ресурс", f"Меркурий в знаке {mercury} подсказывает, как эта связка может работать мягче, если не давить на привычный сценарий."),
            ("Как это читать", "Полный слой показывает конкретные аспекты, орбы и то, как две темы уже живут вместе — не как прогноз, а как гипотеза для проверки."),
        ]
    if section == SECTION_CYCLES:
        return [
            ("Что звучит сейчас", f"Текущее небо касается твоей Луны в знаке {moon} и Солнца в знаке {sun}. В разборе — какие циклы выходят на первый план."),
            ("Длительность", "У каждого транзита своё окно. Полный отчёт показывает, что уже началось, что длится месяцами, а что только набирает силу."),
            ("Как с этим быть", f"Сатурн в знаке {saturn} задаёт фон ответственности. Здесь раскрывается, где лучше опереться, а где не стоит форсировать."),
            ("Практика периода", "После оплаты видно не только «что происходит», но и как наблюдать это в конкретных ситуациях ближайших недель."),
        ]
    if section == SECTION_REQUEST:
        return [
            ("Твой запрос", f"Вопрос из квиза пересекается с Солнцем в знаке {sun} и Венерой в знаке {venus}. Полный слой собирает это в одну нить."),
            ("Где карта отвечает", "Мы не угадываем события. Показываем, какие темы карты уже держат этот вопрос — и где он может быть шире, чем кажется."),
            ("Отличие", f"Луна в знаке {moon} часто тянет к знакомому ответу. Разбор отделяет привычную защиту от того, что ты на самом деле спрашиваешь."),
            ("Вывод", "После оплаты здесь появляется связка запроса, карты и текущего периода — чтобы не размазывать вопрос на всё сразу."),
        ]
    if section == SECTION_PRACTICE:
        return [
            ("С чего начать", f"Практика опирается на Солнце в знаке {sun}: не совет «стань другим», а маленький эксперимент в привычной теме."),
            ("Паттерн", f"Луна в знаке {moon} подсказывает, какую защиту ты уже умеешь включать. Разбор показывает её цену и более гибкий жест."),
            ("Вопросы", f"Меркурий в знаке {mercury} задаёт тон наблюдения. Здесь будут вопросы, с которыми стоит пожить несколько дней, а не «решить всё сразу»."),
            ("Эксперимент", "Полный слой собирает одно конкретное действие, срок и то, на что смотреть — без обещания, что жизнь изменится за ночь."),
        ]
    return []
