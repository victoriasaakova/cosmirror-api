"""Сборка PDF персонального отчёта Cosmirror."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fpdf import FPDF

_FONTS = Path(__file__).resolve().parent.parent / "assets" / "fonts"
_REGULAR = _FONTS / "DejaVuSans.ttf"
_BOLD = _FONTS / "DejaVuSans-Bold.ttf"


class _ReportPDF(FPDF):
    def footer(self) -> None:  # noqa: N802 — fpdf API
        self.set_y(-14)
        self.set_font("DejaVu", size=8)
        self.set_text_color(90, 90, 90)
        self.cell(0, 8, f"Cosmirror  ·  {self.page_no()}", align="C")


def render_report_pdf(report: dict[str, Any]) -> bytes:
    if not _REGULAR.exists() or not _BOLD.exists():
        raise RuntimeError(f"Нет шрифтов для PDF в {_FONTS}")

    pdf = _ReportPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(18, 18, 18)
    pdf.add_font("DejaVu", style="", fname=str(_REGULAR))
    pdf.add_font("DejaVu", style="B", fname=str(_BOLD))
    pdf.add_page()
    pdf.set_text_color(10, 26, 58)

    def write(text: str, *, bold: bool = False, size: int = 11, height: float = 6) -> None:
        pdf.set_x(pdf.l_margin)
        pdf.set_font("DejaVu", style="B" if bold else "", size=size)
        pdf.multi_cell(w=pdf.epw, h=height, text=text)

    write("Cosmirror", bold=True, size=11, height=8)
    write(str(report.get("title") or "Персональный отчёт"), bold=True, size=20, height=9)
    subtitle = str(report.get("subtitle") or "").strip()
    if subtitle:
        pdf.set_text_color(70, 70, 80)
        write(subtitle, size=11)
        pdf.set_text_color(10, 26, 58)
    pdf.ln(4)

    for section in report.get("sections") or []:
        if not isinstance(section, dict):
            continue
        title = str(section.get("title") or "").strip()
        if title:
            write(title, bold=True, size=14, height=8)
            pdf.ln(1)
        for block in section.get("blocks") or []:
            if not isinstance(block, dict):
                continue
            heading = str(block.get("title") or "").strip()
            text = str(block.get("text") or "").strip()
            if heading:
                write(heading, bold=True, size=11)
            if text:
                write(text, size=11)
            pdf.ln(2)
        pdf.ln(2)

    disclaimer = str(report.get("disclaimer") or "").strip()
    if disclaimer:
        pdf.set_text_color(90, 90, 90)
        write(disclaimer, size=9, height=5)

    return bytes(pdf.output())
