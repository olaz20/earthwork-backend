"""Pure report renderers: ReportContext -> bytes. No database, no FastAPI."""
from __future__ import annotations

import io
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Sequence
from xml.sax.saxutils import escape

from app.schemas.progress import ProgressPoint

_UNIT_SYMBOLS = {
    "metre": "m", "meter": "m", "metres": "m", "meters": "m", "m": "m",
    "foot": "ft", "feet": "ft", "ft": "ft",
    "us_survey_foot": "ft (US)", "us_foot": "ft (US)",
}

_DIAGNOSTIC_LABELS = [
    ("initial_points_used", "Initial survey points used", "int"),
    ("progress_points_used", "Progress survey points used", "int"),
    ("duplicate_points_merged", "Duplicate points merged", "int"),
    ("survey_point_spacing", "Typical point spacing", "len"),
    ("max_fill_depth", "Maximum fill depth", "len"),
    ("max_cut_depth", "Maximum cut depth", "len"),
    ("cut_area", "Area in cut", "area"),
    ("extrapolated_area_fraction", "Site area extrapolated beyond survey", "pct"),
    ("extrapolated_vertex_fraction", "Mesh vertices extrapolated beyond survey", "pct"),
    ("max_extrapolation_distance", "Maximum extrapolation distance", "len"),
]

_METHOD_NOTES = {
    "grid": "Regular grid. Cells crossing a boundary are clipped exactly to the polygon and weighted by the clipped area.",
    "tin": "Both surfaces are evaluated on one common triangulation; triangles are split along the "
    "zero-change line and integrated exactly.",
}


@dataclass(frozen=True)
class InputRow:
    role: str
    ref: str  # e.g. "#12"
    date: date | None
    detail: str


@dataclass(frozen=True)
class ReportContext:
    title: str
    project_name: str
    project_description: str | None
    crs: str | None
    length_unit: str
    computation_id: int
    method: str | None
    computed_at: datetime | None
    generated_at: datetime
    site_area: float
    fill_area: float
    fill_volume: float
    cut_volume: float
    inputs: Sequence[InputRow]
    settings: dict
    diagnostics: dict
    history: Sequence[ProgressPoint] = field(default_factory=tuple)

    @property
    def warnings(self) -> list[str]:
        return list(self.diagnostics.get("warnings", []))

    @property
    def net_volume(self) -> float:
        return self.fill_volume - self.cut_volume

    @property
    def percent_area(self) -> float | None:
        return round(min(max(self.fill_area / self.site_area * 100, 0), 100), 2) if self.site_area > 0 else None

    @property
    def sym(self) -> str:
        return _UNIT_SYMBOLS.get(self.length_unit.lower(), self.length_unit)


def _rich(text: str) -> str:
    """Escape for reportlab Paragraph and turn unit superscripts into markup
    (the built-in PDF fonts silently drop the characters 2 and 3 in superscript form)."""
    return escape(text).replace("\u00b2", "<super>2</super>").replace("\u00b3", "<super>3</super>")


def _n(v: float | None, d: int = 2) -> str:
    return "-" if v is None else f"{v:,.{d}f}"


def _diag_rows(ctx: ReportContext) -> list[tuple[str, str]]:
    rows = []
    for key, label, kind in _DIAGNOSTIC_LABELS:
        if key not in ctx.diagnostics or ctx.diagnostics[key] is None:
            continue
        v = ctx.diagnostics[key]
        text = {
            "int": f"{int(v):,}",
            "len": f"{_n(v)} {ctx.sym}",
            "area": f"{_n(v)} {ctx.sym}²",
            "pct": f"{v * 100:.1f}%",
        }[kind]
        rows.append((label, text))
    return rows


def _setting_rows(ctx: ReportContext) -> list[tuple[str, str]]:
    rows = []
    for k, v in ctx.settings.items():
        text = "auto / none" if v is None else (f"{v:,.4g}" if isinstance(v, float) else str(v))
        rows.append((k.replace("_", " ").capitalize(), text))
    return rows


# ------------------------------------------------------------------------------- PDF
def render_pdf(ctx: ReportContext) -> bytes:
    from reportlab.graphics.charts.barcharts import VerticalBarChart
    from reportlab.graphics.shapes import Drawing
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    accent = colors.HexColor("#1F4E79")
    ss = getSampleStyleSheet()
    ss.add(ParagraphStyle("Cell", parent=ss["BodyText"], fontSize=8.5, leading=10.5))
    ss.add(ParagraphStyle("CellB", parent=ss["Cell"], fontName="Helvetica-Bold", textColor=colors.white))
    ss.add(ParagraphStyle("CellR", parent=ss["Cell"], alignment=TA_RIGHT))
    ss.add(ParagraphStyle("CellRB", parent=ss["CellB"], alignment=TA_RIGHT))
    ss.add(ParagraphStyle("Sec", parent=ss["Heading2"], textColor=accent, spaceBefore=12, spaceAfter=4))
    ss.add(ParagraphStyle("Small", parent=ss["BodyText"], fontSize=8, leading=10, textColor=colors.grey))
    ss.add(ParagraphStyle("Warn", parent=ss["BodyText"], fontSize=9, textColor=colors.HexColor("#9C5700")))

    def table(rows, widths, right=(), zebra=True):
        data = []
        for r, row in enumerate(rows):
            data.append([
                Paragraph(_rich(str(c)), ss[("CellRB" if c_i in right else "CellB") if r == 0 else ("CellR" if c_i in right else "Cell")])
                for c_i, c in enumerate(row)
            ])
        t = Table(data, colWidths=widths, repeatRows=1)
        style = [
            ("BACKGROUND", (0, 0), (-1, 0), accent),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#D0D7DE")),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]
        if zebra:
            style += [("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5F8FB")])]
        t.setStyle(TableStyle(style))
        return t

    def chart():
        vals = [ctx.fill_volume, ctx.cut_volume, ctx.net_volume]
        d = Drawing(440, 170)
        bc = VerticalBarChart()
        bc.x, bc.y, bc.width, bc.height = 55, 30, 340, 115
        bc.data = [vals]
        bc.categoryAxis.categoryNames = ["Fill", "Cut", "Net (fill - cut)"]
        bc.categoryAxis.labelAxisMode = "low"
        hi, lo = max(vals + [0]), min(vals + [0])
        pad = (hi - lo) * 0.18 or 1.0
        bc.valueAxis.valueMax = hi + pad
        bc.valueAxis.valueMin = lo - pad if lo < 0 else 0
        bc.valueAxis.labels.fontSize = 7
        bc.categoryAxis.labels.fontSize = 8
        bc.barLabelFormat = "%0.1f"
        bc.barLabels.nudge = 7
        bc.barLabels.fontSize = 7
        bc.barWidth = 40
        for i, col in enumerate(["#2E8B57", "#C0392B", "#1F4E79"]):
            bc.bars[(0, i)].fillColor = colors.HexColor(col)
        d.add(bc)
        return d

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.grey)
        canvas.drawString(18 * mm, 10 * mm, f"{ctx.project_name} - computation #{ctx.computation_id}")
        canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Generated {ctx.generated_at:%Y-%m-%d %H:%M UTC} - page {doc.page}")
        canvas.restoreState()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm,
        bottomMargin=18 * mm, title=ctx.title, author="Earthwork API",
    )
    W = A4[0] - 36 * mm
    sym = ctx.sym
    story = [Paragraph(escape(ctx.title), ss["Title"])]

    meta = [("Project", ctx.project_name), ("Computation", f"#{ctx.computation_id} ({ctx.method or 'n/a'} method)"),
            ("Coordinate system", ctx.crs or "not set"), ("Length unit", ctx.length_unit),
            ("Computed", f"{ctx.computed_at:%Y-%m-%d %H:%M UTC}" if ctx.computed_at else "-")]
    if ctx.project_description:
        meta.insert(1, ("Description", ctx.project_description))
    story.append(
        Table(
            [[Paragraph(f"<b>{escape(k)}</b>", ss["Cell"]), Paragraph(escape(v), ss["Cell"])] for k, v in meta],
            colWidths=[40 * mm, W - 40 * mm],
        )
    )

    story += [Paragraph("Results", ss["Sec"])]
    res = [("Metric", "Value", "Unit"),
           ("Site area", _n(ctx.site_area), f"{sym}²"),
           ("Fill area", _n(ctx.fill_area), f"{sym}²"),
           ("Fill volume", _n(ctx.fill_volume), f"{sym}³"),
           ("Cut volume", _n(ctx.cut_volume), f"{sym}³"),
           ("Net volume (fill - cut)", _n(ctx.net_volume), f"{sym}³")]
    if ctx.percent_area is not None:
        res.append(("Complete by area (fill area / site area)", f"{ctx.percent_area:.1f}", "%"))
    story += [table(res, [W * 0.55, W * 0.25, W * 0.20], right={1}), Spacer(1, 6), chart()]
    story.append(Paragraph("Sign convention: change = progress surface - initial surface. Positive is fill, negative is cut.", ss["Small"]))

    if ctx.warnings:
        story.append(Paragraph("Warnings", ss["Sec"]))
        story += [Paragraph("- " + escape(w), ss["Warn"]) for w in ctx.warnings]

    story.append(Paragraph("Inputs", ss["Sec"]))
    rows = [("Input", "ID", "Date", "Details")] + [
        (i.role, i.ref, i.date.isoformat() if i.date else "-", i.detail) for i in ctx.inputs
    ]
    story.append(table(rows, [W * 0.22, W * 0.10, W * 0.16, W * 0.52]))

    story.append(Paragraph("Method and parameters", ss["Sec"]))
    if ctx.method in _METHOD_NOTES:
        story.append(Paragraph(escape(_METHOD_NOTES[ctx.method]), ss["BodyText"]))
    story.append(table([("Parameter", "Value")] + _setting_rows(ctx), [W * 0.5, W * 0.5]))

    drows = _diag_rows(ctx)
    if drows:
        story.append(Paragraph("Data quality", ss["Sec"]))
        story.append(table([("Check", "Value")] + drows, [W * 0.6, W * 0.4], right={1}))

    if len(ctx.history) > 1:
        story.append(Paragraph("Progress history", ss["Sec"]))
        hist = [("Survey date", "Fill volume", "Cut volume", "Fill area", "% by area")] + [
            (p.date.isoformat(), _n(p.fill_volume), _n(p.cut_volume), _n(p.fill_area), f"{p.percent_complete_area:.1f}")
            for p in ctx.history
        ]
        story.append(table(hist, [W * 0.2] + [W * 0.2] * 4, right={1, 2, 3, 4}))
        story.append(Paragraph(_rich(f"Volumes in {sym}³, areas in {sym}². Same computation method, up to this survey."), ss["Small"]))

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()


# ------------------------------------------------------------------------------ XLSX
def render_xlsx(ctx: ReportContext) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    head_fill = PatternFill("solid", fgColor="1F4E79")
    sym = ctx.sym

    def sheet(ws, rows, header_row=1, number_cols=()):
        for r in rows:
            ws.append(list(r))
        for c in ws[header_row]:
            c.font, c.fill = Font(bold=True, color="FFFFFF"), head_fill
        for col in number_cols:
            for c in ws[get_column_letter(col)][header_row:]:
                c.number_format = "#,##0.00"
                c.alignment = Alignment(horizontal="right")
        for i, col in enumerate(ws.columns, 1):
            ws.column_dimensions[get_column_letter(i)].width = min(60, max(12, max(len(str(c.value or "")) for c in col) + 2))

    ws = wb.active
    ws.title = "Summary"
    rows = [("Metric", "Value", "Unit"),
            ("Site area", ctx.site_area, f"{sym}²"), ("Fill area", ctx.fill_area, f"{sym}²"),
            ("Fill volume", ctx.fill_volume, f"{sym}³"), ("Cut volume", ctx.cut_volume, f"{sym}³"),
            ("Net volume (fill - cut)", ctx.net_volume, f"{sym}³")]
    if ctx.percent_area is not None:
        rows.append(("Complete by area", ctx.percent_area, "%"))
    sheet(ws, rows, number_cols=(2,))
    ws.append([])
    for k, v in [("Project", ctx.project_name), ("Report", ctx.title), ("Computation", f"#{ctx.computation_id}"),
                 ("Method", ctx.method or "-"), ("CRS", ctx.crs or "not set"), ("Length unit", ctx.length_unit),
                 ("Generated", f"{ctx.generated_at:%Y-%m-%d %H:%M UTC}")]:
        ws.append([k, v])
    for w in ctx.warnings:
        ws.append(["Warning", w])

    sheet(wb.create_sheet("Inputs"), [("Input", "ID", "Date", "Details")] +
          [(i.role, i.ref, i.date.isoformat() if i.date else "-", i.detail) for i in ctx.inputs])
    sheet(wb.create_sheet("Parameters"), [("Parameter", "Value")] + _setting_rows(ctx))
    drows = _diag_rows(ctx)
    if drows:
        sheet(wb.create_sheet("Data quality"), [("Check", "Value")] + drows)
    if ctx.history:
        sheet(wb.create_sheet("Progress"),
              [("Survey date", f"Fill volume ({sym}³)", f"Cut volume ({sym}³)", f"Fill area ({sym}²)", "% by area")] +
              [(p.date, p.fill_volume, p.cut_volume, p.fill_area, p.percent_complete_area) for p in ctx.history],
              number_cols=(2, 3, 4, 5))

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


RENDERERS = {"pdf": render_pdf, "xlsx": render_xlsx}
MEDIA_TYPES = {
    "pdf": "application/pdf",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}