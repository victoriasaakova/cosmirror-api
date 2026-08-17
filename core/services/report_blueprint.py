"""
Сборка каркаса отчёта: факты + акценты + пустой интерпретационный слой + промпт.

LLM здесь не вызывается. `generation.payload` — то, что позже уйдёт в модель.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from core.services.report_accents import quiz_profile, select_accents
from core.services.report_facts import (
    collective_sky,
    houses_table,
    method_block,
    natal_aspects,
    natal_table,
    transits_now,
)
from core.services.report_lexicon import WORK_WITH
from core.services.report_types import (
    PDF_OUTLINE,
    SCHEMA_VERSION,
    SECTION_METHOD,
    SECTION_NATAL,
    SECTION_NOW,
    SECTION_PERIODS,
    SECTION_PRACTICE,
    SECTION_REQUEST,
    SYSTEM_PROMPT_ID,
    WEB_TABS,
)

_PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "paid_report.md"


def load_paid_report_prompt() -> str:
    return _PROMPT_PATH.read_text(encoding="utf-8")


def build_report_document(
    *,
    natal: dict[str, Any],
    sky_now: dict[str, Any],
    quiz: dict[str, Any] | None = None,
    person: dict[str, Any] | None = None,
) -> dict[str, Any]:
    profile = quiz_profile(quiz)
    natal_rows = natal_table(natal)
    natal_hits = natal_aspects(natal)
    transits = transits_now(natal, sky_now) if natal_rows else []
    sky_iso = str(sky_now.get("datetime_utc") or "")
    accents = select_accents(
        transits=transits,
        natal_aspects=natal_hits,
        quiz=quiz,
        sky_iso=sky_iso,
    )
    method = method_block(natal, sky_now)
    factual = {
        "natal": {
            "points": natal_rows,
            "aspects": natal_hits,
            "houses": houses_table(natal),
            "has_birth_time": bool(natal.get("has_birth_time")),
        },
        "sky": {
            "datetime_utc": sky_iso,
            "collective": collective_sky(sky_now),
        },
        "transits": transits,
        "method": method,
    }
    sections = _section_shells(profile, accents, factual)
    payload = build_generation_payload(
        person=person or {},
        profile=profile,
        accents=accents,
        factual=factual,
        method=method,
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "quiz": profile,
        "factual": factual,
        "accents": {
            "knowledge_depth": accents["knowledge_depth"],
            "primary": accents["primary"],
            "supporting": accents["supporting"],
            "pressure": accents["pressure"],
            "resource": accents["resource"],
            "focus_matches": accents["focus_matches"],
            "through_line": accents["through_line"],
            "rules_applied": accents["rules_applied"],
        },
        "interpretive": {
            "status": "pending_llm",
            "system_prompt_id": SYSTEM_PROMPT_ID,
            "sections": {key: {**row, "body": "", "questions": row.get("questions") or []} for key, row in sections.items()},
        },
        "presentation": {
            "web": {"tabs": WEB_TABS, "default_tab": SECTION_NOW},
            "pdf": {"outline": PDF_OUTLINE, "theme": "cosmirror_navy_gold"},
        },
        "generation": {
            "status": "payload_ready",
            "system_prompt_id": SYSTEM_PROMPT_ID,
            "system_prompt_path": "core/prompts/paid_report.md",
            "payload": payload,
        },
        "sections": sections,
    }


def build_generation_payload(
    *,
    person: dict[str, Any],
    profile: dict[str, Any],
    accents: dict[str, Any],
    factual: dict[str, Any],
    method: dict[str, Any],
) -> dict[str, Any]:
    natal_points = factual["natal"]["points"]
    return {
        "task": "generate_paid_report",
        "voice": "cosmirror_editorial",
        "person": {
            "name": person.get("name") or profile.get("name") or "",
            "birth_date": person.get("birth_date") or "",
            "birth_time": person.get("birth_time") or "",
            "birth_place": person.get("birth_place") or "",
            "has_birth_time": method.get("has_birth_time"),
        },
        "quiz": profile,
        "method": method,
        "natal_points": [
            {
                "key": row["key"],
                "name": row["name"],
                "sign_ru": row["sign_ru"],
                "degree": row["degree"],
                "house": row["house"],
                "theme": row["theme"],
                "fact": row["fact"],
            }
            for row in natal_points
        ],
        "natal_aspects": accents.get("natal_aspects") or [],
        "accents": {
            "through_line": _slim_through_line(accents.get("through_line")),
            "primary": [_slim_hit(row) for row in accents.get("primary") or []],
            "supporting": [_slim_hit(row) for row in accents.get("supporting") or []],
            "pressure": [_slim_hit(row) for row in accents.get("pressure") or []],
            "resource": [_slim_hit(row) for row in accents.get("resource") or []],
            "focus_matches": [_slim_hit(row) for row in accents.get("focus_matches") or []],
        },
        "rules": {
            "layers": "сначала факт (что посчитано), потом гипотеза (что это может значить)",
            "no_predictions": True,
            "no_diagnoses": True,
            "no_inevitable_events": True,
            "user_is_authority": True,
            "personalize_from_quiz": True,
            "through_line_first": True,
            "knowledge_depth": profile.get("knowledge_depth"),
        },
        "output": {
            "sections": {
                SECTION_NOW: ["through_line", "peak", "pressure", "resource", "how_to_work"],
                SECTION_NATAL: ["portrait", "tensions", "resources"],
                SECTION_PERIODS: ["windows", "plus", "minus"],
                SECTION_REQUEST: ["quiz_link", "hypothesis", "what_to_watch"],
                SECTION_PRACTICE: ["questions", "directions"],
                SECTION_METHOD: ["what_calculated", "what_it_means"],
            }
        },
    }


def flatten_document_sections(document: dict[str, Any]) -> list[dict[str, Any]]:
    """Линейные блоки для PDF и старого UI: факты уже есть, интерпретация — позже."""
    sections = document.get("sections") or {}
    order = [tab["id"] for tab in WEB_TABS]
    out: list[dict[str, Any]] = []
    for key in order:
        section = sections.get(key)
        if not isinstance(section, dict):
            continue
        out.append(
            {
                "id": key,
                "title": section.get("title") or key,
                "blocks": section.get("blocks") or [],
            }
        )
    return out


def _slim_hit(hit: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(hit, dict):
        return {}
    return {
        "id": hit.get("id"),
        "label": (
            f"{hit.get('transit_name')} {hit.get('aspect_ru')} "
            f"{hit.get('natal_name')} ({hit.get('orb')}°)"
        ),
        "transit": hit.get("transit"),
        "natal": hit.get("natal"),
        "aspect": hit.get("aspect"),
        "aspect_ru": hit.get("aspect_ru"),
        "polarity": hit.get("polarity"),
        "orb": hit.get("orb"),
        "motion": hit.get("motion"),
        "natal_house": hit.get("natal_house"),
        "focus_match": hit.get("focus_match") or [],
        "fact": hit.get("fact"),
        "work_with": hit.get("work_with"),
        "window": hit.get("window"),
        "score": hit.get("score"),
    }


def _slim_through_line(line: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(line, dict):
        return None
    return {
        "transit": line.get("transit"),
        "transit_name": line.get("transit_name"),
        "natal_points": line.get("natal_points") or [],
        "summary_fact": line.get("summary_fact"),
        "hits": [_slim_hit(row) for row in (line.get("hits") or [])[:6]],
    }


def _hit_block(hit: dict[str, Any]) -> dict[str, str]:
    window = hit.get("window") or {}
    peak = window.get("peak_estimate")
    peak_bit = f" Оценка пика по орбу и скорости: {peak}." if peak else ""
    span = window.get("span_note") or ""
    return {
        "title": (
            f"{hit.get('transit_name')} · {hit.get('aspect_ru')} · "
            f"{hit.get('natal_name')} · {hit.get('orb')}° · {hit.get('polarity_ru')}"
        ),
        "text": f"{hit.get('fact') or ''} {span}.{peak_bit} {hit.get('work_with') or ''}".strip(),
    }


def _section_shells(
    profile: dict[str, Any],
    accents: dict[str, Any],
    factual: dict[str, Any],
) -> dict[str, Any]:
    primary = (accents.get("primary") or [None])[0]
    line = accents.get("through_line")
    now_blocks: list[dict[str, str]] = []
    if line:
        now_blocks.append({"title": "Сквозная линия", "text": str(line.get("summary_fact") or "")})
    if primary:
        now_blocks.append(_hit_block(primary))
        now_blocks.append(
            {
                "title": "Как с этим работать",
                "text": str(primary.get("work_with") or WORK_WITH["mixed"]),
            }
        )
    if not now_blocks:
        now_blocks.append(
            {
                "title": "Текущее небо",
                "text": "Прямых точных персональных попаданий сейчас нет — это тоже информация. Смотри общий фон и свои повторяющиеся реакции.",
            }
        )

    natal_blocks = [
        {"title": f"{row['name']} · {row['sign_ru']}" + (f" · дом {row['house']}" if row.get("house") else ""), "text": row["fact"]}
        for row in factual["natal"]["points"]
    ]
    for house in factual["natal"]["houses"]:
        who = ", ".join(house.get("occupants") or [])
        who_text = f" Здесь в карте: {who}." if who else ""
        natal_blocks.append(
            {
                "title": f"{house['house']}-й дом · {house['sign_ru']}",
                "text": f"{house['theme']}.{who_text}",
            }
        )

    period_blocks = [_hit_block(row) for row in (accents.get("pressure") or [])]
    period_blocks += [_hit_block(row) for row in (accents.get("resource") or [])]
    if not period_blocks:
        period_blocks.append(
            {
                "title": "Окна",
                "text": "Значимых персональных аспектов в текущем орбе нет. Общий фон внешних планет всё равно задаёт климат.",
            }
        )

    focus_labels = ", ".join(profile.get("focus_labels") or []) or "жизнь"
    request_text = (
        f"Сейчас в фокусе: {focus_labels}. "
        f"Период: {profile.get('life_stage_label') or 'не указан'}. "
        f"Запрос к астрологии: {profile.get('intent_label') or profile.get('astrology_trigger_label') or 'понять, что происходит'}."
    )
    if accents.get("focus_matches"):
        request_text += " С картой это пересекается через: " + ", ".join(
            f"{row['transit_name']} → {row['natal_name']}" for row in accents["focus_matches"][:3]
        ) + "."

    questions = _practice_questions(profile)
    method = factual["method"]

    return {
        SECTION_NOW: {
            "id": SECTION_NOW,
            "title": "Что происходит сейчас",
            "layer": "factual",
            "blocks": now_blocks,
        },
        SECTION_NATAL: {
            "id": SECTION_NATAL,
            "title": "Натальная карта",
            "layer": "factual",
            "blocks": natal_blocks,
        },
        SECTION_PERIODS: {
            "id": SECTION_PERIODS,
            "title": "Периоды: напряжение и ресурс",
            "layer": "factual",
            "blocks": period_blocks,
        },
        SECTION_REQUEST: {
            "id": SECTION_REQUEST,
            "title": "Твой запрос",
            "layer": "factual",
            "blocks": [{"title": "Как квиз стыкуется с картой", "text": request_text}],
            "questions": questions[:1],
        },
        SECTION_PRACTICE: {
            "id": SECTION_PRACTICE,
            "title": "Практика",
            "layer": "interpretive_ready",
            "blocks": [
                {"title": "Направления", "text": WORK_WITH["mixed"]},
            ],
            "questions": questions,
        },
        SECTION_METHOD: {
            "id": SECTION_METHOD,
            "title": "Что именно посчитано",
            "layer": "factual",
            "blocks": [
                {
                    "title": method.get("engine_label") or "Расчёт",
                    "text": " ".join(method.get("what_calculated") or []) + " " + str(method.get("what_it_means") or ""),
                }
            ],
        },
    }


def _practice_questions(profile: dict[str, Any]) -> list[str]:
    focus = (profile.get("focus") or ["path"])[0]
    by_focus = {
        "love": "Где близость всё ещё ощущается твоим выбором — а где уже автоматической уступкой?",
        "money": "Что из рабочей нагрузки правда твоё — а что держится чужим ожиданием?",
        "energy": "После каких ситуаций сил становится меньше, даже если «надо было справиться»?",
        "confidence": "Где ты ждешь разрешения быть видимым — и кто, по ощущению, должен его дать?",
        "path": "Что из привычного сейчас даёт опору, а что просто знакомо?",
        "other": "Где реакция уже не помогает, хотя когда-то защищала?",
    }
    stage = {
        "stable": "Если снаружи стабильно — где внутри уже тесно?",
        "one-sphere": "В какой одной сфере ты уже не можешь делать вид, что всё как раньше?",
        "many-spheres": "Что общего у перемен в разных сферах — какой запрос под ними один?",
        "ready-to-change": "Что ты называешь «пора менять» — и чего в этом страхе потерять?",
        "unclear": "Что именно ты не понимаешь: факты, чувства или то, чего от тебя ждут?",
    }
    return [
        by_focus.get(focus, by_focus["other"]),
        stage.get(str(profile.get("life_stage") or ""), "Где ты соглашаешься быстрее, чем успеваешь понять, хочешь ли этого?"),
        "Какой маленький шаг был бы честным, даже если большое решение ещё рано?",
    ]
