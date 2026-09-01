"""Сборка PDF персонального отчёта Cosmirror: HTML/CSS → WeasyPrint."""

from __future__ import annotations

from pathlib import Path
from typing import Any

_ASSETS = Path(__file__).resolve().parent.parent / "assets" / "pdf"


def weasyprint_available() -> bool:
    try:
        from weasyprint import HTML  # noqa: F401
    except OSError:
        return False
    except Exception:
        return False
    return True


def render_report_pdf(report: dict[str, Any]) -> bytes:
    if not weasyprint_available():
        from core.services.pdf_report_legacy import render_report_pdf as render_legacy

        return render_legacy(report)

    from weasyprint import HTML

    from core.services.pdf_html import render_report_html

    html = render_report_html(report)
    return HTML(string=html, base_url=str(_ASSETS)).write_pdf()
