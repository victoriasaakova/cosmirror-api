"""Контракт данных для HTML/WeasyPrint PDF.

Новый рендерер собирает страницы из document, не из flatten_document_sections.
WEB_TABS не трогаем: веб по-прежнему читает document.sections и presentation.web.tabs.

В document.factual.natal таблица положений лежит в ключе `points`
(это и есть natal_table). Аспекты — в `aspects` (natal_aspects).
Этот модуль отдаёт их под именами, которые ждут вёрстку PDF.
"""

from __future__ import annotations

from typing import Any

from core.services.report_types import PDF_OUTLINE


def pdf_sections(document: dict[str, Any]) -> list[dict[str, Any]]:
    """Секции в порядке PDF_OUTLINE, без схлопывания полей блока."""
    sections = document.get("sections") if isinstance(document.get("sections"), dict) else {}
    out: list[dict[str, Any]] = []
    for key in PDF_OUTLINE:
        section = sections.get(key)
        if not isinstance(section, dict):
            continue
        out.append(
            {
                "id": key,
                "title": section.get("title") or key,
                "layer": section.get("layer"),
                "blocks": list(section.get("blocks") or []),
                "questions": list(section.get("questions") or []),
            }
        )
    return out


def natal_facts_for_pdf(document: dict[str, Any]) -> dict[str, Any]:
    natal = ((document.get("factual") or {}).get("natal") or {})
    if not isinstance(natal, dict):
        natal = {}
    points = list(natal.get("points") or [])
    aspects = list(natal.get("aspects") or [])
    return {
        "natal_table": points,
        "natal_aspects": aspects,
        "houses": list(natal.get("houses") or []),
        "wheel": natal.get("wheel") if isinstance(natal.get("wheel"), dict) else {},
        "has_birth_time": bool(natal.get("has_birth_time")),
        "house_system": natal.get("house_system"),
        "source_paths": {
            "natal_table": "document.factual.natal.points",
            "natal_aspects": "document.factual.natal.aspects",
            "houses": "document.factual.natal.houses",
            "wheel": "document.factual.natal.wheel",
        },
    }


def build_pdf_render_payload(report: dict[str, Any]) -> dict[str, Any]:
    """Вход будущего WeasyPrint-рендерера. Не меняет GET кабинета."""
    document = report.get("document") if isinstance(report.get("document"), dict) else {}
    presentation = document.get("presentation") if isinstance(document.get("presentation"), dict) else {}
    pdf_meta = presentation.get("pdf") if isinstance(presentation.get("pdf"), dict) else {}
    natal = natal_facts_for_pdf(document)
    interpretive = document.get("interpretive") if isinstance(document.get("interpretive"), dict) else {}
    person = report.get("person") if isinstance(report.get("person"), dict) else {}
    quiz = document.get("quiz") if isinstance(document.get("quiz"), dict) else {}
    name = str(person.get("name") or quiz.get("name") or "").strip()
    return {
        "title": report.get("title") or "Персональный астрологический отчёт",
        "subtitle": report.get("subtitle") or "",
        "disclaimer": report.get("disclaimer") or "",
        "person": {**person, "name": name},
        "outline": list(PDF_OUTLINE),
        "theme": pdf_meta.get("theme") or "cosmirror_navy_gold",
        "sections": pdf_sections(document),
        "natal_table": natal["natal_table"],
        "natal_aspects": natal["natal_aspects"],
        "houses": natal["houses"],
        "wheel": natal["wheel"],
        "has_birth_time": natal["has_birth_time"],
        "house_system": natal["house_system"],
        "source_paths": natal["source_paths"],
        "interpretive": {
            "natal": (interpretive.get("natal") or {}).get("payload") if isinstance(interpretive.get("natal"), dict) else {},
            "aspects": (interpretive.get("aspects") or {}).get("payload") if isinstance(interpretive.get("aspects"), dict) else {},
            "cycles": (interpretive.get("cycles") or {}).get("payload") if isinstance(interpretive.get("cycles"), dict) else {},
            "request": (interpretive.get("request") or {}).get("payload") if isinstance(interpretive.get("request"), dict) else {},
            "practice": (interpretive.get("practice") or {}).get("payload") if isinstance(interpretive.get("practice"), dict) else {},
        },
    }
