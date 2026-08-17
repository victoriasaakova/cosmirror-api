"""Сборка PDF персонального отчёта Cosmirror."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fpdf import FPDF

_FONTS = Path(__file__).resolve().parent.parent / "assets" / "fonts"
_REGULAR = _FONTS / "DejaVuSans.ttf"
_BOLD = _FONTS / "DejaVuSans-Bold.ttf"
_EYE = Path(__file__).resolve().parent.parent / "assets" / "email_eye.png"

NAVY = (5, 13, 74)
GOLD = (246, 231, 161)
INK = (10, 26, 58)
MUTED = (90, 96, 120)
CREAM = (244, 239, 232)


class _ReportPDF(FPDF):
    def footer(self) -> None:  # noqa: N802 — fpdf API
        if self.page_no() == 1:
            return
        self.set_y(-14)
        self.set_font("DejaVu", size=8)
        self.set_text_color(*MUTED)
        self.cell(0, 8, f"Cosmirror  ·  {self.page_no()}", align="C")


def render_report_pdf(report: dict[str, Any]) -> bytes:
    if not _REGULAR.exists() or not _BOLD.exists():
        raise RuntimeError(f"Нет шрифтов для PDF в {_FONTS}")

    pdf = _ReportPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(18, 22, 18)
    pdf.add_font("DejaVu", style="", fname=str(_REGULAR))
    pdf.add_font("DejaVu", style="B", fname=str(_BOLD))

    _cover(pdf, report)
    pdf.add_page()
    pdf.set_text_color(*INK)

    def write(text: str, *, bold: bool = False, size: int = 11, height: float = 6, color=INK) -> None:
        pdf.set_text_color(*color)
        pdf.set_x(pdf.l_margin)
        pdf.set_font("DejaVu", style="B" if bold else "", size=size)
        pdf.multi_cell(w=pdf.epw, h=height, text=text)

    for section in report.get("sections") or []:
        if not isinstance(section, dict):
            continue
        title = str(section.get("title") or "").strip()
        if title:
            write(title.upper(), bold=True, size=11, height=8, color=NAVY)
            pdf.set_draw_color(*GOLD)
            pdf.set_line_width(0.4)
            y = pdf.get_y()
            pdf.line(pdf.l_margin, y, pdf.l_margin + 28, y)
            pdf.ln(4)
        for block in section.get("blocks") or []:
            if not isinstance(block, dict):
                continue
            heading = str(block.get("title") or "").strip()
            text = str(block.get("text") or "").strip()
            if heading:
                write(heading, bold=True, size=12, height=7)
            if text:
                write(text, size=11, height=6)
            pdf.ln(2)
        pdf.ln(3)

    disclaimer = str(report.get("disclaimer") or "").strip()
    if disclaimer:
        write(disclaimer, size=9, height=5, color=MUTED)

    return bytes(pdf.output())


def _cover(pdf: _ReportPDF, report: dict[str, Any]) -> None:
    pdf.add_page()
    pdf.set_fill_color(*NAVY)
    pdf.rect(0, 0, pdf.w, pdf.h, "F")
    pdf.set_text_color(*GOLD)

    if _EYE.exists():
        size = 28
        pdf.image(str(_EYE), x=(pdf.w - size) / 2, y=42, w=size)

    pdf.set_y(78 if _EYE.exists() else 70)
    pdf.set_font("DejaVu", style="", size=16)
    pdf.cell(0, 10, "Cosmirror", align="C")
    pdf.ln(16)
    pdf.set_font("DejaVu", style="B", size=26)
    title = str(report.get("title") or "Персональный отчёт")
    pdf.set_x(pdf.l_margin)
    pdf.multi_cell(w=pdf.epw, h=12, text=title, align="C")
    subtitle = str(report.get("subtitle") or "").strip()
    if subtitle:
        pdf.ln(6)
        pdf.set_text_color(*CREAM)
        pdf.set_font("DejaVu", size=12)
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(w=pdf.epw, h=7, text=subtitle, align="C")

    person = report.get("person") if isinstance(report.get("person"), dict) else {}
    name = str(person.get("name") or "").strip()
    bits = [part for part in (
        name,
        person.get("birth_date") or "",
        person.get("birth_place") or "",
    ) if part]
    if bits:
        pdf.ln(10)
        pdf.set_text_color(*GOLD)
        pdf.set_font("DejaVu", size=11)
        pdf.cell(0, 8, " · ".join(bits), align="C")
