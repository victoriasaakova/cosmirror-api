"""
Сборка каркаса отчёта: факты + акценты + интерпретационный слой-заготовка + промпт.

LLM здесь не вызывается. `generation.payload` — то, что позже уйдёт в модель.
"""

from __future__ import annotations

from typing import Any

from core.services.llm_prompts import (
    PROMPT_PAID_REPORT,
    PROMPT_PAID_REPORT_ASPECTS,
    PROMPT_PAID_REPORT_CYCLES,
    PROMPT_PAID_REPORT_NATAL,
    PROMPT_PAID_REPORT_PRACTICE,
    PROMPT_PAID_REPORT_REQUEST,
    load_prompt,
    resolve_model,
)
from core.services.report_accents import quiz_profile, select_accents
from core.services.report_facts import (
    chart_wheel,
    collective_sky,
    houses_table,
    method_block,
    natal_aspects,
    natal_table,
    transits_now,
)
from core.services.report_lexicon import WORK_WITH, natal_aspect_sentence
from core.services.report_aspects import apply_aspects_to_document, fallback_aspects_interpretation
from core.services.report_cycles import apply_cycles_to_document, fallback_cycles_interpretation
from core.services.report_natal import apply_natal_to_document, fallback_natal_interpretation
from core.services.report_practice import apply_practice_to_document, fallback_practice_interpretation
from core.services.report_request import apply_request_to_document, fallback_request_interpretation
from core.services.report_types import (
    PDF_OUTLINE,
    SCHEMA_VERSION,
    SECTION_ASPECTS,
    SECTION_CYCLES,
    SECTION_NATAL,
    SECTION_PRACTICE,
    SECTION_REQUEST,
    SYSTEM_PROMPT_ID,
    WEB_TABS,
)

_CORE = ("sun", "moon", "ascendant")


def load_paid_report_prompt() -> str:
    return load_prompt(PROMPT_PAID_REPORT).body.strip() + "\n"


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
    wheel = chart_wheel(natal, natal_hits)
    factual = {
        "natal": {
            "points": natal_rows,
            "aspects": natal_hits,
            "houses": houses_table(natal),
            "wheel": wheel,
            "has_birth_time": bool(natal.get("has_birth_time")),
            "house_system": natal.get("house_system") or method.get("house_system"),
        },
        "sky": {
            "datetime_utc": sky_iso,
            "collective": collective_sky(sky_now),
        },
        "transits": transits,
        "method": method,
    }
    sections = _section_shells(profile, accents, factual)
    document_shell = {
        "factual": factual,
        "sections": sections,
        "interpretive": {},
        "quiz": profile,
        "accents": accents,
    }
    apply_natal_to_document(
        document_shell,
        fallback_natal_interpretation(document_shell),
        source="fallback",
        model="",
    )
    apply_aspects_to_document(
        document_shell,
        fallback_aspects_interpretation(document_shell),
        source="fallback",
        model="",
    )
    apply_cycles_to_document(
        document_shell,
        fallback_cycles_interpretation(document_shell),
        source="fallback",
        model="",
    )
    apply_request_to_document(
        document_shell,
        fallback_request_interpretation(document_shell),
        source="fallback",
        model="",
    )
    apply_practice_to_document(
        document_shell,
        fallback_practice_interpretation(document_shell),
        source="fallback",
        model="",
    )
    sections = document_shell["sections"]
    interpretive_layer = document_shell["interpretive"]
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
            "upcoming": accents.get("upcoming") or [],
            "through_line": accents["through_line"],
            "rules_applied": accents["rules_applied"],
        },
        "interpretive": {
            "status": interpretive_layer.get("status") or "fallback",
            "system_prompt_id": SYSTEM_PROMPT_ID,
            "natal": interpretive_layer.get("natal"),
            "aspects": interpretive_layer.get("aspects"),
            "cycles": interpretive_layer.get("cycles"),
            "request": interpretive_layer.get("request"),
            "practice": interpretive_layer.get("practice"),
            "sections": {
                key: {**row, "body": "", "questions": row.get("questions") or []}
                for key, row in sections.items()
            },
        },
        "presentation": {
            "web": {"tabs": WEB_TABS, "default_tab": SECTION_NATAL},
            "pdf": {"outline": PDF_OUTLINE, "theme": "cosmirror_navy_gold"},
        },
        "generation": {
            "status": "payload_ready",
            "system_prompt_id": SYSTEM_PROMPT_ID,
            "system_prompt_path": "core/prompts/paid_report.md",
            "model": resolve_model(SYSTEM_PROMPT_ID),
            "section_prompts": {
                SECTION_NATAL: _section_prompt(
                    PROMPT_PAID_REPORT_NATAL,
                    "core/prompts/paid_report_natal.md",
                ),
                SECTION_ASPECTS: _section_prompt(
                    PROMPT_PAID_REPORT_ASPECTS,
                    "core/prompts/paid_report_aspects.md",
                ),
                SECTION_CYCLES: _section_prompt(
                    PROMPT_PAID_REPORT_CYCLES,
                    "core/prompts/paid_report_cycles.md",
                ),
                SECTION_REQUEST: _section_prompt(
                    PROMPT_PAID_REPORT_REQUEST,
                    "core/prompts/paid_report_request.md",
                ),
                SECTION_PRACTICE: _section_prompt(
                    PROMPT_PAID_REPORT_PRACTICE,
                    "core/prompts/paid_report_practice.md",
                ),
            },
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
            "upcoming": [_slim_hit(row) for row in accents.get("upcoming") or []],
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
                SECTION_NATAL: ["portrait", "sun_moon_asc", "houses", "placements"],
                SECTION_ASPECTS: ["tension", "support", "how_they_work"],
                SECTION_CYCLES: ["pressure", "resource", "how_to_work"],
                SECTION_REQUEST: [
                    "request",
                    "connections",
                    "core_distinction",
                    "resource",
                    "takeaway",
                ],
                SECTION_PRACTICE: [
                    "start_here",
                    "pattern",
                    "protective_function",
                    "cost",
                    "key_distinctions",
                    "values",
                    "reflection_questions",
                    "experiment",
                    "observe_over_time",
                    "user_takeaway",
                ],
            }
        },
    }


def _section_prompt(prompt_id: str, path: str) -> dict[str, str]:
    return {
        "system_prompt_id": prompt_id,
        "system_prompt_path": path,
        "model": resolve_model(prompt_id),
    }


def flatten_document_sections(document: dict[str, Any]) -> list[dict[str, Any]]:
    """Линейные блоки для PDF: факты уже есть, интерпретация дописывается в сами блоки."""
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
        "meaning": hit.get("meaning"),
        "duration": hit.get("duration"),
        "practice": hit.get("practice"),
        "use_for": hit.get("use_for"),
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


def _cycle_block(hit: dict[str, Any]) -> dict[str, str]:
    window = hit.get("window") or {}
    peak = window.get("peak_estimate")
    peak_bit = f" По текущему орбу пик может быть ближе к {peak}." if peak else ""
    duration = str(hit.get("duration") or window.get("span_note") or "")
    meaning = str(hit.get("meaning") or "")
    practice = str(hit.get("practice") or hit.get("work_with") or "")
    use_for = str(hit.get("use_for") or "")
    parts = [
        str(hit.get("fact") or "").strip(),
        f"Длительность: {duration}" if duration else "",
        meaning,
        f"Как работать: {practice}" if practice else "",
        f"Для чего это использовать: {use_for}" if use_for else "",
        peak_bit.strip(),
    ]
    return {
        "title": (
            f"{hit.get('transit_name')} · {hit.get('aspect_ru')} · "
            f"{hit.get('natal_name')} · {hit.get('orb')}° · {hit.get('polarity_ru')}"
        ),
        "text": " ".join(part for part in parts if part).strip(),
        "polarity": str(hit.get("polarity") or ""),
        "duration": duration,
        "meaning": meaning,
        "practice": practice,
        "use_for": use_for,
    }


def _section_shells(
    profile: dict[str, Any],
    accents: dict[str, Any],
    factual: dict[str, Any],
) -> dict[str, Any]:
    points = factual["natal"]["points"]
    by_key = {row["key"]: row for row in points}
    natal_blocks: list[dict[str, str]] = []
    for key in _CORE:
        row = by_key.get(key)
        if not row:
            continue
        house = f" · дом {row['house']}" if row.get("house") else ""
        natal_blocks.append(
            {
                "title": f"{row['name']} · {row['sign_ru']}{house}",
                "text": row["fact"],
            }
        )
    for row in points:
        if row["key"] in _CORE:
            continue
        house = f" · дом {row['house']}" if row.get("house") else ""
        natal_blocks.append(
            {
                "title": f"{row['name']} · {row['sign_ru']}{house}",
                "text": row["fact"],
            }
        )
    for house in factual["natal"]["houses"]:
        who = ", ".join(house.get("occupants") or [])
        who_text = f" Здесь в карте: {who}." if who else ""
        natal_blocks.append(
            {
                "title": f"{house['house']}-й дом · {house['sign_ru']}",
                "text": f"{house['theme']}{who_text}",
            }
        )

    aspect_blocks = _aspect_blocks(factual["natal"].get("aspects") or [])
    pressure_blocks = [_cycle_block(row) for row in (accents.get("pressure") or [])]
    resource_blocks = [_cycle_block(row) for row in (accents.get("resource") or [])]
    cycle_blocks: list[dict[str, str]] = [
        {
            "title": "Что звучит сейчас",
            "text": (
                "Это внешнее небо к уже посчитанной карте: транзиты, окна, трение и канал. "
                "Не путать с натальными аспектами — те живут во вкладке «Аспекты»."
            ),
        }
    ]
    if pressure_blocks:
        cycle_blocks.append(
            {
                "title": "Напряжённые периоды",
                "text": "Это зоны трения: что стало тесным и просит честности. Не катастрофа и не приговор.",
            }
        )
        cycle_blocks.extend(pressure_blocks)
    if resource_blocks:
        cycle_blocks.append(
            {
                "title": "Ресурсные периоды",
                "text": "Это каналы, которыми можно пользоваться специально — пока окно открыто.",
            }
        )
        cycle_blocks.extend(resource_blocks)
    if not pressure_blocks and not resource_blocks:
        cycle_blocks.append(
            {
                "title": "Текущие циклы",
                "text": "Значимых персональных транзитов в текущем орбе нет. Общий фон внешних планет всё равно задаёт климат — смотри, где ты уже реагируешь сильнее обычного.",
            }
        )

    request_blocks = _request_blocks(profile, accents)
    practice_blocks = _practice_shell_blocks(profile)

    return {
        SECTION_NATAL: {
            "id": SECTION_NATAL,
            "title": "Твоя карта",
            "layer": "factual",
            "blocks": natal_blocks,
        },
        SECTION_ASPECTS: {
            "id": SECTION_ASPECTS,
            "title": "Аспекты",
            "layer": "factual",
            "blocks": aspect_blocks,
        },
        SECTION_CYCLES: {
            "id": SECTION_CYCLES,
            "title": "Циклы",
            "layer": "factual",
            "blocks": cycle_blocks,
        },
        SECTION_REQUEST: {
            "id": SECTION_REQUEST,
            "title": "Запрос",
            "layer": "factual",
            "blocks": request_blocks,
        },
        SECTION_PRACTICE: {
            "id": SECTION_PRACTICE,
            "title": "Практика",
            "layer": "factual",
            "blocks": practice_blocks,
            "questions": _practice_questions(profile),
        },
    }


def _aspect_card(row: dict[str, Any]) -> dict[str, str]:
    return {
        "title": (
            f"{row.get('a_name')} · {row.get('aspect_ru')} · "
            f"{row.get('b_name')} · {row.get('orb')}°"
        ),
        "text": natal_aspect_sentence(
            str(row.get("a") or ""),
            str(row.get("aspect") or ""),
            str(row.get("aspect_ru") or ""),
            str(row.get("b") or ""),
        ),
        "kind": str(row.get("kind") or ""),
        "aspect": str(row.get("aspect") or ""),
    }


def _aspect_blocks(hits: list[dict[str, Any]]) -> list[dict[str, str]]:
    blocks: list[dict[str, str]] = [
        {
            "title": "Как темы связаны внутри",
            "text": (
                "Это не текущее небо и не прогноз. "
                "Аспект — как две темы в тебе уже связаны: трение, поддержка, растяжка или слияние."
            ),
        }
    ]
    if not hits:
        blocks.append(
            {
                "title": "Натальные аспекты",
                "text": "В текущем расчёте тесных натальных аспектов нет — смотри положения и дома.",
            }
        )
        return blocks

    hard = [row for row in hits if row.get("kind") == "hard"]
    soft = [row for row in hits if row.get("kind") != "hard"]
    if hard:
        blocks.append(
            {
                "title": "Трение",
                "text": "Жёсткие аспекты: темы сталкиваются и просят честного выбора. Не «плохо» — громче.",
            }
        )
        blocks.extend(_aspect_card(row) for row in hard)
    if soft:
        blocks.append(
            {
                "title": "Поддержка",
                "text": (
                    "Мягкие аспекты: есть рабочий канал. Не «удача» — привычное русло, "
                    "которым можно пользоваться."
                ),
            }
        )
        blocks.extend(_aspect_card(row) for row in soft)
    return blocks


def _request_blocks(profile: dict[str, Any], accents: dict[str, Any]) -> list[dict[str, str]]:
    focus_labels = ", ".join(profile.get("focus_labels") or []) or "жизнь"
    intent = profile.get("intent_label") or profile.get("astrology_trigger_label") or "понять, что происходит"
    line = accents.get("through_line")
    primary = (accents.get("primary") or [None])[0]
    matches = accents.get("focus_matches") or []
    pressure = accents.get("pressure") or []
    resource = accents.get("resource") or []

    intro = (
        f"В онбординге ты отметила фокус: {focus_labels}. "
        f"Запрос к астрологии: {intent}. "
        "Карта не отвечает на вопрос «что случится». Она показывает, какие темы сейчас громче — "
        "и почему именно этот запрос мог выйти на поверхность."
    )
    if line:
        intro += (
            f" Сквозная линия сейчас — транзитный {line.get('transit_name')}: "
            f"{line.get('summary_fact')}"
        )

    link_bits: list[str] = []
    if primary:
        house = f", дом {primary['natal_house']}" if primary.get("natal_house") else ""
        link_bits.append(
            f"Самый тесный контакт: {primary.get('transit_name')} {primary.get('aspect_ru')} "
            f"{primary.get('natal_name')}{house}. {primary.get('fact') or ''} "
            f"В запросе про «{focus_labels}» это может звучать как давление или сдвиг именно в этой теме — "
            "не как событие, а как ощущение, что старый способ больше не держит."
        )
    for row in matches[:3]:
        if primary and row.get("id") == primary.get("id"):
            continue
        link_bits.append(
            f"{row.get('transit_name')} к {row.get('natal_name')}: {row.get('fact') or ''} "
            f"{row.get('meaning') or ''}"
        )
    if not link_bits:
        link_bits.append(
            "Прямого точного попадания в выбранный фокус сейчас нет. "
            "Имеет смысл смотреть общий фон и свои повторяющиеся реакции — запрос всё равно важен сам по себе."
        )

    work_parts = []
    if pressure:
        work_parts.append(
            "В напряжённых циклах: не ускоряться из стыда и не замирать. "
            + str(pressure[0].get("practice") or WORK_WITH["pressure"])
        )
    if resource:
        work_parts.append(
            "В ресурсных: пользоваться каналом специально. "
            + str(resource[0].get("practice") or WORK_WITH["resource"])
        )
    if not work_parts:
        work_parts.append(WORK_WITH["mixed"])
    work_parts.append(_practice_questions(profile)[0])

    why = (
        f"Такой запрос часто появляется, когда внешний цикл задевает ту же тему, что уже зрела внутри. "
        f"Сейчас в фокусе {focus_labels}, запрос — {intent}. "
        "Цикл не «создаёт» вопрос из воздуха: он делает его слышнее. "
        "Имеет смысл использовать этот момент, чтобы отличить своё желание от привычки держаться за знакомое — "
        "и сделать один маленький честный шаг, а не большое судьбоносное решение."
    )
    if primary and primary.get("use_for"):
        why += " " + str(primary["use_for"])

    return [
        {"title": "Как запрос связан с циклами", "text": intro},
        {"title": "Где карта пересекается с вопросом", "text": " ".join(link_bits)},
        {"title": "Как с этим работать", "text": " ".join(work_parts)},
        {"title": "Для чего это может происходить сейчас", "text": why},
    ]


def _summary_blocks(accents: dict[str, Any], factual: dict[str, Any]) -> list[dict[str, str]]:
    line = accents.get("through_line")
    pressure = accents.get("pressure") or []
    resource = accents.get("resource") or []
    upcoming = accents.get("upcoming") or []
    now_parts: list[str] = []
    if line:
        now_parts.append(str(line.get("summary_fact") or ""))
    if pressure:
        names = ", ".join(
            f"{row.get('transit_name')} к {row.get('natal_name')}" for row in pressure[:4]
        )
        now_parts.append(f"Напряжённые контакты сейчас: {names}.")
    if resource:
        names = ", ".join(
            f"{row.get('transit_name')} к {row.get('natal_name')}" for row in resource[:4]
        )
        now_parts.append(f"Ресурсные контакты: {names}.")
    if not now_parts:
        now_parts.append("Персональных точных попаданий в текущем орбе почти нет — фон спокойнее точечных ударов.")

    next_parts: list[str] = []
    for row in upcoming[:5]:
        days = row.get("days_to_exact")
        peak = (row.get("window") or {}).get("peak_estimate")
        when = f"оценка пика {peak}" if peak else (f"ещё около {days} дн. до точного" if days is not None else "идёт к точности")
        next_parts.append(
            f"{row.get('transit_name')} {row.get('aspect_ru')} {row.get('natal_name')} — {when}. "
            f"{row.get('duration') or ''}"
        )
    if not next_parts:
        next_parts.append(
            "Точных applying-контактов в расчёте сейчас нет. "
            "Имеет смысл вернуться к карте, когда внешние планеты снова сузят орб."
        )

    collective = factual.get("sky", {}).get("collective") or []
    climate = ""
    if collective:
        climate = " Общий фон неба: " + "; ".join(
            f"{row.get('name')} в {row.get('sign_ru')}" for row in collective
        ) + "."

    return [
        {
            "title": "Что идёт сейчас",
            "text": " ".join(now_parts) + climate,
        },
        {
            "title": "Что будет дальше",
            "text": " ".join(next_parts)
            + " Это ориентиры по орбу и скорости, не даты событий.",
        },
    ]


def _practice_shell_blocks(profile: dict[str, Any]) -> list[dict[str, str]]:
    questions = _practice_questions(profile)
    return [
        {
            "title": "С чего начать",
            "text": (
                "После вкладок карты, аспектов, циклов и запроса здесь — "
                "практическая самостоятельная работа с найденной темой."
            ),
        },
        {
            "title": "Вопросы для наблюдения",
            "text": "\n".join(f"• {q}" for q in questions),
        },
    ]


def _practice_questions(profile: dict[str, Any]) -> list[str]:
    focus = (profile.get("focus") or ["path"])[0]
    by_focus = {
        "love": "Где близость всё ещё ощущается твоим выбором — а где уже автоматической уступкой?",
        "money": "Что из рабочей нагрузки правда твоё — а что держится чужим ожиданием?",
        "energy": "После каких ситуаций сил становится меньше, даже если «надо было справиться»?",
        "confidence": "Где ты ждёшь разрешения быть видимой — и кто, по ощущению, должен его дать?",
        "path": "Что из привычного сейчас даёт опору, а что просто знакомо?",
        "future": "Что из привычного сейчас даёт опору, а что просто знакомо?",
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
