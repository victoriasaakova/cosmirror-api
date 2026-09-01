"""Сборка PDF персонального отчёта Cosmirror: navy, Playfair, Onest, карта."""

from __future__ import annotations

from math import cos, radians, sin
from pathlib import Path
from typing import Any

from fpdf import FPDF

_FONTS = Path(__file__).resolve().parent.parent / "assets" / "fonts"
_PLAYFAIR = _FONTS / "PlayfairDisplay-Regular.ttf"
_PLAYFAIR_I = _FONTS / "PlayfairDisplay-Italic.ttf"
_ONEST = _FONTS / "Onest-Regular.ttf"
_ONEST_M = _FONTS / "Onest-Medium.ttf"
_DEJAVU = _FONTS / "DejaVuSans.ttf"
_EYE = Path(__file__).resolve().parent.parent / "assets" / "email_eye.png"

NAVY = (5, 13, 74)
NAVY_DEEP = (4, 10, 52)
GOLD = (246, 231, 161)
CREAM = (244, 239, 232)
MUTED = (180, 186, 210)

PLANET_GLYPH = {
    "sun": "☉",
    "moon": "☽",
    "mercury": "☿",
    "venus": "♀",
    "mars": "♂",
    "jupiter": "♃",
    "saturn": "♄",
    "uranus": "♅",
    "neptune": "♆",
    "pluto": "♇",
}

SIGN_RU_SHORT = {
    "aries": "Овен",
    "taurus": "Телец",
    "gemini": "Близнецы",
    "cancer": "Рак",
    "leo": "Лев",
    "virgo": "Дева",
    "libra": "Весы",
    "scorpio": "Скорпион",
    "sagittarius": "Стрелец",
    "capricorn": "Козерог",
    "aquarius": "Водолей",
    "pisces": "Рыбы",
}


class _ReportPDF(FPDF):
    def header(self) -> None:  # noqa: N802
        self.set_fill_color(*NAVY)
        self.rect(0, 0, self.w, self.h, "F")

    def footer(self) -> None:  # noqa: N802
        self.set_y(-12)
        self.set_font("Onest", size=8)
        self.set_text_color(*GOLD)
        self.cell(0, 8, f"Cosmirror  ·  {self.page_no()}", align="C")


def render_report_pdf(report: dict[str, Any]) -> bytes:
    missing = [path for path in (_PLAYFAIR, _PLAYFAIR_I, _ONEST, _ONEST_M, _DEJAVU) if not path.exists()]
    if missing:
        raise RuntimeError(f"Нет шрифтов для PDF: {', '.join(str(p.name) for p in missing)}")

    pdf = _ReportPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(16, 18, 16)
    pdf.add_font("Playfair", style="", fname=str(_PLAYFAIR))
    pdf.add_font("Playfair", style="I", fname=str(_PLAYFAIR_I))
    pdf.add_font("Onest", style="", fname=str(_ONEST))
    pdf.add_font("Onest", style="B", fname=str(_ONEST_M))
    pdf.add_font("DejaVu", style="", fname=str(_DEJAVU))

    _first_page(pdf, report)
    pdf.add_page()

    def write(text: str, *, italic: bool = False, medium: bool = False, size: int = 11, height: float = 6, color=CREAM) -> None:
        pdf.set_text_color(*color)
        pdf.set_x(pdf.l_margin)
        if italic:
            pdf.set_font("Playfair", style="I", size=size)
        elif medium:
            pdf.set_font("Onest", style="B", size=size)
        else:
            pdf.set_font("Onest", style="", size=size)
        pdf.multi_cell(w=pdf.epw, h=height, text=text)

    for section in report.get("sections") or []:
        if not isinstance(section, dict):
            continue
        title = str(section.get("title") or "").strip()
        if title:
            if pdf.get_y() > pdf.h - 40:
                pdf.add_page()
            write(title, italic=True, size=22, height=10, color=GOLD)
            pdf.set_draw_color(*GOLD)
            pdf.set_line_width(0.35)
            y = pdf.get_y()
            pdf.line(pdf.l_margin, y, pdf.l_margin + 36, y)
            pdf.ln(5)
        for block in section.get("blocks") or []:
            if not isinstance(block, dict):
                continue
            heading = str(block.get("title") or "").strip()
            text = str(block.get("text") or "").strip()
            if pdf.get_y() > pdf.h - 32:
                pdf.add_page()
            if heading:
                write(heading, medium=True, size=12, height=7, color=GOLD)
            if text:
                write(text, size=11, height=5.8)
            pdf.ln(2.4)
        pdf.ln(4)

    disclaimer = str(report.get("disclaimer") or "").strip()
    if disclaimer:
        write(disclaimer, size=9, height=5, color=MUTED)

    return bytes(pdf.output())


def _first_page(pdf: _ReportPDF, report: dict[str, Any]) -> None:
    pdf.add_page()
    pdf.set_text_color(*GOLD)

    if _EYE.exists():
        size = 16
        pdf.image(str(_EYE), x=(pdf.w - size) / 2, y=10, w=size)
        pdf.set_y(28)
    else:
        pdf.set_y(14)

    pdf.set_font("Playfair", style="I", size=16)
    pdf.cell(0, 8, "Cosmirror", align="C")
    pdf.ln(4)

    pdf.set_font("Onest", size=10)
    pdf.set_text_color(*CREAM)
    pdf.cell(0, 6, str(report.get("title") or "Персональный астрологический отчёт"), align="C")
    subtitle = str(report.get("subtitle") or "").strip()
    if subtitle:
        pdf.ln(4)
        pdf.set_text_color(*GOLD)
        pdf.set_font("Onest", size=9)
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(w=pdf.epw, h=5, text=subtitle, align="C")

    document = report.get("document") if isinstance(report.get("document"), dict) else {}
    natal = ((document.get("factual") or {}).get("natal") or {})
    wheel = natal.get("wheel") if isinstance(natal, dict) else None
    if isinstance(wheel, dict) and wheel.get("planets"):
        _draw_wheel(pdf, wheel, cy=118, radius=62)
    else:
        pdf.ln(8)
        pdf.set_font("Playfair", style="I", size=14)
        pdf.set_text_color(*GOLD)
        pdf.cell(0, 8, "Натальная карта", align="C")

    pdf.set_y(pdf.h - 28)
    pdf.set_font("Onest", size=8)
    pdf.set_text_color(*MUTED)
    pdf.cell(0, 5, "Swiss Ephemeris  ·  тропический зодиак  ·  Плацидус", align="C")


def _wheel_xy(asc_lon: float, lon: float, cx: float, cy: float, r: float) -> tuple[float, float]:
    theta = radians(asc_lon - lon)
    return cx - r * cos(theta), cy + r * sin(theta)


def _draw_wheel(pdf: _ReportPDF, wheel: dict[str, Any], *, cy: float, radius: float) -> None:
    cx = pdf.w / 2
    r_out = radius
    r_in = radius * 0.78
    r_house = radius * 0.54
    r_planet = radius * 0.62
    asc = float(wheel.get("ascendant_longitude") or 0.0)

    pdf.set_draw_color(*GOLD)
    pdf.set_line_width(0.45)
    pdf.ellipse(cx - r_out, cy - r_out, 2 * r_out, 2 * r_out, style="D")
    pdf.set_line_width(0.2)
    pdf.set_draw_color(246, 231, 161)
    pdf.ellipse(cx - r_in, cy - r_in, 2 * r_in, 2 * r_in, style="D")
    pdf.set_draw_color(180, 186, 210)
    pdf.ellipse(cx - r_house, cy - r_house, 2 * r_house, 2 * r_house, style="D")

    pdf.set_font("Onest", size=6)
    for sign in wheel.get("signs") or []:
        start = float(sign.get("start") or 0)
        x1, y1 = _wheel_xy(asc, start, cx, cy, r_in)
        x2, y2 = _wheel_xy(asc, start, cx, cy, r_out)
        pdf.set_draw_color(*GOLD)
        pdf.set_line_width(0.15)
        pdf.line(x1, y1, x2, y2)
        mid = start + 15
        tx, ty = _wheel_xy(asc, mid, cx, cy, (r_in + r_out) / 2)
        pdf.set_text_color(*GOLD)
        label = str(sign.get("sign_ru") or SIGN_RU_SHORT.get(str(sign.get("sign") or ""), ""))
        pdf.set_xy(tx - 10, ty - 2)
        pdf.cell(20, 4, label[:10], align="C")

    for house in wheel.get("houses") or []:
        cusp = house.get("cusp")
        if cusp is None:
            continue
        x1, y1 = _wheel_xy(asc, float(cusp), cx, cy, 4)
        x2, y2 = _wheel_xy(asc, float(cusp), cx, cy, r_house)
        pdf.set_draw_color(246, 231, 161)
        pdf.set_line_width(0.28 if int(house.get("house") or 0) in (1, 4, 7, 10) else 0.12)
        pdf.line(x1, y1, x2, y2)

    by_key = {row.get("key"): row for row in (wheel.get("planets") or []) if row.get("key")}
    for line in wheel.get("aspects") or []:
        a = by_key.get(line.get("a"))
        b = by_key.get(line.get("b"))
        if not a or not b:
            continue
        x1, y1 = _wheel_xy(asc, float(a["longitude"]), cx, cy, r_house * 0.92)
        x2, y2 = _wheel_xy(asc, float(b["longitude"]), cx, cy, r_house * 0.92)
        hard = str(line.get("kind") or "") == "hard"
        pdf.set_draw_color(*(GOLD if hard else MUTED))
        pdf.set_line_width(0.28 if hard else 0.16)
        pdf.line(x1, y1, x2, y2)

    pdf.set_font("DejaVu", size=9)
    used: list[tuple[float, float]] = []
    for planet in wheel.get("planets") or []:
        lon = float(planet.get("longitude") or 0)
        r = r_planet
        x, y = _wheel_xy(asc, lon, cx, cy, r)
        for ux, uy in used:
            if (x - ux) ** 2 + (y - uy) ** 2 < 36:
                r += 5
                x, y = _wheel_xy(asc, lon, cx, cy, r)
        used.append((x, y))
        pdf.set_fill_color(*NAVY_DEEP)
        pdf.set_draw_color(*GOLD)
        pdf.set_line_width(0.25)
        pdf.ellipse(x - 3.4, y - 3.4, 6.8, 6.8, style="FD")
        glyph = PLANET_GLYPH.get(str(planet.get("key") or ""), str(planet.get("glyph") or ""))
        pdf.set_text_color(*CREAM)
        pdf.set_xy(x - 4, y - 3)
        pdf.cell(8, 6, glyph, align="C")

    pdf.set_font("Onest", style="B", size=7)
    pdf.set_text_color(*GOLD)
    ax, ay = _wheel_xy(asc, asc, cx, cy, r_out + 6)
    pdf.set_xy(ax - 8, ay - 3)
    pdf.cell(16, 6, "ASC", align="C")
    mc = wheel.get("mc_longitude")
    if mc is not None:
        mx, my = _wheel_xy(asc, float(mc), cx, cy, r_out + 6)
        pdf.set_xy(mx - 8, my - 3)
        pdf.cell(16, 6, "MC", align="C")
