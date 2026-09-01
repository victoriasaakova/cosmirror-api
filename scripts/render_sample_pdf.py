"""Собрать образец PDF на фикстуре Гдыня (fallback-тексты кабинета)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from core.services.pdf_report import render_report_pdf, weasyprint_available
from core.services.report_blueprint import build_report_document
from core.services.swiss_engine import calculate_natal, calculate_sky_now
from core.test_natal_chart import GDYNIA


def sample_report() -> dict:
    natal = calculate_natal(**GDYNIA)
    document = build_report_document(
        natal=natal,
        sky_now=calculate_sky_now(),
        quiz={"name": "Виктория"},
    )
    return {
        "title": "Персональный астрологический отчёт",
        "disclaimer": (
            "Это не прогноз будущего и не замена терапии. "
            "Расчёт — Swiss Ephemeris, тропический зодиак, дома Плацидуса. "
            "Интерпретация — гипотеза, которую стоит проверить на своём опыте."
        ),
        "person": {
            "name": "Виктория",
            "birth_date": "1995-05-26",
            "birth_time": "19:25",
            "birth_place": "Гдыня",
            "has_birth_time": True,
        },
        "document": document,
    }


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "samples" / "cosmirror-report.pdf"
    out.parent.mkdir(parents=True, exist_ok=True)
    print("weasyprint", weasyprint_available(), flush=True)
    pdf = render_report_pdf(sample_report())
    out.write_bytes(pdf)
    print(f"wrote {out} ({len(pdf)} bytes)", flush=True)


if __name__ == "__main__":
    main()
