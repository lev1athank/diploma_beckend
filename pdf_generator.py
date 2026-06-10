from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
)
import os
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# ── Переводы характеристик ──────────────────────────────────────────────────

COMPONENT_NAMES = {
    "cpu": "Процессор",
    "gpu": "Видеокарта",
    "motherboard": "Материнская плата",
    "mem": "Оперативная память",
}

# Только нужные поля + их русские названия, по типу компонента
SPEC_FIELDS: dict[str, list[tuple[str, str]]] = {
    "cpu": [
        ("clock_speed",       "Базовая частота"),
        ("turbo_speed",       "Турбо частота"),
        ("cores",             "Ядра"),
        ("threads",           "Потоки"),
        ("socket",            "Сокет"),
        ("tdp",               "TDP"),
        ("memory_type",       "Тип памяти"),
        ("max_memory",        "Макс. объём памяти"),
        ("l3_cache",          "Кэш L3"),
    ],
    "gpu": [
        ("core_clock",        "Базовая частота"),
        ("boost_clock",       "Буст частота"),
        ("memory_type",       "Тип памяти"),
        ("memory_size",       "Объём памяти"),
        ("tdp",               "TDP"),
        ("floating_point_performance", "Производительность"),
        ("directx_support",   "DirectX"),
        ("pcie_revision",     "PCIe версия"),
    ],
    "motherboard": [
        ("socket",            "Сокет"),
        ("form_factor",       "Форм-фактор"),
        ("max_memory",        "Макс. объём памяти"),
        ("memory_slots",      "Слоты памяти"),
        ("color",             "Цвет"),
    ],
    "mem": [
        ("modules",           "Модули"),
        ("speed",             "Частота"),
        ("cas_latency",       "CAS Latency"),
        ("first_word_latency","Задержка (нс)"),
        ("color",             "Цвет"),
    ],
}


def _fmt_value(key: str, value) -> str:
    """Приводим значения к читаемому виду."""
    if value is None:
        return "—"
    if key == "modules" and isinstance(value, list) and len(value) == 2:
        return f"{value[0]} × {value[1]} ГБ"
    if key == "speed" and isinstance(value, list) and len(value) == 2:
        return f"DDR{value[0]}-{value[1]}"
    if key == "price" or key == "price_per_gb":
        return f"${float(value):.2f}"
    if key == "max_memory" and isinstance(value, (int, float)):
        return f"{int(value)} ГБ"
    return str(value)


def generate_config_pdf(components: list) -> bytes:
    """
    Принимает список ComponentPDF и возвращает PDF в байтах.
    Регистрирует кириллический шрифт — положи DejaVuSans.ttf рядом
    или укажи абсолютный путь.
    """
    # Кириллический шрифт (положи файл шрифта в папку проекта)

    FONT_DIR = os.path.join(os.path.dirname(__file__), "fonts")
    pdfmetrics.registerFont(TTFont("DejaVu",      f"{FONT_DIR}/GoogleSans-Regular.ttf"))
    pdfmetrics.registerFont(TTFont("DejaVu-Bold", f"{FONT_DIR}/GoogleSans-Bold.ttf"))
    pdfmetrics.registerFont(TTFont("DV-Mono", f"{FONT_DIR}/Roboto-Regular.ttf"))  # моно = Roboto
    pdfmetrics.registerFontFamily("DV", normal="DV", bold="DV-Bold")
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "DocTitle",
        fontName="DejaVu-Bold",
        fontSize=16,
        spaceAfter=6,
        textColor=colors.HexColor("#1a1a2e"),
    )
    section_style = ParagraphStyle(
        "SectionHeader",
        fontName="DejaVu-Bold",
        fontSize=12,
        spaceBefore=10,
        spaceAfter=4,
        textColor=colors.HexColor("#16213e"),
    )
    cell_style = ParagraphStyle(
        "Cell",
        fontName="DejaVu",
        fontSize=9,
    )

    story = []

    # Заголовок документа
    story.append(Paragraph("Конфигурация ПК", title_style))
    story.append(HRFlowable(width="100%", thickness=1.5,
                            color=colors.HexColor("#0f3460"), spaceAfter=10))

    for comp in components:
        comp_type = comp.type
        label = COMPONENT_NAMES.get(comp_type, comp_type.upper())

        # Заголовок секции
        story.append(Paragraph(f"{label}: {comp.name}", section_style))

        fields = SPEC_FIELDS.get(comp_type, [])
        if not fields:
            story.append(Paragraph("Нет данных", cell_style))
            story.append(Spacer(1, 6))
            continue

        table_data = []
        for key, ru_label in fields:
            raw = comp.specifications.get(key)
            if raw is None:
                continue
            table_data.append([
                Paragraph(ru_label, cell_style),
                Paragraph(_fmt_value(key, raw), cell_style),
            ])

        if table_data:
            col_widths = [80 * mm, 80 * mm]
            tbl = Table(table_data, colWidths=col_widths, hAlign="LEFT")
            tbl.setStyle(TableStyle([
                # чётные/нечётные строки
                ("ROWBACKGROUNDS", (0, 0), (-1, -1),
                 [colors.HexColor("#f5f5f5"), colors.white]),
                ("GRID",        (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
                ("FONTNAME",    (0, 0), (-1, -1), "DejaVu"),
                ("FONTSIZE",    (0, 0), (-1, -1), 9),
                ("TOPPADDING",  (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING",(0, 0), (-1, -1), 6),
            ]))
            story.append(tbl)

        story.append(Spacer(1, 8))

    doc.build(story)
    buf.seek(0)
    return buf.read()