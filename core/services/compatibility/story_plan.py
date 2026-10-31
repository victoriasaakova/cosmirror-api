"""Внутренний план сюжета глубокого разбора.

Поля плана не показываются пользователю. Пустое поле значит, что факта нет:
его не заполняют правдоподобной догадкой.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from .insight import basis_line, decline_name
from .policy import PERSONAL

SECTION_IDS = ("common_ground", "differences", "values_needs", "mutual_expression")

_SOFT = frozenset({"trine", "sextile"})
_HARD = frozenset({"square", "opposition"})
_STOP = frozenset(
    {
        "или",
        "как",
        "где",
        "что",
        "это",
        "здесь",
        "может",
        "могут",
        "быть",
        "для",
        "при",
        "уже",
        "ещё",
        "еще",
        "только",
        "тебя",
        "тебе",
        "твой",
        "твоя",
        "твоё",
        "твое",
        "этот",
        "эта",
        "этого",
        "этой",
        "один",
        "одна",
        "одно",
        "когда",
        "если",
        "него",
        "нее",
        "них",
        "вас",
        "вам",
        "ваш",
        "ваша",
        "между",
        "рядом",
        "через",
        "после",
        "перед",
        "чтобы",
        "который",
        "которая",
        "которое",
        "которые",
    }
)


def plan_sections(
    rows: list[dict[str, Any]],
    *,
    relationship_type: str,
    relationship_status: Optional[str],
    names: tuple[str, str],
    anchors: dict[str, list[dict[str, Any]]],
    insight_ids: set[str],
    titles: dict[str, str],
) -> list[dict[str, Any]]:
    forms = decline_name(names[1])
    used_ids: set[str] = set()
    used_families: set[str] = set()
    used_mechanisms: set[str] = set()
    used_natal: set[str] = set()
    taken_text: list[str] = []
    sections: list[dict[str, Any]] = []
    for section_id in SECTION_IDS:
        picked = _pick(
            section_id,
            rows,
            relationship_type=relationship_type,
            forms=forms,
            used_ids=used_ids,
            used_families=used_families,
            used_mechanisms=used_mechanisms,
            taken_text=taken_text,
        )
        opened = False
        if picked is None:
            row = _open_row(section_id, rows, used_ids)
            if row is None:
                sections.append(_limited(section_id, titles))
                continue
            spec = _open_spec(section_id, row, names)
            claim = spec["claim"]
            mechanism = spec["mechanism"]
            opened = True
        else:
            row, spec, claim, mechanism = picked
        used_ids.add(row["evidence_id"])
        used_families.add(spec["family"])
        used_mechanisms.add(spec["mechanism_id"])
        taken_text.append(f"{claim} {mechanism}")
        sections.append(
            _ready(
                section_id,
                row,
                spec,
                claim=claim,
                mechanism=mechanism,
                relationship_status=relationship_status,
                names=names,
                forms=forms,
                anchors=anchors,
                insight_ids=insight_ids,
                titles=titles,
                used_natal=used_natal,
            )
        )
        if opened:
            basis = (sections[-1]["analysis"].get("cross_evidence_ru") or [""])[0]
            sections[-1]["headline"] = "Персональная история этой темы пока ограничена по глубине."
            sections[-1]["preview"] = "Персональное объяснение этой темы пока ограничено по глубине."
            sections[-1]["body"] = (
                f"{basis}. Этот контакт выбран для темы, потому что он есть в рассчитанной синастрии. "
                "Отдельные натальные опоры, если они переданы, уточняют только склонность каждого к своей стороне контакта.\n\n"
                "Персональное объяснение пока ограничено по глубине. "
                "Это не вывод о чувствах, мотивах или решениях и не готовая история для любой пары. "
                "Авторский текст заменяет эту пометку, когда проходит проверку."
            )
            sections[-1]["interpretation_depth"] = "limited"
            sections[-1]["confidence"] = "limited"
    _fill_forbidden(sections)
    return sections


def writer_facts(section: dict[str, Any]) -> dict[str, Any]:
    analysis = section.get("analysis") if isinstance(section.get("analysis"), dict) else {}
    plan = analysis.get("story_plan") if isinstance(analysis.get("story_plan"), dict) else {}
    return {
        "id": section.get("id"),
        "section_title": section.get("section_title"),
        "story_plan": plan,
        "cross_evidence_ru": analysis.get("cross_evidence_ru") or [],
        "reader_trait_allowed": bool(plan.get("person_a_quality")),
        "other_trait_allowed": bool(plan.get("person_b_quality")),
        "required_words": list(analysis.get("markers") or []),
    }


def section_collides(body: str, section: dict[str, Any], others: list[dict[str, Any]]) -> bool:
    """True, если текст ушёл из своего механизма или повторил чужой."""
    analysis = section.get("analysis") if isinstance(section.get("analysis"), dict) else {}
    own = {str(item).casefold() for item in analysis.get("markers") or []}
    lowered = body.casefold()
    if own and not any(marker in lowered for marker in own):
        return True
    for other in others:
        if other.get("id") == section.get("id"):
            continue
        other_analysis = other.get("analysis") if isinstance(other.get("analysis"), dict) else {}
        foreign = [
            str(item).casefold()
            for item in other_analysis.get("markers") or []
            if str(item).casefold() not in own
        ]
        if sum(1 for marker in foreign if marker in lowered) >= 2:
            return True
        other_body = str(other.get("body") or "")
        if other_body and _similar(body, other_body):
            return True
    return False


def audit_stories(sections: list[dict[str, Any]]) -> dict[str, Any]:
    ready = [section for section in sections if section.get("status") == "ready"]
    mechanisms = [_analysis(section).get("mechanism_id") for section in ready]
    families = [_analysis(section).get("theme_family") for section in ready]
    claims = [
        str((_analysis(section).get("story_plan") or {}).get("central_claim") or "")
        for section in ready
    ]
    overlaps = []
    for index, left in enumerate(ready):
        for right in ready[index + 1 :]:
            if section_collides(str(left.get("body") or ""), left, [right]) or section_collides(
                str(right.get("body") or ""), right, [left]
            ):
                overlaps.append([left.get("id"), right.get("id")])
    distinct_mechanisms = len(mechanisms) == len(set(mechanisms)) and all(mechanisms)
    distinct_families = len(families) == len(set(families)) and all(families)
    distinct_claims = len(claims) == len(set(claims)) and all(claims)
    return {
        "ready_ids": [section.get("id") for section in ready],
        "mechanism_ids": mechanisms,
        "theme_families": families,
        "central_claims": claims,
        "distinct_mechanisms": distinct_mechanisms,
        "distinct_families": distinct_families,
        "distinct_claims": distinct_claims,
        "overlaps": overlaps,
        "passed": distinct_mechanisms and distinct_families and distinct_claims and not overlaps,
    }


def _open_row(
    section_id: str,
    rows: list[dict[str, Any]],
    used_ids: set[str],
) -> Optional[dict[str, Any]]:
    """Аспект вне каталога всё равно попадает к writer, если он относится к теме."""
    wanted = {
        "common_ground": _SOFT,
        "differences": _HARD,
        "values_needs": _SOFT | _HARD | {"conjunction"},
        "mutual_expression": _SOFT | _HARD | {"conjunction"},
    }[section_id]
    focus = {
        "common_ground": frozenset({"moon", "venus", "sun", "mercury"}),
        "differences": frozenset({"moon", "mars", "mercury", "saturn", "venus"}),
        "values_needs": frozenset({"moon", "venus", "saturn", "jupiter", "sun"}),
        "mutual_expression": frozenset({"sun", "mars", "mercury", "asc", "mc"}),
    }[section_id]
    ranked = []
    for row in rows:
        if row["evidence_id"] in used_ids or row["aspect"] not in wanted:
            continue
        points = {row["point_a"], row["point_b"]}
        if not points & PERSONAL:
            continue
        if points & {"chiron"}:
            continue
        focus_hit = 0 if points & focus else 1
        ranked.append((focus_hit, -row["signal"], row["evidence_id"], row))
    if not ranked:
        return None
    ranked.sort(key=lambda item: (item[0], item[1], item[2]))
    return ranked[0][3]


def _open_spec(section_id: str, row: dict[str, Any], names: tuple[str, str]) -> dict[str, Any]:
    basis = basis_line(row["point_a"], names[0], row["aspect"], row["point_b"], names[1])
    polarity = "soft" if row["aspect"] in _SOFT else "hard" if row["aspect"] in _HARD else "conjunction"
    claim, mechanism, scene, insight = _plain_contact(section_id, row, names, basis, polarity)
    return _spec(
        section_id,
        row["point_a"],
        row["point_b"],
        polarity,
        f"open-{section_id}-{row['point_a']}-{row['point_b']}-{row['aspect']}",
        f"open-{section_id}",
        (),
        claim,
        mechanism,
        scene,
        insight,
        "Персональное объяснение этой темы пока ограничено по глубине.",
    )


_NEED = {
    "moon": "получить отклик на настроение, а не сразу его разбор",
    "venus": "проявить симпатию и получить тёплый, не резкий ответ",
    "mars": "быстрее перейти от разговора к действию",
    "mercury": "сначала ясно сформулировать, что происходит",
    "sun": "чтобы собственный выбор и присутствие заметили",
    "jupiter": "увидеть в ситуации больше возможностей, чем в ней прямо просили",
    "saturn": "сначала увидеть, что правила понятны и обещание выполняется",
    "uranus": "сохранить дистанцию и собственный темп",
    "neptune": "представлять близость мягче, чем она складывается на деле",
    "pluto": "не бросать тему, пока она не доведена до конца",
    "asc": "чтобы первое впечатление не расходилось с самоощущением",
    "mc": "чтобы видимая роль совпадала с тем, чего хочется",
}


def _plain_contact(
    section_id: str,
    row: dict[str, Any],
    names: tuple[str, str],
    basis: str,
    polarity: str,
) -> tuple[str, str, str, str]:
    """Человеческая ситуация аспекта. Это задание writer, не готовый текст карточки."""
    other = decline_name(names[1])
    dative = other.get("dative") or names[1]
    reader_need = _NEED.get(row["point_a"], "отреагировать из своей привычной потребности")
    other_need = _NEED.get(row["point_b"], "отреагировать из своей привычной потребности")
    pair = f"{_matters('Тебе', reader_need)}. {_matters(dative, other_need)}."
    if section_id == "common_ground":
        claim = "Эти реакции могут совпасть и сделать контакт проще."
        closing = "В обычном контакте это может совпасть: одна потребность встречает другую, и сближение становится проще без обязательного спора."
        scene = "Так может выглядеть обычный разговор или пауза рядом, где каждый отвечает своей потребностью и это не нужно долго согласовывать."
    elif section_id == "differences":
        claim = "В одной ситуации эти реакции могут не совпасть."
        closing = "Трение возникает из этих двух реакций в одном моменте, а не из оценки, кто прав."
        scene = "Так может выглядеть трудный момент, где один уже отвечает своей потребностью, а другой ждёт другого ответа."
    elif section_id == "values_needs":
        claim = "Две потребности могут стоять рядом и не стать одним требованием."
        closing = "Их можно не путать: каждая подтверждает связь по-своему, и они не обязаны совпасть."
        scene = "Так может выглядеть разговор о том, как будет дальше, где каждый узнаёт заботу своим способом."
    else:
        claim = "Рядом эти реакции могут становиться заметнее."
        closing = "Присутствие одного делает реакцию другого заметнее. Это не повтор темы сближения и не доказательство чувств."
        scene = "Так может выглядеть момент, где рядом с другим человеком собственная реакция проявляется явнее, чем в одиночку."
    if polarity == "hard" and section_id == "common_ground":
        closing = "Даже в сближении эти реакции остаются разными и не обязаны превратиться в спор."
    mechanism = f"{basis}. {pair} {closing}"
    insight = closing
    return claim, mechanism, scene, insight


def _matters(who: str, need: str) -> str:
    if need.startswith("чтобы"):
        return f"{who} важно, {need}"
    return f"{who} важно {need}"


def _pick(
    section_id: str,
    rows: list[dict[str, Any]],
    *,
    relationship_type: str,
    forms: dict[str, Optional[str]],
    used_ids: set[str],
    used_families: set[str],
    used_mechanisms: set[str],
    taken_text: list[str],
) -> Optional[tuple[dict[str, Any], dict[str, Any], str, str]]:
    candidates = []
    for row in rows:
        if row["evidence_id"] in used_ids:
            continue
        for spec in _SPECS:
            if spec["section_id"] != section_id or not _matches(spec, row, relationship_type):
                continue
            if spec["family"] in used_families or spec["mechanism_id"] in used_mechanisms:
                continue
            claim = _fill(spec["claim"], forms)
            mechanism = _fill(spec["mechanism"], forms)
            blob = f"{claim} {mechanism}"
            if any(_similar(blob, previous) for previous in taken_text):
                continue
            candidates.append((-row["signal"], row["evidence_id"], row, spec, claim, mechanism))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]))
    _, _, row, spec, claim, mechanism = candidates[0]
    return row, spec, claim, mechanism


def _matches(spec: dict[str, Any], row: dict[str, Any], relationship_type: str) -> bool:
    allowed = spec.get("relationships")
    if allowed is not None and relationship_type not in allowed:
        return False
    if (row["point_a"], row["point_b"]) != (spec["point_a"], spec["point_b"]):
        return False
    kind = row["aspect"]
    polarity = spec["polarity"]
    if polarity == "soft":
        return kind in _SOFT
    if polarity == "hard":
        return kind in _HARD
    if polarity == "conjunction":
        return kind == "conjunction"
    if polarity == "soft_or_conj":
        return kind in _SOFT or kind == "conjunction"
    return False


def _ready(
    section_id: str,
    row: dict[str, Any],
    spec: dict[str, Any],
    *,
    claim: str,
    mechanism: str,
    relationship_status: Optional[str],
    names: tuple[str, str],
    forms: dict[str, Optional[str]],
    anchors: dict[str, list[dict[str, Any]]],
    insight_ids: set[str],
    titles: dict[str, str],
    used_natal: set[str],
) -> dict[str, Any]:
    quality_a, natal_a = _quality(
        anchors.get("A") or [],
        row["point_a"],
        person="A",
        prefer=spec.get("prefer_a"),
        used=used_natal,
        forms=forms,
    )
    quality_b, natal_b = _quality(
        anchors.get("B") or [],
        row["point_b"],
        person="B",
        prefer=spec.get("prefer_b"),
        used=used_natal,
        forms=forms,
    )
    scene = _fill(spec["scene"], forms)
    insight = _fill(spec["insight"], forms)
    preview = _fill(spec["preview"], forms)
    first = " ".join(part for part in (quality_a, quality_b, mechanism) if part)
    second = f"{scene} {insight}"
    if relationship_status in {"ended", "no_contact"}:
        second += " Это возможный узор того, как контакт мог складываться, не причина завершения и не прогноз возвращения."
    evidence_id = row["evidence_id"]
    natal_a_ids = [natal_a] if natal_a else []
    natal_b_ids = [natal_b] if natal_b else []
    return {
        "id": section_id,
        "status": "ready",
        "access": "full",
        "confidence": "full" if quality_a and quality_b else "limited",
        "section_title": titles[section_id],
        "headline": claim,
        "body": f"{first}\n\n{second}",
        "preview": preview,
        "evidence_ids": [evidence_id],
        "astro_basis": {
            "cross_evidence_ids": [evidence_id],
            "natal_a_evidence_ids": natal_a_ids,
            "natal_b_evidence_ids": natal_b_ids,
        },
        "primary_evidence_id": evidence_id,
        "reused_evidence_reason": "insight_reference" if evidence_id in insight_ids else None,
        "source": "fallback",
        "writer": "fallback",
        "analysis": {
            "mechanism_id": spec["mechanism_id"],
            "theme_family": spec["family"],
            "markers": list(spec["markers"]),
            "cross_evidence_ru": [
                basis_line(row["point_a"], names[0], row["aspect"], row["point_b"], names[1])
            ],
            "evidence": {
                "id": evidence_id,
                "owner_a": names[0],
                "owner_b": names[1],
                "point_a": row["point_a"],
                "point_b": row["point_b"],
                "aspect": row["aspect"],
                "orb_deg": row.get("orb_deg"),
            },
            "story_plan": {
                "section_id": section_id,
                "central_claim": claim,
                "unique_mechanism": mechanism,
                "person_a_quality": quality_a,
                "person_b_quality": quality_b,
                "concrete_scene": scene,
                "distinctive_insight": insight,
                "primary_evidence_ids": [evidence_id],
                "natal_a_evidence_ids": natal_a_ids,
                "natal_b_evidence_ids": natal_b_ids,
                "must_not_repeat": [],
            },
        },
    }


def _limited(section_id: str, titles: dict[str, str]) -> dict[str, Any]:
    return {
        "id": section_id,
        "status": "limited",
        "access": "full",
        "confidence": "limited",
        "section_title": titles[section_id],
        "headline": None,
        "body": None,
        "preview": "Для этой темы отдельный механизм в выбранных критериях не нашёлся.",
        "evidence_ids": [],
        "astro_basis": {"cross_evidence_ids": [], "natal_a_evidence_ids": [], "natal_b_evidence_ids": []},
        "primary_evidence_id": None,
        "reused_evidence_reason": None,
        "source": "fallback",
        "writer": "fallback",
    }


def _fill_forbidden(sections: list[dict[str, Any]]) -> None:
    owned = []
    for section in sections:
        plan = (_analysis(section).get("story_plan") or {}) if section.get("status") == "ready" else {}
        if plan:
            owned.append((section["id"], str(plan.get("unique_mechanism") or ""), str(plan.get("central_claim") or "")))
    for section in sections:
        plan = _analysis(section).get("story_plan")
        if not isinstance(plan, dict):
            continue
        plan["must_not_repeat"] = [
            text
            for section_id, mechanism, claim in owned
            if section_id != section["id"]
            for text in (mechanism, claim)
            if text
        ]


def _quality(
    anchors: list[dict[str, Any]],
    point: str,
    *,
    person: str,
    prefer: Optional[str],
    used: set[str],
    forms: dict[str, Optional[str]],
) -> tuple[Optional[str], Optional[str]]:
    ranked = []
    for anchor in anchors:
        if not isinstance(anchor, dict):
            continue
        left = str(anchor.get("a") or "")
        right = str(anchor.get("b") or "")
        aspect = str(anchor.get("aspect") or "")
        evidence_id = str(anchor.get("id") or "")
        if point not in {left, right} or not evidence_id or evidence_id in used:
            continue
        entry = _NATAL.get((frozenset({left, right}), aspect))
        if not entry or point not in entry["points"]:
            continue
        other = left if right == point else right
        template = entry["reader"] if person == "A" else entry["other"]
        text = template if person == "A" else _fill(template, forms)
        rank = (0 if prefer and other == prefer else 1, 0 if other in PERSONAL else 1, evidence_id)
        ranked.append((rank, evidence_id, text))
    if not ranked:
        return None, None
    ranked.sort(key=lambda item: item[0])
    _, evidence_id, text = ranked[0]
    used.add(evidence_id)
    return text, evidence_id


def _fill(template: str, forms: dict[str, Optional[str]]) -> str:
    nominative = forms.get("nominative") or "партнёр"
    return template.format(
        nom=nominative,
        gen=forms.get("genitive") or nominative,
        dat=forms.get("dative") or nominative,
        acc=forms.get("accusative") or nominative,
        ins=forms.get("instrumental") or nominative,
    )


def _analysis(section: dict[str, Any]) -> dict[str, Any]:
    analysis = section.get("analysis")
    return analysis if isinstance(analysis, dict) else {}


def _similar(left: str, right: str) -> bool:
    words_left = _words(left)
    words_right = _words(right)
    if not words_left or not words_right:
        return False
    overlap = len(words_left & words_right) / len(words_left | words_right)
    return overlap >= 0.5


def _words(text: str) -> set[str]:
    return {
        word
        for word in re.findall(r"[а-яёa-z]+", text.casefold())
        if len(word) > 3 and word not in _STOP
    }


def _spec(
    section_id: str,
    point_a: str,
    point_b: str,
    polarity: str,
    mechanism_id: str,
    family: str,
    markers: tuple[str, ...],
    claim: str,
    mechanism: str,
    scene: str,
    insight: str,
    preview: str,
    *,
    relationships: Optional[frozenset[str]] = None,
    prefer_a: Optional[str] = None,
    prefer_b: Optional[str] = None,
) -> dict[str, Any]:
    return {
        "section_id": section_id,
        "point_a": point_a,
        "point_b": point_b,
        "polarity": polarity,
        "mechanism_id": mechanism_id,
        "family": family,
        "markers": markers,
        "claim": claim,
        "mechanism": mechanism,
        "scene": scene,
        "insight": insight,
        "preview": preview,
        "relationships": relationships,
        "prefer_a": prefer_a,
        "prefer_b": prefer_b,
    }


_SPECS: tuple[dict[str, Any], ...] = (
    _spec(
        "common_ground",
        "mars",
        "mercury",
        "soft",
        "impulse_into_words",
        "wording_of_impulse",
        ("формулир", "шаг"),
        "Желание действовать может получить слова раньше, чем станет спором.",
        "Ты можешь уже хотеть сделать следующий шаг, а {nom} — успеть назвать его понятной формулировкой. Сближает не общая суета, а то, что действие становится ясной фразой, пока его ещё не нужно защищать.",
        "Так может складываться разговор, в котором общего плана ещё нет, а следующий шаг уже можно произнести вслух.",
        "Контакт держится на том, что шаг успевает стать понятной формулировкой, и этим отделён от спора о близости.",
        "Следующий шаг успевает стать ясной формулировкой до того, как его приходится отстаивать.",
        prefer_a="pluto",
        prefer_b="saturn",
    ),
    _spec(
        "common_ground",
        "mercury",
        "mars",
        "soft",
        "words_take_impulse",
        "wording_of_impulse",
        ("формулир", "шаг"),
        "Шаг {gen} может получить у тебя формулировку раньше спора.",
        "Когда {nom} уже хочет действовать, ты можешь собрать этот шаг в понятную формулировку. Сближает то, что действие становится словами, пока его ещё не нужно отстаивать.",
        "Так может складываться разговор, где {nom} уже готов действовать, а ты успеваешь назвать шаг до спора.",
        "Контакт держится на том, что желание действовать становится формулировкой, а не на общей суете.",
        "Шаг {gen} успевает получить у тебя формулировку до спора.",
        prefer_a="saturn",
        prefer_b="pluto",
    ),
    _spec(
        "common_ground",
        "venus",
        "mars",
        "soft",
        "desire_meets_taste",
        "taste_and_drive",
        ("интерес", "жест"),
        "Интерес может совпасть с желанием действовать ещё до общего плана.",
        "Твой интерес к человеку и готовность {gen} действовать могут совпасть в одном жесте. Притяжение здесь в том, что внимание и желание начать появляются вместе, а не в одинаковом характере.",
        "Так может начаться встреча, где внимание к человеку и желание что-то сделать появляются в одном жесте, ещё до разговора о планах.",
        "Контакт держится на том, что интерес и действие узнают друг друга раньше договорённости.",
        "Интерес и желание действовать узнают друг друга раньше общего плана.",
        relationships=frozenset({"romantic"}),
        prefer_a="mars",
        prefer_b="venus",
    ),
    _spec(
        "common_ground",
        "venus",
        "mars",
        "soft",
        "care_meets_action",
        "care_and_action",
        ("поддерж", "дело"),
        "Поддержка и готовность взяться за дело встречаются в одном жесте.",
        "Твоя поддержка встречает у {gen} готовность взяться за дело, не дожидаясь длинного согласования. Сближает именно этот жест: поддержка делает дело возможным, а дело даёт поддержке конкретный повод. Это не одинаковый характер.",
        "Так может выглядеть общая задача, где один уже включается в дело, а другой держит поддержку рядом.",
        "Контакт держится на том, что поддержка и дело узнают друг друга в одной сцене.",
        "Поддержка и дело здесь встречаются раньше длинного обсуждения.",
        relationships=frozenset({"friendship", "family"}),
        prefer_a="mars",
        prefer_b="venus",
    ),
    _spec(
        "common_ground",
        "moon",
        "venus",
        "soft",
        "warmth_before_explanation",
        "feeling_meets_warmth",
        ("тепло", "отклик"),
        "Тепло может появиться раньше объяснения.",
        "Ты можешь откликнуться, а {nom} — проявить тепло, ещё до того как это нужно объяснять. Сближает узнавание настроения, а не общий темперамент.",
        "Так может ощущаться пауза рядом, в которой отклик уже есть, а объяснять его ещё не пришлось.",
        "Контакт держится на том, что тепло появляется раньше рассказа о нём, и это отдельная сцена, не спор.",
        "Отклик и тепло здесь появляются раньше объяснения.",
        prefer_a="venus",
        prefer_b="moon",
    ),
    _spec(
        "differences",
        "venus",
        "mars",
        "hard",
        "affection_meets_will",
        "closeness_bid",
        ("симпат", "прям"),
        "Проявление симпатии может получить слишком прямой ответ.",
        "Ты можешь ждать мягкого отклика на проявление симпатии, а {nom} — отвечать более прямо и сразу переходить к действию. Жест ищет принятия, а навстречу приходит желание сразу что-то сделать.",
        "Так может случиться в момент близости, где знак внимания уже сделан, а вместо спокойного приёма включается встречное действие.",
        "Задевает не различие характеров целиком, а подмена: место принятия занимает ответ действием.",
        "Знак симпатии может столкнуться с ответом, который уже является действием.",
        relationships=frozenset({"romantic"}),
        prefer_a="jupiter",
        prefer_b="uranus",
    ),
    _spec(
        "differences",
        "mars",
        "venus",
        "hard",
        "will_meets_affection",
        "closeness_bid",
        ("симпат", "прям"),
        "Действие может прийти туда, где {nom} ждал принятия.",
        "Ты можешь отвечать действием и слишком прямо там, где {nom} уже проявил симпатию и ждал, что её примут. Стык в этой подмене, не в различии характеров целиком.",
        "Так может случиться в момент близости, где {nom} уже показал симпатию, а в ответ сразу включается действие.",
        "Задевает не сам факт различия, а то, что место принятия занимает ответ действием.",
        "Действие может прийти вместо принятия жеста симпатии.",
        relationships=frozenset({"romantic"}),
        prefer_a="uranus",
        prefer_b="jupiter",
    ),
    _spec(
        "differences",
        "venus",
        "sun",
        "hard",
        "warmth_meets_presence",
        "closeness_bid",
        ("симпат", "прям"),
        "Знак симпатии может встретить ответ, в котором человек говорит о себе.",
        "Твой жест ищет принятия симпатии, а {nom} отвечает более прямо и говорит о собственной позиции. Это подмена приёма ответом о себе, не общая разница потребностей.",
        "Так может выглядеть сцена, где знак внимания уже есть, а ответ звучит как заявление о себе.",
        "Задевает именно эта подмена: вместо принятия симпатии звучит ответ о себе.",
        "Знак симпатии может получить в ответ заявление о себе.",
        relationships=frozenset({"romantic"}),
        prefer_a="jupiter",
        prefer_b="mars",
    ),
    _spec(
        "differences",
        "mercury",
        "moon",
        "hard",
        "words_before_feeling",
        "speech_vs_pause",
        ("пауз", "ясн"),
        "Ясность может прийти раньше, чем отклик успел сложиться.",
        "Твоё объяснение уже ищет ясность, а отклик {gen} ещё держит паузу. Стык в том, что это один и тот же момент, а не две разные темы.",
        "Так может выглядеть короткий разговор, где вывод уже произнесён, а у {gen} ещё нет готового ответа.",
        "Задевает не предмет разговора, а то, что пауза и ясность занимают одно мгновение.",
        "Вывод может прозвучать, пока отклик ещё не сложился.",
        prefer_a="saturn",
        prefer_b="saturn",
    ),
    _spec(
        "differences",
        "moon",
        "mercury",
        "hard",
        "feeling_before_words",
        "speech_vs_pause",
        ("пауз", "ясн"),
        "Пауза может занять момент, в котором {nom} уже ищет ясность.",
        "Тебе ещё нужна пауза, а объяснение {gen} уже собирает ясность. Стык в одном моменте, не в разных темах разговора.",
        "Так может выглядеть разговор, где {nom} уже назвал вывод, а отклик ещё не сложился.",
        "Задевает то, что пауза и ясность претендуют на одно и то же мгновение.",
        "Пауза и ясность могут столкнуться в одном моменте разговора.",
        prefer_a="saturn",
        prefer_b="saturn",
    ),
    _spec(
        "differences",
        "mars",
        "saturn",
        "hard",
        "move_meets_brake",
        "pace_vs_form",
        ("сразу", "договор"),
        "Желание действовать сразу может упереться в требование сначала договориться.",
        "Ты можешь хотеть действовать сразу, а {nom} останавливается, пока договорённость не закреплена. Спор начинается с этого порядка, не с характера целиком.",
        "Так может выглядеть решение, где один уже делает шаг, а другой не отпускает его без ясной договорённости.",
        "Задевает порядок: действие приходит раньше договорённости, и остановка читается как отказ.",
        "Действие сразу может упереться в паузу, пока договорённость не закреплена.",
        prefer_a="pluto",
        prefer_b="sun",
    ),
    _spec(
        "values_needs",
        "saturn",
        "sun",
        "soft",
        "reliability_meets_direction",
        "form_and_direction",
        ("последовательн", "решен"),
        "Одному важно, чтобы слово держали. Другому — самому выбирать.",
        "Тебе может быть важно не только слышать обещания, но и видеть, что их последовательно выполняют. Для {gen} быть собой уже значит самому выбирать следующее решение. Эти потребности стоят рядом и не сливаются в одно требование.",
        "Это проявляется, когда решается, как жить дальше: один смотрит, выполняют ли обещанное, другой не хочет отдавать свой выбор.",
        "Близость здесь не требует, чтобы оба заботились о будущем одним способом. Легко не заметить заботу, если ждать от другого точно такого же доказательства.",
        "Последовательность и собственный выбор подтверждают связь по-разному.",
        prefer_a="moon",
        prefer_b="mars",
    ),
    _spec(
        "values_needs",
        "sun",
        "saturn",
        "soft",
        "direction_meets_reliability",
        "form_and_direction",
        ("последовательн", "решен"),
        "Свой выбор и чужая последовательность подтверждают связь по-разному.",
        "Тебе важно, чтобы решение оставалось твоим. У {gen} надёжность — это когда обещания последовательно выполняют. Это два разных подтверждения, не одно требование.",
        "Это видно в разговоре о том, как будет дальше: один держит своё решение, другой смотрит, держат ли слово.",
        "Совмещается возможность не отдавать свой выбор. Способы подтверждать, что связь настоящая, остаются разными.",
        "Собственное решение и последовательность другого подтверждают связь по-разному.",
        prefer_a="mars",
        prefer_b="moon",
    ),
    _spec(
        "values_needs",
        "moon",
        "saturn",
        "soft",
        "feeling_needs_contour",
        "safety_and_form",
        ("опор", "договор"),
        "Опора и договорённость здесь не обязаны быть одним требованием.",
        "Тебе нужна ощутимая опора. У {gen} надёжность выглядит как договорённость, которую можно удержать. Это соседние нужды, не одно и то же.",
        "Это видно, когда один ищет, на что опереться, а другой хочет заранее понять правила следующего шага.",
        "Договорённость может держать опору, хотя каждый подтверждает надёжность своим способом.",
        "Опора и договорённость могут поддерживать связь, оставаясь разными нуждами.",
        prefer_a="saturn",
        prefer_b="moon",
    ),
    _spec(
        "values_needs",
        "saturn",
        "moon",
        "soft",
        "contour_needs_feeling",
        "safety_and_form",
        ("опор", "договор"),
        "Договорённость и живая опора здесь не одно требование.",
        "Тебе нужно заранее понять правила следующего шага. У {gen} надёжность чувствуется как живая опора, а не как пункт договорённости. Потребности соседствуют и не обязаны совпасть.",
        "Это видно там, где один заранее закрепляет правила, а другому важно сначала почувствовать опору.",
        "Связь выдерживает оба способа, только если договорённость не подменяет собой опору.",
        "Договорённость и опора подтверждают надёжность по-разному.",
        prefer_a="moon",
        prefer_b="saturn",
    ),
    _spec(
        "mutual_expression",
        "jupiter",
        "mars",
        "soft_or_conj",
        "horizon_on_drive",
        "scale_on_drive",
        ("инициатив", "предложен"),
        "Рядом инициатива {gen} может становиться решительнее.",
        "Рядом с тобой {nom} может решительнее проявлять инициативу, а тебе легче поддерживать предложения {gen}. Смелее становится готовность начать, а не разговор о планах.",
        "Так может выглядеть момент, где привычное дело становится началом чего-то большего, потому что кто-то готов его поддержать.",
        "Рядом отдельное решение может ощущаться смелее, потому что его готовы поддержать, а не потому что разговор стал громче.",
        "Рядом инициатива может становиться решительнее, чем в одиночку.",
        prefer_a="mc",
        prefer_b="jupiter",
    ),
    _spec(
        "mutual_expression",
        "mars",
        "jupiter",
        "soft_or_conj",
        "drive_gets_horizon",
        "scale_on_drive",
        ("инициатив", "предложен"),
        "Рядом твоя инициатива может становиться решительнее.",
        "Рядом с {ins} ты можешь решительнее проявлять инициативу, а {nom} — легче поддерживать твои предложения. Смелее становится готовность начать, а не разговор о планах.",
        "Так может выглядеть момент, где привычное дело становится началом чего-то большего, потому что его готовы поддержать.",
        "Присутствие {gen} меняет не громкость разговора, а то, насколько смелым ощущается отдельное решение.",
        "Рядом с {ins} отдельное решение может становиться решительнее.",
        prefer_a="jupiter",
        prefer_b="mc",
    ),
    _spec(
        "mutual_expression",
        "jupiter",
        "sun",
        "soft_or_conj",
        "horizon_on_self",
        "scale_on_drive",
        ("инициатив", "предложен"),
        "Рядом {nom} может смелее заявлять о себе.",
        "Рядом с тобой {nom} может смелее проявлять инициативу и говорить о себе, а тебе легче поддерживать такие предложения. Заметнее становится готовность быть видимым, а не отдельная задача.",
        "Так может выглядеть ситуация, где обычное проявление себя становится предложением более широкого будущего, потому что его готовы принять.",
        "Присутствие меняет не список дел, а то, насколько смело человек заявляет, чего хочет.",
        "Рядом проявление себя может становиться смелее обычного.",
        prefer_a="mc",
        prefer_b="mars",
    ),
)


_NATAL: dict[tuple[frozenset[str], str], dict[str, Any]] = {
    (frozenset({"mars", "pluto"}), "trine"): {
        "points": frozenset({"mars"}),
        "reader": "Тебе может быть трудно бросать начатое на полпути: если ты берёшься за дело, тебе важно довести его до конца.",
        "other": "{dat} может быть трудно бросать начатое на полпути: если дело начато, его труднее оставить.",
    },
    (frozenset({"mercury", "saturn"}), "sextile"): {
        "points": frozenset({"mercury"}),
        "reader": "Тебе легче доверять сказанному, когда в словах есть ясные границы, а не только быстрый ответ.",
        "other": "{dat} легче доверять сказанному, когда в словах есть ясные границы, а не только быстрый ответ.",
    },
    (frozenset({"venus", "jupiter"}), "opposition"): {
        "points": frozenset({"venus"}),
        "reader": "Тебе может быть мало сдержанного знака внимания: симпатия просит более щедрого отклика.",
        "other": "{dat} может быть мало сдержанного знака внимания: симпатия просит более щедрого отклика.",
    },
    (frozenset({"mars", "uranus"}), "sextile"): {
        "points": frozenset({"mars"}),
        "reader": "Ты можешь включаться в действие резко и плохо ждать долгого согласования.",
        "other": "{nom} может включаться в действие резко и плохо ждать долгого согласования.",
    },
    (frozenset({"moon", "saturn"}), "sextile"): {
        "points": frozenset({"moon", "saturn"}),
        "reader": "Тебе может быть важно не только слышать обещание, но и видеть, что человек его выполняет.",
        "other": "{dat} может быть важно не только слышать обещание, но и видеть, что его выполняют.",
    },
    (frozenset({"sun", "mars"}), "conjunction"): {
        "points": frozenset({"sun", "mars"}),
        "reader": "Для тебя показать себя и начать действовать часто одно и то же.",
        "other": "Для {gen} показать себя и начать действовать часто одно и то же.",
    },
    (frozenset({"sun", "jupiter"}), "sextile"): {
        "points": frozenset({"sun"}),
        "reader": "Тебе важно, чтобы у собственного выбора был смысл шире ближайшего шага.",
        "other": "{dat} важно, чтобы у собственного выбора был смысл шире ближайшего шага.",
    },
    (frozenset({"jupiter", "mc"}), "opposition"): {
        "points": frozenset({"jupiter"}),
        "reader": "Тебе может быть тесно в роли, которая не оставляет места для более широкой задачи.",
        "other": "{dat} может быть тесно в роли, которая не оставляет места для более широкой задачи.",
    },
    (frozenset({"mars", "jupiter"}), "sextile"): {
        "points": frozenset({"mars"}),
        "reader": "Тебе легче начинать дело, когда у него есть смысл шире ближайшей задачи.",
        "other": "{dat} легче начинать дело, когда у него есть смысл шире ближайшей задачи.",
    },
    (frozenset({"venus", "mars"}), "trine"): {
        "points": frozenset({"venus", "mars"}),
        "reader": "Вкус и желание действовать у тебя легко оказываются в одном жесте.",
        "other": "У {gen} вкус и желание действовать легко оказываются в одном жесте.",
    },
    (frozenset({"moon", "saturn"}), "square"): {
        "points": frozenset({"moon"}),
        "reader": "Твой отклик и внутренняя строгость могут спорить в одном моменте.",
        "other": "У {gen} отклик и внутренняя строгость могут спорить в одном моменте.",
    },
    (frozenset({"moon", "venus"}), "conjunction"): {
        "points": frozenset({"moon", "venus"}),
        "reader": "Тепло и отклик у тебя легко становятся одним жестом.",
        "other": "У {gen} тепло и отклик легко становятся одним жестом.",
    },
}
