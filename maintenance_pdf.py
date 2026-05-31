"""
maintenance_pdf.py — Генератор PDF регламента ТО для TECHFORGE
Использует ReportLab + DejaVu (полная поддержка кириллицы)
"""

from io import BytesIO
from typing import List, Dict, Any
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import (
    BaseDocTemplate, PageTemplate, Frame,
    Paragraph, Spacer, Table, TableStyle,
    HRFlowable, KeepTogether
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
import datetime
import os

# ── Шрифты ────────────────────────────────────────────────────────────────────

FONT_DIR = os.path.join(os.path.dirname(__file__), "fonts")
pdfmetrics.registerFont(TTFont("DV",      f"{FONT_DIR}/GoogleSans-Regular.ttf"))
pdfmetrics.registerFont(TTFont("DV-Bold", f"{FONT_DIR}/GoogleSans-Bold.ttf"))
pdfmetrics.registerFont(TTFont("DV-Mono", f"{FONT_DIR}/Roboto-Regular.ttf"))  # моно = Roboto
pdfmetrics.registerFontFamily("DV", normal="DV", bold="DV-Bold")

# ── Цветовая палитра (тёмный tech-стиль, но для белой бумаги) ─────────────────
C_NAVY      = colors.HexColor("#0F2744")   # заголовки шапки
C_BLUE      = colors.HexColor("#1D4ED8")   # акцент
C_BLUE_LITE = colors.HexColor("#DBEAFE")   # фон шапок таблиц
C_STRIPE    = colors.HexColor("#F0F5FF")   # чётные строки
C_RULE      = colors.HexColor("#CBD5E1")   # горизонтальные линии
C_TEXT      = colors.HexColor("#1E293B")   # основной текст
C_MUTED     = colors.HexColor("#64748B")   # вспомогательный
C_WHITE     = colors.white
C_RED_BG    = colors.HexColor("#FEF2F2")
C_RED_TEXT  = colors.HexColor("#991B1B")
C_GREEN_BG  = colors.HexColor("#F0FDF4")
C_GREEN_TEXT= colors.HexColor("#166534")

W, H = A4  # 210 × 297 мм


# ── Стили параграфов ───────────────────────────────────────────────────────────
def _s(name, **kw) -> ParagraphStyle:
    base = dict(fontName="DV", fontSize=9, leading=13, textColor=C_TEXT,
                spaceAfter=0, spaceBefore=0, leftIndent=0)
    base.update(kw)
    return ParagraphStyle(name, **base)

S = {
    "h1":       _s("h1",   fontName="DV-Bold", fontSize=20, textColor=C_WHITE,
                            leading=24, spaceAfter=2),
    "h1sub":    _s("h1sub",fontName="DV", fontSize=10, textColor=colors.HexColor("#93C5FD"),
                            leading=14),
    "h2":       _s("h2",   fontName="DV-Bold", fontSize=13, textColor=C_NAVY,
                            leading=17, spaceBefore=14, spaceAfter=6),
    "h3":       _s("h3",   fontName="DV-Bold", fontSize=10, textColor=C_BLUE,
                            leading=14, spaceBefore=8, spaceAfter=3),
    "body":     _s("body", fontSize=9,  leading=14, spaceAfter=2),
    "small":    _s("small",fontSize=8,  leading=12, textColor=C_MUTED),
    "mono":     _s("mono", fontName="DV-Mono", fontSize=8, leading=12),
    "badge_b":  _s("badge_b", fontName="DV-Bold", fontSize=8,
                              textColor=C_BLUE, alignment=TA_CENTER),
    "tbl_hdr":  _s("tbl_hdr", fontName="DV-Bold", fontSize=8,
                               textColor=C_NAVY, leading=11),
    "tbl_cell": _s("tbl_cell",fontSize=8, leading=12),
    "tbl_mono": _s("tbl_mono",fontName="DV-Mono", fontSize=8,
                               textColor=C_BLUE, leading=12),
    "step_num": _s("step_num", fontName="DV-Bold", fontSize=9,
                               textColor=C_BLUE, alignment=TA_CENTER),
    "step_txt": _s("step_txt", fontSize=9, leading=13),
    "warn":     _s("warn",  fontSize=8, leading=12, textColor=C_RED_TEXT),
    "ok":       _s("ok",    fontSize=8, leading=12, textColor=C_GREEN_TEXT),
    "meta_key": _s("meta_key", fontSize=8, textColor=C_MUTED),
    "meta_val": _s("meta_val", fontName="DV-Bold", fontSize=9, textColor=C_TEXT),
}


# ── Вспомогательные строители ──────────────────────────────────────────────────

def _hr(color=C_RULE, thickness=0.5):
    return HRFlowable(width="100%", thickness=thickness, color=color,
                      spaceAfter=4, spaceBefore=4)


def _sp(h=4):
    return Spacer(1, h * mm)


def _tbl_style(extra=()) -> TableStyle:
    base = [
        ("FONTNAME",    (0, 0), (-1, 0), "DV-Bold"),
        ("FONTSIZE",    (0, 0), (-1, 0), 8),
        ("BACKGROUND",  (0, 0), (-1, 0), C_BLUE_LITE),
        ("TEXTCOLOR",   (0, 0), (-1, 0), C_NAVY),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [C_WHITE, C_STRIPE]),
        ("GRID",        (0, 0), (-1, -1), 0.3, C_RULE),
        ("TOPPADDING",  (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING",(0,0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",(0, 0), (-1, -1), 6),
        ("VALIGN",      (0, 0), (-1, -1), "MIDDLE"),
    ]
    base.extend(extra)
    return TableStyle(base)


# ── Шапка страницы (header/footer через PageTemplate) ─────────────────────────

class _TechForgePage(PageTemplate):
    def __init__(self, doc, meta: Dict):
        self.meta = meta
        frame = Frame(15*mm, 18*mm, W - 30*mm, H - 42*mm,
                      leftPadding=0, rightPadding=0,
                      topPadding=0, bottomPadding=0, id="main")
        super().__init__("techforge", [frame])

    def beforeDrawPage(self, canvas, doc):
        canvas.saveState()
        if doc.page == 1:
            self._draw_header(canvas, doc)
        self._draw_footer(canvas, doc)
        canvas.restoreState()

    def _draw_header(self, c, doc):
        # Тёмная полоса
        c.setFillColor(C_NAVY)
        c.rect(0, H - 28*mm, W, 28*mm, fill=1, stroke=0)
        # Синий акцент слева
        c.setFillColor(C_BLUE)
        c.rect(0, H - 28*mm, 4*mm, 28*mm, fill=1, stroke=0)
        # Логотип
        c.setFont("DV-Bold", 14)
        c.setFillColor(C_WHITE)
        c.drawString(10*mm, H - 14*mm, "TECHFORGE")
        c.setFont("DV", 8)
        c.setFillColor(colors.HexColor("#93C5FD"))
        c.drawString(10*mm, H - 20*mm, "Регламент технического обслуживания ПК")
        # Мета справа
        c.setFont("DV", 7.5)
        c.setFillColor(colors.HexColor("#94A3B8"))
        right_x = W - 15*mm
        c.drawRightString(right_x, H - 11*mm, self.meta.get("cpu", ""))
        c.drawRightString(right_x, H - 17*mm, self.meta.get("gpu", ""))
        c.drawRightString(right_x, H - 23*mm, self.meta.get("date", ""))

    def _draw_footer(self, c, doc):
        c.setFillColor(C_RULE)
        c.rect(0, 12*mm, W, 0.3*mm, fill=1, stroke=0)
        c.setFont("DV", 7)
        c.setFillColor(C_MUTED)
        c.drawString(15*mm, 7*mm, "TECHFORGE — Автоматически сгенерированный регламент ТО")
        c.drawRightString(W - 15*mm, 7*mm, f"Стр. {doc.page}")


# ── Секция «Сводный регламент» ─────────────────────────────────────────────────

def _build_schedule(tasks: List[Dict], intensity: str) -> List:
    label_map = {"light": "Лёгкая", "medium": "Средняя", "high": "Высокая"}
    intensity_label = label_map.get(intensity, intensity)

    elems = []
    elems.append(_sp(3))
    elems.append(Paragraph("Сводный регламент", S["h2"]))
    elems.append(Paragraph(
        f"Профиль интенсивности: <b>{intensity_label}</b> · "
        f"Всего видов работ: <b>{len(tasks)}</b>",
        S["small"]
    ))
    elems.append(_sp(3))

    col_w = [(W - 30*mm) * x for x in (0.05, 0.38, 0.22, 0.22, 0.13)]
    header = [
        Paragraph("#",                S["tbl_hdr"]),
        Paragraph("Вид работы",       S["tbl_hdr"]),
        Paragraph("Применимость",     S["tbl_hdr"]),
        Paragraph("Периодичность",    S["tbl_hdr"]),
        Paragraph("Утилита",          S["tbl_hdr"]),
    ]
    rows = [header]
    for i, t in enumerate(tasks, 1):
        interval = t.get("interval", "—")
        is_high  = intensity == "high" and t.get("high_interval") != t.get("base_interval")
        interval_p = Paragraph(
            f'<font color="#1D4ED8"><b>{interval}</b></font>'
            + (' <font size="7" color="#60A5FA">↑</font>' if is_high else ""),
            S["tbl_cell"]
        )
        rows.append([
            Paragraph(str(i).zfill(2), S["tbl_mono"]),
            Paragraph(t.get("title", ""), S["tbl_cell"]),
            Paragraph(t.get("applicability", ""), S["small"]),
            interval_p,
            Paragraph(t.get("utility") or "—", S["small"]),
        ])

    tbl = Table(rows, colWidths=col_w, repeatRows=1)
    tbl.setStyle(_tbl_style())
    elems.append(tbl)
    return elems


# ── Секция «Инструкции» ────────────────────────────────────────────────────────

def _build_instructions(tasks: List[Dict]) -> List:
    elems = []
    elems.append(_sp(5))
    elems.append(Paragraph("Пошаговые инструкции", S["h2"]))

    for i, t in enumerate(tasks, 1):
        block = []
        # Заголовок задачи
        block.append(_sp(2))
        block.append(Paragraph(f"{i}. {t.get('title', '')}", S["h3"]))
        block.append(Paragraph(
            f"Применимость: {t.get('applicability', '')} · "
            f"Периодичность: <b>{t.get('interval', '—')}</b>",
            S["small"]
        ))
        block.append(_sp(2))

        # 3 колонки: инструменты | меры безопасности | признаки успеха
        tools_txt  = "<br/>".join(f"• {x}" for x in t.get("tools", []))
        safety_txt = "<br/>".join(f"! {x}" for x in t.get("safety", []))
        success    = t.get("success", "—")

        info_data = [[
            Paragraph("🔧 Инструменты",    S["tbl_hdr"]),
            Paragraph("⚠ Меры безопасности", S["tbl_hdr"]),
            Paragraph("✓ Признаки успеха",  S["tbl_hdr"]),
        ],[
            Paragraph(tools_txt or "—",  S["tbl_cell"]),
            Paragraph(safety_txt or "—", S["warn"]),
            Paragraph(success,           S["ok"]),
        ]]
        iw = (W - 30*mm) / 3
        info_tbl = Table(info_data, colWidths=[iw, iw, iw])
        info_tbl.setStyle(TableStyle([
            ("BACKGROUND",   (0, 0), (-1, 0), C_BLUE_LITE),
            ("BACKGROUND",   (1, 1), (1, 1), C_RED_BG),
            ("BACKGROUND",   (2, 1), (2, 1), C_GREEN_BG),
            ("GRID",         (0, 0), (-1, -1), 0.3, C_RULE),
            ("VALIGN",       (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING",   (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 6),
            ("LEFTPADDING",  (0, 0), (-1, -1), 7),
            ("RIGHTPADDING", (0, 0), (-1, -1), 7),
        ]))
        block.append(info_tbl)
        block.append(_sp(3))

        # Нумерованные шаги
        block.append(Paragraph("Порядок выполнения:", _s("steps_lbl",
                     fontName="DV-Bold", fontSize=8, textColor=C_MUTED,
                     spaceBefore=2, spaceAfter=4)))
        step_rows = []
        for j, step in enumerate(t.get("steps", []), 1):
            step_rows.append([
                Paragraph(str(j), S["step_num"]),
                Paragraph(step,   S["step_txt"]),
            ])
        if step_rows:
            sw = W - 30*mm
            stbl = Table(step_rows, colWidths=[8*mm, sw - 8*mm])
            stbl.setStyle(TableStyle([
                ("ROWBACKGROUNDS", (0, 0), (-1, -1), [C_WHITE, C_STRIPE]),
                ("GRID",           (0, 0), (-1, -1), 0.2, C_RULE),
                ("VALIGN",         (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING",     (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING",  (0, 0), (-1, -1), 5),
                ("LEFTPADDING",    (0, 0), (-1, -1), 5),
                ("ALIGN",          (0, 0), (0, -1),  "CENTER"),
                ("BACKGROUND",     (0, 0), (0, -1),  C_BLUE_LITE),
            ]))
            block.append(stbl)

        block.append(_hr())
        elems.append(KeepTogether(block[:6]))  # шапку+инфо держим вместе
        elems.extend(block[6:])

    return elems


# ── Секция «Термопаста» ────────────────────────────────────────────────────────

def _build_thermal(thermal_pastes: List[Dict]) -> List:
    if not thermal_pastes:
        return []
    elems = []
    elems.append(_sp(5))
    elems.append(Paragraph("Рекомендованные термопасты", S["h2"]))

    col_w = [(W - 30*mm) * x for x in (0.25, 0.15, 0.2, 0.4)]
    header = [Paragraph(h, S["tbl_hdr"]) for h in
              ["Марка", "Теплопров., Вт/(м·К)", "Макс. TDP", "Описание"]]
    rows = [header]
    for p in thermal_pastes:
        rows.append([
            Paragraph(f'<b>{p.get("brand", "")}</b>', S["tbl_cell"]),
            Paragraph(str(p.get("conductivity", "—")), S["tbl_mono"]),
            Paragraph(
                "Без огр." if p.get("max_tdp", 0) >= 999
                else f'до {p.get("max_tdp")} Вт', S["small"]),
            Paragraph(p.get("description", ""), S["small"]),
        ])
    tbl = Table(rows, colWidths=col_w, repeatRows=1)
    tbl.setStyle(_tbl_style())
    elems.append(tbl)
    return elems


# ── Главная функция ────────────────────────────────────────────────────────────

def generate_maintenance_pdf(
    tasks: List[Dict[str, Any]],
    intensity: str,
    cpu_name: str = "",
    gpu_name: str = "",
    thermal_pastes: List[Dict[str, Any]] = None,
) -> bytes:
    """
    Генерирует PDF-регламент ТО и возвращает bytes.

    tasks: список задач, каждая:
        {
          "title": str,
          "applicability": str,
          "interval": str,         # уже посчитанный интервал
          "base_interval": str,
          "high_interval": str,
          "tools": List[str],
          "safety": List[str],
          "steps": List[str],
          "success": str,
          "utility": str,          # опционально
        }
    intensity: "light" | "medium" | "high"
    thermal_pastes: список паст (опционально, добавляется последней секцией)
    """
    buf = BytesIO()

    meta = {
        "cpu":  f"CPU: {cpu_name}" if cpu_name else "",
        "gpu":  f"GPU: {gpu_name}" if gpu_name else "",
        "date": datetime.datetime.now().strftime("%d.%m.%Y"),
    }

    doc = BaseDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=15*mm, rightMargin=15*mm,
        topMargin=32*mm,  bottomMargin=20*mm,
        title="Регламент ТО — TECHFORGE",
        author="TECHFORGE",
    )
    doc.addPageTemplates([_TechForgePage(doc, meta)])

    story = []

    # ── Обложка-введение ──────────────────────────────────────────────────────
    story.append(_sp(4))
    # Мета-блок конфигурации
    meta_rows = []
    if cpu_name:
        meta_rows.append([Paragraph("Процессор (CPU)", S["meta_key"]),
                          Paragraph(cpu_name, S["meta_val"])])
    if gpu_name:
        meta_rows.append([Paragraph("Видеокарта (GPU)", S["meta_key"]),
                          Paragraph(gpu_name, S["meta_val"])])
    label_map = {"light": "Лёгкая (офис)", "medium": "Средняя (повседневная)", "high": "Высокая (игры/рендер)"}
    meta_rows.append([Paragraph("Профиль нагрузки", S["meta_key"]),
                      Paragraph(label_map.get(intensity, intensity), S["meta_val"])])
    meta_rows.append([Paragraph("Дата генерации", S["meta_key"]),
                      Paragraph(meta["date"], S["meta_val"])])
    meta_rows.append([Paragraph("Видов работ", S["meta_key"]),
                      Paragraph(str(len(tasks)), S["meta_val"])])

    mw = W - 30*mm
    meta_tbl = Table(meta_rows, colWidths=[mw * 0.35, mw * 0.65])
    meta_tbl.setStyle(TableStyle([
        ("ROWBACKGROUNDS", (0, 0), (-1, -1), [C_WHITE, C_STRIPE]),
        ("GRID",   (0, 0), (-1, -1), 0.3, C_RULE),
        ("TOPPADDING",    (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
        ("FONTNAME",      (0, 0), (0, -1),  "DV"),
        ("FONTNAME",      (1, 0), (1, -1),  "DV-Bold"),
        ("LINEAFTER",     (0, 0), (0, -1),  0.5, C_RULE),
    ]))
    story.append(meta_tbl)

    # ── Регламент + инструкции ────────────────────────────────────────────────
    story.extend(_build_schedule(tasks, intensity))
    story.extend(_build_instructions(tasks))

    # ── Термопасты ────────────────────────────────────────────────────────────
    if thermal_pastes:
        story.extend(_build_thermal(thermal_pastes))

    doc.build(story)
    return buf.getvalue()
