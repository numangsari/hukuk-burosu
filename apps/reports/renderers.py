"""Rapor çıktıları: Excel (openpyxl) ve PDF (ReportLab, gömülü DejaVu Sans)."""

import datetime as dt
import io
import re
from decimal import Decimal
from pathlib import Path

from django.utils import timezone

from .base import ReportResult, fmt

FONT_DIR = Path(__file__).resolve().parent / "fonts"
_fonts_registered = False


def to_xlsx(r: ReportResult, office_name: str) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active

    def write_cell(row, column, value=None):
        cell = ws.cell(row, column, value)
        if isinstance(value, str):
            cell.data_type = "s"
        return cell

    # Excel sayfa adı en çok 31 karakter olabilir ve []:*?/\ içeremez.
    ws.title = re.sub(r"[\[\]:*?/\\]", "-", r.title)[:31]
    navy = "0F1F38"
    ncol = len(r.columns)
    write_cell(1, 1, office_name).font = Font(bold=True, size=12, color=navy)
    write_cell(2, 1, r.title).font = Font(bold=True, size=14)
    write_cell(3, 1, r.subtitle).font = Font(italic=True, color="666666")
    write_cell(3, ncol, f"Oluşturma: {timezone.localtime():%d.%m.%Y %H:%M}").alignment = Alignment(
        horizontal="right"
    )
    row = 5
    for label, value in r.summary:
        write_cell(row, 1, label).font = Font(bold=True)
        write_cell(row, 2, value)
        row += 1
    if r.summary:
        row += 1
    header_row = row
    thin = Side(style="thin", color="D9DEE5")
    for i, c in enumerate(r.columns, start=1):
        cell = write_cell(header_row, i, c.label)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor=navy)
        cell.alignment = Alignment(
            horizontal="right" if c.kind in ("money", "int") else "left", vertical="center"
        )
        ws.column_dimensions[get_column_letter(i)].width = max(10, min(60, 14 * c.width))
    money_fmt = '#,##0.00 "₺";[Red]-#,##0.00 "₺"'
    for data in r.rows + ([r.totals] if r.totals else []):
        row += 1
        is_total = data is r.totals
        for i, (c, value) in enumerate(zip(r.columns, data, strict=False), start=1):
            if isinstance(value, Decimal):
                value = float(value)
            elif value is not None and not isinstance(value, (str, int, float, dt.date)):
                value = str(value)  # ör. kullanıcı nesnesi
            cell = write_cell(row, i, value if value not in (None, "") else None)
            cell.border = Border(bottom=thin)
            if c.kind == "money":
                cell.number_format = money_fmt
            elif c.kind == "date" and isinstance(value, dt.date):
                cell.number_format = "DD.MM.YYYY"
            if not is_total and (row - header_row) % 2 == 0:
                cell.fill = PatternFill("solid", fgColor="F5F7FA")
            if is_total:
                cell.font = Font(bold=True)
                cell.fill = PatternFill("solid", fgColor="EEF2F7")
            cell.alignment = Alignment(
                horizontal="right" if c.kind in ("money", "int") else "left",
                vertical="top",
                wrap_text=c.kind == "text",
            )
    ws.freeze_panes = ws.cell(header_row + 1, 1)
    ws.auto_filter.ref = f"A{header_row}:{get_column_letter(ncol)}{row}"
    ws.page_setup.orientation = "landscape" if r.landscape else "portrait"
    ws.page_setup.fitToWidth = 1
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _register_fonts():
    global _fonts_registered
    if _fonts_registered:
        return
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    pdfmetrics.registerFont(TTFont("DejaVu", FONT_DIR / "DejaVuSans.ttf"))
    pdfmetrics.registerFont(TTFont("DejaVu-Bold", FONT_DIR / "DejaVuSans-Bold.ttf"))
    pdfmetrics.registerFontFamily("DejaVu", normal="DejaVu", bold="DejaVu-Bold")
    _fonts_registered = True


def to_pdf(r: ReportResult, office_name: str, office_info: str = "") -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    _register_fonts()
    navy = colors.HexColor("#0F1F38")
    bronze = colors.HexColor("#B8925A")
    page = landscape(A4) if r.landscape else A4
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=page, leftMargin=14 * mm, rightMargin=14 * mm, topMargin=22 * mm,
        bottomMargin=16 * mm, title=r.title, author=office_name,
    )  # fmt: skip
    base = ParagraphStyle("b", fontName="DejaVu", fontSize=8, leading=10)
    right = ParagraphStyle("r", parent=base, alignment=2)
    head = ParagraphStyle("h", parent=base, fontName="DejaVu-Bold", textColor=colors.white)
    head_r = ParagraphStyle("hr", parent=head, alignment=2)
    title = ParagraphStyle("t", fontName="DejaVu-Bold", fontSize=15, leading=19, textColor=navy)
    sub = ParagraphStyle("s", parent=base, fontSize=9, textColor=colors.HexColor("#5A6578"))

    def esc(s):
        return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    story = [Paragraph(esc(r.title), title), Paragraph(esc(r.subtitle), sub), Spacer(1, 4 * mm)]
    if r.summary:
        st = Table(
            [[Paragraph(f"<b>{esc(k)}</b>", base), Paragraph(esc(v), base)] for k, v in r.summary],
            colWidths=[55 * mm, 70 * mm],
            hAlign="LEFT",
        )
        st.setStyle(TableStyle([("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
        story += [st, Spacer(1, 4 * mm)]

    avail = page[0] - doc.leftMargin - doc.rightMargin
    total_w = sum(c.width for c in r.columns)
    widths = [avail * c.width / total_w for c in r.columns]
    numeric = [c.kind in ("money", "int") for c in r.columns]
    data = [
        [
            Paragraph(esc(c.label), head_r if n else head)
            for c, n in zip(r.columns, numeric, strict=True)
        ]
    ]
    for row in r.rows:
        data.append(
            [
                Paragraph(esc(fmt(v, c.kind)), right if n else base)
                for v, c, n in zip(row, r.columns, numeric, strict=False)
            ]
        )
    if r.totals:
        data.append(
            [Paragraph(f"<b>{esc(fmt(v, c.kind)) if v not in (None, '') else ''}</b>", right if n else base)
             for v, c, n in zip(r.totals, r.columns, numeric, strict=False)]
        )  # fmt: skip
    if not r.rows:
        data.append([Paragraph("Kayıt yok.", base)] + [""] * (len(r.columns) - 1))
    table = Table(data, colWidths=widths, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), navy),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 1), (-1, -1), 0.25, colors.HexColor("#D9DEE5")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F6F8FB")]),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    if r.totals:
        style += [
            ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#EEF2F7")),
            ("LINEABOVE", (0, -1), (-1, -1), 0.8, navy),
        ]
    table.setStyle(TableStyle(style))
    story.append(table)

    stamp = f"{timezone.localtime():%d.%m.%Y %H:%M}"

    def decorate(canvas, d):
        canvas.saveState()
        w, h = page
        canvas.setFont("DejaVu-Bold", 10)
        canvas.setFillColor(navy)
        canvas.drawString(d.leftMargin, h - 12 * mm, office_name)
        canvas.setFont("DejaVu", 7.5)
        canvas.setFillColor(colors.HexColor("#5A6578"))
        if office_info:
            canvas.drawString(d.leftMargin, h - 16 * mm, office_info[:150])
        canvas.setStrokeColor(bronze)
        canvas.setLineWidth(0.8)
        canvas.line(d.leftMargin, h - 18 * mm, w - d.rightMargin, h - 18 * mm)
        canvas.drawString(d.leftMargin, 9 * mm, f"Oluşturma: {stamp}")
        canvas.drawRightString(w - d.rightMargin, 9 * mm, f"Sayfa {canvas.getPageNumber()}")
        canvas.restoreState()

    doc.build(story, onFirstPage=decorate, onLaterPages=decorate)
    return buf.getvalue()
