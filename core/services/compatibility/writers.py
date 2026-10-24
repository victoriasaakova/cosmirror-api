"""Тексты Bond и Signs через Polza. Chart и транзиты модель не пишет.

Ошибка одной секции оставляет её фактический текст. Поля модели и шаблона
в одной карточке не смешиваются. Groq для совместимости не вызывается.
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional

from core.services import llm_client
from core.services.llm_prompts import (
    PROMPT_COMPATIBILITY_BOND,
    PROMPT_COMPATIBILITY_SIGNS,
    load_prompt,
)

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

_PREAMBLE = (
    "Перед работой держи Cosmirror editorial: гипотеза, не приговор; опыт сначала; "
    "без прогнозов, диагнозов и судьбы. К одному человеку — «ты». "
    "О вас двоих — «вы», «вам», «вас», «между вами». "
    "Русский как у носителя. "
    "Грамматический род — только из reader.grammatical_gender.\n\n"
)

_BOND_CONTRACT = """\
Верни ТОЛЬКО JSON:
{"insights":[{"id":"","title":"","snapshot":"","summary":"","deep_read":"","share_text":""}]}

По одному объекту на каждый insight из входа. id копируй. category, evidence_ids,
орб и аспект не меняй и в ответ не добавляй. eyebrow не пиши: его соберёт код.
title — смысл связи, не строка из названий планет.
summary и deep_read не повторяют друг друга.
Не пиши даты, города, проценты, «суждено», «соулмейт».
Не описывай мысли и чувства человека B как установленный факт.
Имя B оставляй в именительном падеже. При grammatical_gender=unspecified не пиши «он», «она», «его», «её».
"""

_SIGNS_CONTRACT = """\
Верни ТОЛЬКО JSON:
{"comparisons":[{"id":"","meaning":"","common_ground":"","difference":""}]}

По одному объекту на каждое сравнение из входа. id копируй.
Знак, точку и cross_aspect_ids не меняй. Если cross_aspect_ids пуст, аспект не выдумывай.
Сравнивай два способа одной функции. Не читай мысли человека B.
Не пиши даты, города, проценты, «суждено», «соулмейт».
Имя B оставляй в именительном падеже. При grammatical_gender=unspecified не пиши «он», «она», «его», «её».
"""


def writers_settled(document: dict[str, Any]) -> bool:
    writers = _writers(document)
    if writers.get("bond") == "llm" and writers.get("signs") == "llm":
        return True
    provider = writers.get("provider")
    return provider not in (None, "", "polza") and writers.get("bond") == "fallback" and writers.get("signs") == "fallback"


def enrich_document(document: dict[str, Any]) -> dict[str, Any]:
    meta = document.setdefault("meta", {})
    writers = dict(_writers(document))
    provider = llm_client.active_provider()
    if provider != "polza":
        writers.setdefault("bond", "fallback")
        writers.setdefault("signs", "fallback")
        writers["provider"] = provider or "none"
        meta["writers"] = writers
        return document

    jobs = {}
    if writers.get("bond") != "llm":
        jobs["bond"] = _generate_bond
    if writers.get("signs") != "llm":
        jobs["signs"] = _generate_signs
    results: dict[str, Optional[dict[str, dict[str, str]]]] = {}
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


def _call(prompt_id: str, contract: str, facts: dict[str, Any], max_tokens: int) -> Optional[dict[str, Any]]:
    system = _PREAMBLE + load_prompt(prompt_id).body.strip() + "\n\n" + contract
    user = json.dumps(facts, ensure_ascii=False)
    try:
        return llm_client.chat_json(
            system=system,
            user=user,
            prompt_id=prompt_id,
            temperature=0.55,
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


def _banned(text: str) -> bool:
    lowered = text.casefold()
    return any(token in lowered for token in _BANNED)


def _writers(document: dict[str, Any]) -> dict[str, Any]:
    meta = document.get("meta") if isinstance(document.get("meta"), dict) else {}
    writers = meta.get("writers") if isinstance(meta, dict) else None
    return dict(writers) if isinstance(writers, dict) else {}


def _people(document: dict[str, Any]) -> tuple[dict[str, str], dict[str, str]]:
    persons = {
        row.get("id"): row
        for row in document.get("persons") or []
        if isinstance(row, dict)
    }
    person_a = persons.get("A") or {}
    person_b = persons.get("B") or {}
    return (
        {
            "id": "A",
            "display_name": str(person_a.get("display_name") or "Ты"),
            "grammatical_gender": "unspecified",
        },
        {
            "id": "B",
            "display_name": str(person_b.get("display_name") or "Партнёр"),
        },
    )


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
