"""Тексты Bond и Signs через Polza. Chart и транзиты модель не пишет.

Ошибка одной секции оставляет её фактический текст. Поля модели и шаблона
в одной карточке не смешиваются. Groq для совместимости не вызывается.
"""

from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional

from core.services import llm_client
from core.services.llm_prompts import (
    PROMPT_COMPATIBILITY_BOND,
    PROMPT_COMPATIBILITY_GOLD,
    PROMPT_COMPATIBILITY_CYCLES,
    PROMPT_COMPATIBILITY_DEEP_DIVE,
    PROMPT_COMPATIBILITY_INDICES,
    PROMPT_COMPATIBILITY_INSIGHT,
    PROMPT_COMPATIBILITY_SIGNS,
    load_prompt,
)

from .insight import basis_line, decline_name, ensure_insight, relevant_anchors
from .insight_select import EDITORIAL_VERSION, angle_for, claim_lists
from .quality import rejection_reason
from .story_plan import section_collides, writer_facts

logger = logging.getLogger(__name__)

_BOND_FIELDS = {
    "title": 8,
    "snapshot": 24,
    "summary": 40,
    "deep_read": 40,
    "share_text": 12,
}
_SIGNS_FIELDS = {
    "meaning": 40,
    "common_ground": 16,
    "difference": 16,
}
_BANNED = ("суждено", "соулмейт", "soulmate", "вы расстанетесь", "токсич", "%")

_NAME_RULE = (
    "Имена склоняй только формами из name_forms. Пустой падеж не выдумывай: "
    "имя остаётся подлежащим в именительном. "
    "Не пиши «с Максим», «Марс Максим», «между Виктория и Максим». "
    "При grammatical_gender=unspecified не пиши «он», «она», «его», «её»."
)

_BOND_CONTRACT = f"""\
Верни ТОЛЬКО JSON:
{{"insights":[{{"id":"","title":"","snapshot":"","summary":"","deep_read":"","share_text":""}}]}}

По одному объекту на каждый insight из входа. id копируй. category, evidence_ids,
орб и аспект не меняй и в ответ не добавляй. eyebrow не пиши: его соберёт код.
title — смысл связи, не строка из названий планет.
summary и deep_read не повторяют друг друга.
Не пиши даты, города, проценты, «суждено», «соулмейт».
Не описывай мысли и чувства человека B как установленный факт.
{_NAME_RULE}
"""

_SIGNS_CONTRACT = f"""\
Верни ТОЛЬКО JSON:
{{"comparisons":[{{"id":"","meaning":"","common_ground":"","difference":""}}]}}

По одному объекту на каждое сравнение из входа. id копируй.
Знак, точку и cross_aspect_ids не меняй. Если cross_aspect_ids пуст, аспект не выдумывай.
Сравнивай два способа одной функции. Не читай мысли человека B.
Не пиши даты, города, проценты, «суждено», «соулмейт».
{_NAME_RULE}
"""

_INSIGHT_CONTRACT = f"""\
Верни ТОЛЬКО JSON:
{{"headline":"","body":""}}

Тема уже выбрана. theme_id, evidence, орбы, natal_anchors и current_modifier не меняй и в текст не пересказывай.
headline — одна законченная мысль до 90 символов. body — 2–3 предложения, одна гипотеза, без списка аспектов.
Не переводи точки карты в функции. Запрещённый ход: «разговор помогает инициативе становиться делом», «один начинает, другой оформляет словами».
quality_hint_ru — единственный источник личной склонности. Пустой hint или пустой список: не приписывай характер.
angle_ru — направление мысли, не фраза для копирования. allowed_claims тоже не вставляй дословно.
Несколько якорей связывай только если они держат одну мысль.
polarity supportive может обойтись без «но». challenging — без вины и приговора. neutral — не сглаживай в комплимент и не сгущай в проблему.
status crush: без взаимности. dating: без статуса пары. together: повтор реакций, без обещания будущего. uncertain: без мотива другого. ended: без причины расставания и без прогноза возврата. status null: статус не выдумывай.
Если current_modifier равен null, не пиши «прямо сейчас», «сегодня», «в этот период», «в этом месяце».
Не описывай чувства, намерения и события как установленный факт.
Не заканчивай обязательной оговоркой «это гипотеза» или «это не вердикт».
{_NAME_RULE}
"""

_INSIGHT_BANNED = ("страх близости", "точно влюб")

_CURRENT_CLAIMS = ("прямо сейчас", "именно сейчас", "в этот период", "на этой неделе", "в этом месяце", "сегодня")
_LATIN_POINTS = (
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


def writers_settled(document: dict[str, Any]) -> bool:
    writers = _writers(document)
    bond = writers.get("bond")
    signs = writers.get("signs")
    insight = writers.get("insight")
    stages = all(
        writers.get(key) in {"llm", "fallback", "unavailable"}
        for key in ("deep_dive", "cycles", "indices")
        if key in writers or (key == "indices" and isinstance(document.get("scoring"), dict))
    )
    if bond == "llm" and signs == "llm" and insight in {"llm", "unavailable"} and stages:
        return True
    provider = writers.get("provider")
    return (
        provider not in (None, "", "polza")
        and bond == "fallback"
        and signs == "fallback"
        and insight in {"fallback", "unavailable"}
        and stages
    )


def enrich_document(document: dict[str, Any]) -> dict[str, Any]:
    ensure_insight(document)
    meta = document.setdefault("meta", {})
    writers = dict(_writers(document))
    provider = llm_client.active_provider()
    insight_status = (document.get("insight") or {}).get("status")
    if provider != "polza":
        writers.setdefault("bond", "fallback")
        writers.setdefault("signs", "fallback")
        writers["insight"] = "unavailable" if insight_status == "unavailable" else writers.get("insight") or "fallback"
        writers["deep_dive"] = writers.get("deep_dive") or "fallback"
        writers["cycles"] = writers.get("cycles") or "fallback"
        if isinstance(document.get("scoring"), dict):
            writers["indices"] = writers.get("indices") or "fallback"
        writers["provider"] = provider or "none"
        meta["writers"] = writers
        return document

    jobs = {}
    if writers.get("bond") != "llm":
        jobs["bond"] = _generate_bond
    if writers.get("signs") != "llm":
        jobs["signs"] = _generate_signs
    if insight_status == "unavailable":
        writers["insight"] = "unavailable"
    elif writers.get("insight") != "llm":
        jobs["insight"] = _generate_insight
    if document.get("deep_dive") and writers.get("deep_dive") != "llm":
        jobs["deep_dive"] = _generate_deep_dive
    if document.get("active_cycles") and writers.get("cycles") != "llm":
        jobs["cycles"] = _generate_cycles
    if isinstance(document.get("scoring"), dict) and writers.get("indices") != "llm":
        jobs["indices"] = _generate_indices
    results: dict[str, Any] = {}
    if jobs:
        with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
            futures = {key: pool.submit(fn, document) for key, fn in jobs.items()}
            for key, future in futures.items():
                try:
                    results[key] = future.result()
                except Exception:
                    logger.warning("Compatibility %s writer crashed", key)
                    results[key] = None
    if "bond" in results:
        payload = results["bond"]
        if payload is None:
            writers["bond"] = "fallback"
        else:
            if payload:
                _apply_texts(document["bond"]["insights"], payload)
            writers["bond"] = "llm"
    if "signs" in results:
        payload = results["signs"]
        if payload is None:
            writers["signs"] = "fallback"
        else:
            if payload:
                _apply_texts(document["signs"]["comparisons"], payload)
            writers["signs"] = "llm"
    if "insight" in results:
        payload = results["insight"]
        if not payload:
            writers["insight"] = "fallback"
        else:
            document["insight"]["title"] = payload["title"]
            document["insight"]["headline"] = payload["title"]
            document["insight"]["body"] = payload["body"]
            document["insight"]["source"] = "llm"
            document["insight"]["interpretation_depth"] = "full"
            writers["insight"] = "llm"
    if "deep_dive" in results:
        if results["deep_dive"] is not None:
            _apply_deep_dive(document, results["deep_dive"])
            failed = _deep_sections_pending(document)
            conclusion = (document.get("deep_dive") or {}).get("conclusion") or {}
            conclusion_pending = (
                isinstance(conclusion, dict)
                and conclusion.get("status") == "ready"
                and conclusion.get("source") != "llm"
            )
            if failed or conclusion_pending:
                retry = _generate_deep_dive(document, only_ids=failed, retry=True)
                if retry is not None:
                    _apply_deep_dive(document, retry)
            _enforce_unique_stories(document)
        writers["deep_dive"] = _deep_writer_status(document)
    if "cycles" in results:
        writers["cycles"] = "llm" if _apply_cycles(document, results["cycles"]) else "fallback"
    if "indices" in results:
        payload = results["indices"]
        if payload is not None:
            _apply_indices(document, payload)
            if not _indices_complete(document):
                retry = _generate_indices(document)
                if retry is not None:
                    _apply_indices(document, retry)
        writers["indices"] = "llm" if _indices_complete(document) else "fallback"
    writers["provider"] = "polza"
    meta["writers"] = writers
    return document


def bond_facts(document: dict[str, Any]) -> dict[str, Any]:
    reader, person_b = _people(document)
    aspects = _aspects_by_id(document)
    insights = []
    for insight in (document.get("bond") or {}).get("insights") or []:
        evidence = [item for item in insight.get("evidence_ids") or [] if item in aspects]
        primary = aspects.get(evidence[0]) if evidence else None
        insights.append(
            {
                "id": insight.get("id"),
                "category": insight.get("category"),
                "evidence_ids": list(insight.get("evidence_ids") or []),
                "aspect": _aspect_fact(primary) if primary else None,
            }
        )
    return {
        "reader": reader,
        "person_b": person_b,
        "relationship_type": document.get("relationship_type") or "romantic",
        "insights": insights,
    }


def signs_facts(document: dict[str, Any]) -> dict[str, Any]:
    reader, person_b = _people(document)
    comparisons = []
    for row in (document.get("signs") or {}).get("comparisons") or []:
        placements = row.get("pair_placements") or {}
        comparisons.append(
            {
                "id": row.get("id"),
                "point": row.get("point"),
                "A": _placement_fact(placements.get("A")),
                "B": _placement_fact(placements.get("B")),
                "cross_aspect_ids": list(row.get("cross_aspect_ids") or []),
            }
        )
    return {
        "reader": reader,
        "person_b": person_b,
        "comparisons": comparisons,
    }


def _generate_bond(document: dict[str, Any]) -> Optional[dict[str, dict[str, str]]]:
    insights = (document.get("bond") or {}).get("insights") or []
    if not insights:
        return {}
    raw = _call(PROMPT_COMPATIBILITY_BOND, _BOND_CONTRACT, bond_facts(document), 12000)
    if raw is None:
        return None
    return _validate_rows(raw.get("insights"), insights, _BOND_FIELDS)


def _generate_signs(document: dict[str, Any]) -> Optional[dict[str, dict[str, str]]]:
    rows = (document.get("signs") or {}).get("comparisons") or []
    if not rows:
        return {}
    raw = _call(PROMPT_COMPATIBILITY_SIGNS, _SIGNS_CONTRACT, signs_facts(document), 6000)
    if raw is None:
        return None
    return _validate_rows(raw.get("comparisons"), rows, _SIGNS_FIELDS)


def insight_facts(document: dict[str, Any]) -> dict[str, Any]:
    ensure_insight(document)
    reader, person_b = _people(document)
    slot = document.get("insight") if isinstance(document.get("insight"), dict) else {}
    aspects = _aspects_by_id(document)
    evidence = [aspects[item] for item in slot.get("evidence_ids") or [] if item in aspects]
    theme = str(slot.get("theme_id") or "")
    claims = claim_lists(theme) if theme else {"allowed_claims": [], "forbidden_claims": []}
    primary = evidence[0]["id"] if evidence else None
    context = _context(document)
    return {
        "relationship_context": context,
        "reader": reader,
        "other_person": person_b,
        "natal_anchors": relevant_anchors(document, evidence),
        "selection": {
            "theme_id": slot.get("theme_id"),
            "polarity": slot.get("polarity"),
            "selection_kind": "stable_synastry_pattern",
            "primary_evidence_id": primary,
            "supporting_evidence_ids": [row["id"] for row in evidence[1:]],
            "factor_count": len(evidence),
            "angle_ru": angle_for(theme, str(context.get("type") or "romantic"), context.get("status")),
            "scoring_version": slot.get("scoring_version"),
            **claims,
        },
        "astro_evidence": [_aspect_fact(row) for row in evidence],
        "current_modifier": None,
        "language": "ru",
        "editorial_version": EDITORIAL_VERSION,
    }


_DEEP_CONTRACT = f"""\
Верни ТОЛЬКО JSON:
{{"sections":[{{"id":"","headline":"","body":"","preview":""}}],"conclusion":{{"headline":"","body":""}}}}

Пиши только id из ready_section_ids. limited не заполняй. evidence_ids, section_title, story_plan и analysis не возвращай.
У каждой секции свой story_plan. Это внутреннее задание: не выводи его поля и не ставь подписи.
Пиши unique_mechanism и не пересказывай must_not_repeat.
body — 2 или 3 абзаца одной истории, между абзацами пустая строка.
Не возвращай perspectives, self, other, together, takeaway, person_a, person_b, summary, potential_or_meaning, conditions_or_limits.
headline не длиннее 90 символов. preview — одно предложение, не копия headline и не копия первого абзаца.
Не заканчивай body советом. Если conclusion.status не ready, conclusion верни null.
Заключение — один headline и один body. Не повторяй карточки из do_not_repeat.
{_NAME_RULE}
"""

_CYCLES_CONTRACT = f"""\
Верни ТОЛЬКО JSON:
{{"persons":{{"A":{{"headline":"","body":""}},"B":null}}}}

Ключ человека со status не ready опусти или верни null. Факты транзита не меняй и не возвращай.
body — два абзаца через пустую строку, одна связная интерпретация.
Не возвращай teaser, focus, sensitive_point, need, resource, relationship_lens, astrological_basis_ru.
{_NAME_RULE}
"""

_INDICES_CONTRACT = f"""\
Верни ТОЛЬКО JSON:
{{"indices":{{"harmony":{{"explanation":""}},"karmic_patterns":{{"explanation":""}},"current_tension":{{"explanation":""}},"transformation":{{"explanation":""}}}}}}

Пиши только ключи из входа. value не возвращай и не изменяй.
explanation — 2–4 предложения. Опирайся на top_factors и не копируй учебные примеры.
{_NAME_RULE}
"""


def _context(document: dict[str, Any]) -> dict[str, Any]:
    raw = document.get("relationship_context") if isinstance(document.get("relationship_context"), dict) else {}
    return {
        "type": raw.get("type") or document.get("relationship_type") or "romantic",
        "status": raw.get("status"),
        "family_role": raw.get("family_role"),
        "user_question": raw.get("user_question"),
        "confirmed_events": [],
    }


def _generate_deep_dive(
    document: dict[str, Any],
    *,
    only_ids: Optional[set[str]] = None,
    retry: bool = False,
) -> Optional[dict[str, Any]]:
    deep = document.get("deep_dive") if isinstance(document.get("deep_dive"), dict) else {}
    sections = [row for row in deep.get("sections") or [] if isinstance(row, dict) and row.get("status") == "ready"]
    if only_ids is not None:
        sections = [row for row in sections if row.get("id") in only_ids]
    ready = [row["id"] for row in sections]
    conclusion = deep.get("conclusion") if isinstance(deep.get("conclusion"), dict) else {}
    if not ready and conclusion.get("status") != "ready":
        return {}
    reader, other = _people(document)
    accepted = _accepted_stories(deep.get("sections") or []) if retry else []
    facts = {
        "relationship_context": _context(document),
        "reader": reader,
        "other_person": other,
        "ready_section_ids": ready,
        "sections": [_section_facts(row, document) for row in sections],
        "conclusion": (
            _conclusion_facts(document, conclusion, deep.get("sections") or [])
            if conclusion.get("status") == "ready" and conclusion.get("source") != "llm"
            else None
        ),
        "already_accepted": accepted,
        "retry_reason": (
            "Предыдущий текст не принят: фраза не называет понятное переживание, потребность, реакцию или ситуацию. "
            "Перепиши ту же ситуацию из unique_mechanism и натальных опор. Не добавляй новые аспекты и качества. "
            "Не копируй пометку об ограниченной глубине и не используй пустые метафоры хода, контура, веса, ставки и масштаба. "
            "При grammatical_gender=unspecified не пиши «он», «она», «его», «её»."
            if retry
            else None
        ),
        "insight_theme_id": (document.get("insight") or {}).get("theme_id"),
        "language": "ru",
        "editorial_version": EDITORIAL_VERSION,
    }
    for row, payload in zip(sections, facts["sections"]):
        analysis = row.setdefault("analysis", {})
        if isinstance(analysis, dict):
            analysis["writer_payload"] = {
                "relationship_context": facts["relationship_context"],
                "reader": reader,
                "other_person": other,
                "section": payload,
                "already_accepted": accepted,
                "retry_reason": facts["retry_reason"],
            }
    raw = _call(PROMPT_COMPATIBILITY_DEEP_DIVE, _DEEP_CONTRACT, facts, 8000, temperature=0.4)
    if raw is None:
        return None
    return raw if isinstance(raw, dict) else None


def _section_facts(row: dict[str, Any], document: dict[str, Any]) -> dict[str, Any]:
    facts = writer_facts(row)
    analysis = row.get("analysis") if isinstance(row.get("analysis"), dict) else {}
    evidence = analysis.get("evidence") if isinstance(analysis.get("evidence"), dict) else {}
    facts["natal_anchors"] = relevant_anchors(
        document,
        [
            {
                "person_a_point": evidence.get("point_a"),
                "person_b_point": evidence.get("point_b"),
            }
        ],
    )
    facts["cross_aspect"] = {
        "point_a": evidence.get("point_a"),
        "point_b": evidence.get("point_b"),
        "aspect": evidence.get("aspect"),
        "basis_ru": (analysis.get("cross_evidence_ru") or [None])[0],
    }
    return facts


def _conclusion_facts(
    document: dict[str, Any],
    conclusion: dict[str, Any],
    sections: list[Any],
) -> dict[str, Any]:
    aspects = _aspects_by_id(document)
    reader, other = _people(document)
    evidence = []
    for evidence_id in conclusion.get("evidence_ids") or []:
        row = aspects.get(evidence_id)
        if not row:
            continue
        fact = _aspect_fact(row)
        fact["basis_ru"] = basis_line(
            str(row.get("person_a_point") or ""),
            reader["display_name"],
            str(row.get("aspect") or ""),
            str(row.get("person_b_point") or ""),
            other["display_name"],
        )
        evidence.append(fact)
    headlines = [
        row.get("headline")
        for row in sections
        if isinstance(row, dict) and row.get("headline")
    ]
    return {
        "status": conclusion.get("status"),
        "variant": conclusion.get("variant"),
        "fixed_section_title": "Главное о вашей связи",
        "evidence": evidence,
        "do_not_repeat": headlines,
    }


def _accepted_stories(sections: list[Any]) -> list[dict[str, Any]]:
    accepted = []
    for row in sections:
        if not isinstance(row, dict) or row.get("writer") != "polza":
            continue
        plan = ((row.get("analysis") or {}).get("story_plan") or {}) if isinstance(row.get("analysis"), dict) else {}
        accepted.append(
            {
                "id": row.get("id"),
                "headline": row.get("headline"),
                "central_claim": plan.get("central_claim"),
                "unique_mechanism": plan.get("unique_mechanism"),
            }
        )
    return accepted


def _deep_sections_pending(document: dict[str, Any]) -> set[str]:
    deep = document.get("deep_dive") if isinstance(document.get("deep_dive"), dict) else {}
    return {
        str(row.get("id"))
        for row in deep.get("sections") or []
        if isinstance(row, dict) and row.get("status") == "ready" and row.get("writer") != "polza"
    }


def _generate_cycles(document: dict[str, Any]) -> Optional[dict[str, Any]]:
    cycles = document.get("active_cycles") if isinstance(document.get("active_cycles"), dict) else {}
    persons = cycles.get("persons") if isinstance(cycles.get("persons"), dict) else {}
    reader, other = _people(document)
    names = {"A": reader, "B": other}
    ready = {
        person_id: {
            "display_name": names[person_id]["display_name"],
            "address": "ты" if person_id == "A" else names[person_id]["display_name"],
            "facts": row.get("facts"),
            "basis_ru": ((row.get("interpretation") or {}) if isinstance(row.get("interpretation"), dict) else {}).get(
                "astrological_basis_ru"
            ),
            "status": row.get("status"),
        }
        for person_id, row in persons.items()
        if isinstance(row, dict) and row.get("status") == "ready" and person_id in names
    }
    if not ready:
        return {}
    raw = _call(
        PROMPT_COMPATIBILITY_CYCLES,
        _CYCLES_CONTRACT,
        {"relationship_context": _context(document), "persons": ready, "as_of_utc": cycles.get("as_of_utc")},
        4000,
    )
    if raw is None:
        return None
    return raw if isinstance(raw, dict) else None


_INDEX_KEYS = ("harmony", "karmic_patterns", "current_tension", "transformation")


def _generate_indices(document: dict[str, Any]) -> Optional[dict[str, Any]]:
    indices = _index_payload(document)
    if not indices:
        return {}
    reader, other = _people(document)
    raw = _call(
        PROMPT_COMPATIBILITY_INDICES,
        _INDICES_CONTRACT,
        {
            "relationship_context": _context(document),
            "reader": reader,
            "other_person": other,
            "indices": indices,
            "omitted_factors": (document.get("scoring") or {}).get("omitted_factors") or [],
        },
        4000,
        temperature=0.4,
    )
    if raw is None:
        return None
    return raw if isinstance(raw, dict) else None


def _index_payload(document: dict[str, Any]) -> dict[str, Any]:
    scoring = document.get("scoring") if isinstance(document.get("scoring"), dict) else {}
    payload = {}
    for key in _INDEX_KEYS:
        row = scoring.get(key)
        if not _index_open(row):
            continue
        payload[key] = {
            "value": row.get("value"),
            "status": row.get("status"),
            "confidence": row.get("confidence"),
            "top_factors": row.get("top_factors") or [],
            "reference_instant_utc": row.get("reference_instant_utc"),
        }
    return payload


def _index_open(row: Any) -> bool:
    return (
        isinstance(row, dict)
        and isinstance(row.get("value"), int)
        and row.get("status") in {"ready", "limited"}
        and row.get("interpretation_depth") != "full"
    )


def _apply_indices(document: dict[str, Any], payload: Any) -> bool:
    if payload == {}:
        return _indices_complete(document)
    if not isinstance(payload, dict):
        return False
    rows = payload.get("indices") if isinstance(payload.get("indices"), dict) else {}
    scoring = document.get("scoring") if isinstance(document.get("scoring"), dict) else {}
    omitted = scoring.get("omitted_factors") if isinstance(scoring.get("omitted_factors"), list) else []
    for key in _INDEX_KEYS:
        row = scoring.get(key)
        if not _index_open(row):
            continue
        text = _index_explanation(rows.get(key), row, omitted, document)
        if text is None:
            continue
        row["summary"] = text
        row["interpretation_depth"] = "full"
    return _indices_complete(document)


def _indices_complete(document: dict[str, Any]) -> bool:
    scoring = document.get("scoring") if isinstance(document.get("scoring"), dict) else {}
    return not any(_index_open(scoring.get(key)) for key in _INDEX_KEYS)


def _index_explanation(
    raw: Any,
    row: dict[str, Any],
    omitted: list[Any],
    document: dict[str, Any],
) -> Optional[str]:
    if not isinstance(raw, dict):
        return None
    value = raw.get("explanation")
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    if not 80 <= len(text) <= 520:
        return None
    if _banned(text) or _latin_point(text) or _person_label(text):
        return None
    if re_banned_context(document, text.casefold()):
        return None
    if rejection_reason(
        text,
        kind="index",
        factors=row.get("top_factors") if isinstance(row.get("top_factors"), list) else [],
        value=row.get("value") if isinstance(row.get("value"), int) else None,
        omitted_factors=[str(item) for item in omitted],
    ):
        return None
    return text


def _apply_deep_dive(document: dict[str, Any], payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    applied = False
    accepted: list[str] = []
    sections = {
        row.get("id"): row
        for row in (document.get("deep_dive") or {}).get("sections") or []
        if isinstance(row, dict)
    }
    for raw in payload.get("sections") or []:
        if not isinstance(raw, dict):
            continue
        section = sections.get(raw.get("id"))
        if not section or section.get("status") != "ready" or section.get("writer") == "polza":
            continue
        text = _deep_section_text(raw, document)
        if text is None:
            continue
        others = [row for row in sections.values() if isinstance(row, dict) and row.get("id") != section.get("id")]
        if section_collides(text["body"], section, others):
            continue
        if _has_repeat(accepted + [text["headline"], text["body"]]):
            continue
        section["headline"] = text["headline"]
        section["body"] = text["body"]
        section["preview"] = text["preview"]
        section["source"] = "llm"
        section["writer"] = "polza"
        section["interpretation_depth"] = "full"
        section["confidence"] = "full"
        for key in ("perspectives", "takeaway", "title", "teaser"):
            section.pop(key, None)
        accepted.extend((text["headline"], text["body"]))
        applied = True
    conclusion = (document.get("deep_dive") or {}).get("conclusion")
    if isinstance(conclusion, dict) and conclusion.get("status") == "ready":
        text = _conclusion_text(payload.get("conclusion"), document)
        if text is not None:
            conclusion["headline"] = text["headline"]
            conclusion["body"] = text["body"]
            conclusion["summary"] = text["body"]
            conclusion["potential_or_meaning"] = None
            conclusion["conditions_or_limits"] = None
            conclusion["source"] = "llm"
            conclusion["interpretation_depth"] = "full"
            applied = True
    return applied


def _enforce_unique_stories(document: dict[str, Any]) -> None:
    deep = document.get("deep_dive") if isinstance(document.get("deep_dive"), dict) else {}
    sections = [row for row in deep.get("sections") or [] if isinstance(row, dict)]
    ready = [row for row in sections if row.get("status") == "ready" and row.get("body")]
    demote: set[str] = set()
    for index, left in enumerate(ready):
        for right in ready[index + 1 :]:
            left_bad = section_collides(str(left.get("body") or ""), left, [right])
            right_bad = section_collides(str(right.get("body") or ""), right, [left])
            if not left_bad and not right_bad:
                continue
            if right.get("writer") != "polza":
                demote.add(str(right.get("id")))
            elif left.get("writer") != "polza":
                demote.add(str(left.get("id")))
            elif right_bad:
                demote.add(str(right.get("id")))
            else:
                demote.add(str(left.get("id")))
    for section in sections:
        if str(section.get("id")) not in demote:
            continue
        section["status"] = "limited"
        section["headline"] = None
        section["body"] = None
        section["preview"] = "Отдельный механизм этой темы не отделился от соседней карточки."
        section["source"] = "fallback"
        section["writer"] = "fallback"
    still_ready = sum(1 for section in sections if section.get("status") == "ready")
    if sections:
        deep["status"] = "ready" if still_ready == 4 else "partial" if still_ready else "limited"


def _deep_writer_status(document: dict[str, Any]) -> str:
    deep = document.get("deep_dive") if isinstance(document.get("deep_dive"), dict) else {}
    units = [
        row.get("source")
        for row in deep.get("sections") or []
        if isinstance(row, dict) and row.get("status") == "ready"
    ]
    conclusion = deep.get("conclusion") if isinstance(deep.get("conclusion"), dict) else {}
    if conclusion.get("status") == "ready":
        units.append(conclusion.get("source"))
    if units and all(source == "llm" for source in units):
        return "llm"
    return "fallback"


def _apply_cycles(document: dict[str, Any], payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    persons = payload.get("persons") if isinstance(payload.get("persons"), dict) else {}
    applied = False
    stored = (document.get("active_cycles") or {}).get("persons") or {}
    for person_id, row in stored.items():
        if not isinstance(row, dict) or row.get("status") != "ready":
            continue
        text = _cycle_text(persons.get(person_id), document)
        if text is None:
            continue
        basis = ""
        current = row.get("interpretation")
        if isinstance(current, dict):
            basis = str(current.get("astrological_basis_ru") or "")
        row["interpretation"] = {
            "headline": text["headline"],
            "body": text["body"],
            "astrological_basis_ru": basis,
            "interpretation_depth": "full",
        }
        row["source"] = "llm"
        applied = True
    return applied


_DEEP_GENERIC = (
    "вам важно понимать",
    "важно понимать друг друга",
    "оставлять пространство",
    "пространство для каждого",
    "вдохновлять друг друга",
    "можете вдохновлять",
    "особое ощущение",
    "один проявляет инициативу",
    "другой реагирует",
    "потребности могут различаться",
    "важно находить баланс",
    "уважать границы друг друга",
    "работать над собой",
    "многому научиться друг у друга",
    "энергия вашей связи",
    "особенные вибрации",
)
_DEEP_LABEL = re.compile(
    r"(?:^|\n)\s*(?:ты|другой человек|между вами|инсайт)\s*[:.—–-]\s",
    re.IGNORECASE,
)


def _deep_section_text(raw: dict[str, Any], document: dict[str, Any]) -> Optional[dict[str, Any]]:
    if any(key in raw for key in ("perspectives", "takeaway", "person_a", "person_b", "together")):
        return None
    headline = _deep_line(raw.get("headline"), 90, document, minimum=16)
    body = _deep_body(raw.get("body"), document)
    preview = _deep_line(raw.get("preview"), 140, document, minimum=24)
    if headline is None or body is None or preview is None:
        return None
    if _similar(headline, preview) or _similar(preview, body.split("\n", 1)[0]):
        return None
    if headline in body:
        return None
    return {"headline": headline, "body": body, "preview": preview}


def _deep_body(value: Any, document: dict[str, Any]) -> Optional[str]:
    if not isinstance(value, str):
        return None
    paragraphs = [re.sub(r"\s+", " ", part).strip() for part in re.split(r"\n\s*\n", value)]
    paragraphs = [part for part in paragraphs if part]
    if not 2 <= len(paragraphs) <= 3:
        return None
    if re.match(
        r"^(важно|стоит|нужно|попробуй|попробуйте|имеет смысл|вам стоит|вам важно)\b",
        paragraphs[-1].casefold(),
    ):
        return None
    body = "\n\n".join(paragraphs)
    if not 280 <= len(body) <= 1200:
        return None
    if _deep_rejected(body, document):
        return None
    return body


def _deep_line(value: Any, limit: int, document: dict[str, Any], *, minimum: int) -> Optional[str]:
    if not isinstance(value, str):
        return None
    text = re.sub(r"\s+", " ", value).strip()
    if not minimum <= len(text) <= limit or "\n" in text:
        return None
    if _deep_rejected(text, document):
        return None
    return text


def _deep_rejected(text: str, document: dict[str, Any]) -> bool:
    lowered = text.casefold()
    if any(token in lowered for token in _BANNED) or any(token in lowered for token in _DEEP_GENERIC):
        return True
    if _DEEP_LABEL.search(text):
        return True
    if rejection_reason(text, kind="deep_dive"):
        return True
    if re_banned_context(document, lowered):
        return True
    if re.search(r"\b(sun|moon|mercury|venus|mars|jupiter|saturn|uranus|neptune|pluto)\b", lowered):
        return True
    if any(token in lowered for token in ("ему чув", "ей чув", "он чув", "она чув", "он хочет", "она хочет", "он ощущ", "она ощущ")):
        return True
    if re.search(r"(?:^|\s)[abб](?:$|[\s.,:;])", lowered):
        return True
    return _bad_name_case(text, document)


def _bad_name_case(text: str, document: dict[str, Any]) -> bool:
    reader, other = _people(document)
    for person in (reader, other):
        forms = person.get("name_forms") if isinstance(person.get("name_forms"), dict) else {}
        nominative = str(forms.get("nominative") or "")
        genitive = forms.get("genitive")
        if not nominative or not genitive or genitive == nominative:
            continue
        if re.search(rf"\b[УуСс]\s+{re.escape(nominative)}\b", text):
            return True
        if re.search(rf"\bмежду\s+{re.escape(nominative)}\b", text, re.IGNORECASE):
            return True
    return False


def _conclusion_text(raw: Any, document: dict[str, Any]) -> Optional[dict[str, str]]:
    if not isinstance(raw, dict):
        return None
    headline = _deep_line(raw.get("headline"), 120, document, minimum=16)
    body = _cohesive(raw.get("body"), document, minimum=80, maximum=700)
    if headline is None or body is None:
        return None
    if rejection_reason(f"{headline} {body}", kind="conclusion"):
        return None
    return {"headline": headline, "body": body}


def _cycle_text(raw: Any, document: dict[str, Any]) -> Optional[dict[str, str]]:
    if not isinstance(raw, dict):
        return None
    if any(key in raw for key in ("focus", "sensitive_point", "need", "resource")):
        return None
    headline = _deep_line(raw.get("headline"), 110, document, minimum=16)
    body = _cohesive(raw.get("body"), document, minimum=160, maximum=900)
    if headline is None or body is None or body.count("\n\n") != 1:
        return None
    if rejection_reason(f"{headline} {body}", kind="cycle"):
        return None
    return {"headline": headline, "body": body}


def _cohesive(value: Any, document: dict[str, Any], *, minimum: int, maximum: int) -> Optional[str]:
    if not isinstance(value, str):
        return None
    paragraphs = [re.sub(r"\s+", " ", part).strip() for part in re.split(r"\n\s*\n", value)]
    paragraphs = [part for part in paragraphs if part]
    if not paragraphs:
        return None
    body = "\n\n".join(paragraphs)
    if not minimum <= len(body) <= maximum:
        return None
    if _deep_rejected(body, document):
        return None
    return body


def _prose(value: Any, limit: int, document: dict[str, Any]) -> Optional[str]:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    if len(text) < 12 or len(text) > limit:
        return None
    lowered = text.lower()
    if any(token in lowered for token in _BANNED):
        return None
    if re_banned_context(document, lowered):
        return None
    if re.search(r"\b(sun|moon|mercury|venus|mars|jupiter|saturn|uranus|neptune|pluto)\b", lowered):
        return None
    if any(token in lowered for token in ("ему чув", "ей чув", "он чув", "она чув", "он хочет", "она хочет", "он ощущ", "она ощущ")):
        return None
    if any(
        token in lowered
        for token in ("функци", "энерги", "подхватыва", "карта указывает")
    ):
        return None
    if re.search(r"(?:^|\s)[abб](?:$|[\s.,:;])", lowered):
        return None
    return text


def _has_repeat(fields: list[str]) -> bool:
    kept = [field for field in fields if field]
    for index, left in enumerate(kept):
        for right in kept[index + 1 :]:
            if _similar(left, right):
                return True
    return False


def _similar(left: str, right: str) -> bool:
    words_left = set(_content_words(left))
    words_right = set(_content_words(right))
    if not words_left or not words_right:
        return False
    overlap = len(words_left & words_right) / len(words_left | words_right)
    if overlap >= 0.55:
        return True
    phrase_left = " ".join(_content_words(left))
    phrase_right = " ".join(_content_words(right))
    return (len(phrase_left) > 24 and phrase_left in phrase_right) or (
        len(phrase_right) > 24 and phrase_right in phrase_left
    )


def _content_words(text: str) -> list[str]:
    stop = {
        "или",
        "как",
        "где",
        "что",
        "это",
        "здесь",
        "может",
        "могут",
        "могла",
        "могло",
        "быть",
        "для",
        "при",
        "над",
        "под",
        "без",
        "его",
        "её",
        "нее",
        "него",
        "тебя",
        "тебе",
        "один",
        "одному",
    }
    return [token for token in re.findall(r"[а-яё]+", text.lower()) if len(token) > 3 and token not in stop]


def re_banned_context(document: dict[str, Any], lowered: str) -> bool:
    context = _context(document)
    kind = context.get("type")
    status = context.get("status")
    if kind in {"friendship", "family"} and any(token in lowered for token in ("сексу", "поцел", "влюб", "романт")):
        return True
    if status in {"ended", "no_contact"} and any(
        token in lowered for token in ("вернёт", "вернется", "воссоедин", "помири", "будет развиваться")
    ):
        return True
    return False


def _generate_insight(document: dict[str, Any]) -> Optional[dict[str, str]]:
    slot = document.get("insight") if isinstance(document.get("insight"), dict) else {}
    if slot.get("status") != "ready":
        return {}
    raw = _call(PROMPT_COMPATIBILITY_INSIGHT, _INSIGHT_CONTRACT, insight_facts(document), 2500)
    if raw is None:
        return None
    return _validate_insight(raw, slot, document)


def _call(
    prompt_id: str,
    contract: str,
    facts: dict[str, Any],
    max_tokens: int,
    *,
    temperature: float = 0.55,
) -> Optional[dict[str, Any]]:
    parts = [load_prompt(PROMPT_COMPATIBILITY_GOLD).body.strip()]
    parts.append(load_prompt(prompt_id).body.strip())
    parts.append(contract)
    system = "\n\n".join(parts)
    user = json.dumps(facts, ensure_ascii=False)
    try:
        return llm_client.chat_json(
            system=system,
            user=user,
            prompt_id=prompt_id,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except llm_client.LLMError as exc:
        logger.warning("Compatibility %s writer failed: %s", prompt_id, type(exc).__name__)
        return None


def _validate_rows(
    raw_rows: Any,
    expected_rows: list[dict[str, Any]],
    fields: dict[str, int],
) -> Optional[dict[str, dict[str, str]]]:
    if not isinstance(raw_rows, list):
        return None
    by_id: dict[str, dict[str, Any]] = {}
    for row in raw_rows:
        if isinstance(row, dict) and isinstance(row.get("id"), str):
            by_id[row["id"]] = row
    texts: dict[str, dict[str, str]] = {}
    for row in expected_rows:
        item = by_id.get(row.get("id"))
        if item is None:
            return None
        parsed: dict[str, str] = {}
        for key, minimum in fields.items():
            value = item.get(key)
            if not isinstance(value, str):
                return None
            cleaned = " ".join(value.split())
            if len(cleaned) < minimum:
                return None
            parsed[key] = cleaned
        if _banned(" ".join(parsed.values())):
            return None
        texts[str(row["id"])] = parsed
    return texts


def _apply_texts(rows: list[dict[str, Any]], texts: dict[str, dict[str, str]]) -> None:
    for index, row in enumerate(rows):
        fields = texts.get(row.get("id"))
        if not fields:
            continue
        updated = dict(row)
        updated.update(fields)
        rows[index] = updated


def _validate_insight(raw: Any, slot: dict[str, Any], document: Optional[dict[str, Any]] = None) -> Optional[dict[str, str]]:
    if not isinstance(raw, dict):
        return None
    title = raw.get("headline") if isinstance(raw.get("headline"), str) else raw.get("title")
    body = raw.get("body")
    if not isinstance(title, str) or not isinstance(body, str):
        return None
    title = " ".join(title.split())
    body = " ".join(body.split())
    if not 16 <= len(title) <= 90 or not 120 <= len(body) <= 420:
        return None
    text = f"{title} {body}"
    if _banned(text) or _insight_banned(text) or _latin_point(text) or _person_label(text) or _russian_planet(text):
        return None
    if rejection_reason(text, kind="insight", polarity=str(slot.get("polarity") or "") or None):
        return None
    if document is not None and re_banned_context(document, text.casefold()):
        return None
    if slot.get("temporal_frame") != "current" and any(claim in text.casefold() for claim in _CURRENT_CLAIMS):
        return None
    return {"title": title, "body": body}


_RU_PLANET = re.compile(
    r"(?<![а-яё])(?:солнц\w*|лун\w*|меркур\w*|венер\w*|марс\w*|юпитер\w*|сатурн\w*|уран\w*|нептун\w*|плутон\w*|асцендент\w*)(?![а-яё])",
    re.IGNORECASE,
)


def _russian_planet(text: str) -> bool:
    return _RU_PLANET.search(text) is not None


def _insight_banned(text: str) -> bool:
    lowered = text.casefold()
    return any(token in lowered for token in _INSIGHT_BANNED)


def _banned(text: str) -> bool:
    lowered = text.casefold()
    return any(token in lowered for token in _BANNED)


def _latin_point(text: str) -> bool:
    tokens = set(text.casefold().replace("«", " ").replace("»", " ").split())
    return any(point in tokens for point in _LATIN_POINTS)


def _person_label(text: str) -> bool:
    tokens = set(text.replace("«", " ").replace("»", " ").split())
    return "A" in tokens or "B" in tokens


def _writers(document: dict[str, Any]) -> dict[str, Any]:
    meta = document.get("meta") if isinstance(document.get("meta"), dict) else {}
    writers = meta.get("writers") if isinstance(meta, dict) else None
    return dict(writers) if isinstance(writers, dict) else {}


def _people(document: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    persons = {
        row.get("id"): row
        for row in document.get("persons") or []
        if isinstance(row, dict)
    }
    person_a = persons.get("A") or {}
    person_b = persons.get("B") or {}
    name_a = str(person_a.get("display_name") or "Ты").strip() or "Ты"
    name_b = str(person_b.get("display_name") or "Другой человек").strip() or "Другой человек"
    return (
        {
            "id": "A",
            "person_id": "A",
            "display_name": name_a,
            "grammatical_gender": _gender(person_a),
            "name_forms": _name_forms(name_a),
        },
        {
            "id": "B",
            "person_id": "B",
            "display_name": name_b,
            "grammatical_gender": _gender(person_b),
            "name_forms": _name_forms(name_b),
        },
    )


def _gender(person: dict[str, Any]) -> str:
    gender = person.get("grammatical_gender")
    if gender not in {"feminine", "masculine"}:
        return "unspecified"
    return gender


def _name_forms(name: str) -> dict[str, Optional[str]]:
    return decline_name(name)


def _aspects_by_id(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    chart = document.get("chart") if isinstance(document.get("chart"), dict) else {}
    rows = chart.get("cross_aspects") if isinstance(chart, dict) else []
    return {
        row["id"]: row
        for row in rows or []
        if isinstance(row, dict) and isinstance(row.get("id"), str)
    }


def _aspect_fact(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "person_a_point": row.get("person_a_point"),
        "person_b_point": row.get("person_b_point"),
        "aspect": row.get("aspect"),
        "orb_deg": row.get("orb_deg"),
        "sign_a": row.get("sign_a"),
        "sign_b": row.get("sign_b"),
        "quality": row.get("quality"),
    }


def _placement_fact(row: Any) -> dict[str, Any]:
    if not isinstance(row, dict):
        return {}
    return {"sign": row.get("sign"), "degree": row.get("degree")}
