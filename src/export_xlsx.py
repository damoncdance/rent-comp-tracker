"""Export the latest snapshot to an Excel workbook matching the Bond comp-report format.

Output: data/exports/<slug>_Availability.xlsx
Three sheets: Availability Matrix, Tier Summary, Raw Data.

Uses openpyxl. Called from daily_run after a successful snapshot.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill, numbers
from openpyxl.utils import get_column_letter

from src.config import DATA_DIR, PROPERTY_NAME, PROPERTY_URL
from src.storage import db, latest_snapshot_id


# --- Styles ------------------------------------------------------------------

_HEADER_FILL = PatternFill(start_color="FF1F4E78", end_color="FF1F4E78", fill_type="solid")
_HEADER_FONT = Font(bold=True, size=11, color="FFFFFFFF")
_TITLE_FONT  = Font(bold=True, size=16)
_SUB_FONT    = Font(size=11, color="FF5C5C5C")
_SECTION_FONT = Font(bold=True, size=11)
_DATE_FMT    = 'mmm d, yyyy'
_MONEY_FMT   = '$#,##0'
_NUM_FMT     = '#,##0'
_PSF_FMT     = '$#,##0.00'

EXPORTS_DIR = DATA_DIR / "exports"


def report_workbook_path() -> Path:
    """Path where the latest availability workbook is written (per PROPERTY_NAME)."""
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    slug = _slugify(PROPERTY_NAME)
    return EXPORTS_DIR / f"{slug}_Availability.xlsx"


def _bed_label(beds: int) -> str:
    if beds == 0:
        return "Studio"
    return f"{beds} Bedroom"


def _slugify(name: str) -> str:
    return name.replace(" ", "_").replace("—", "-")


def _apply_header_row(ws, row: int, values: list[str]) -> None:
    for col, val in enumerate(values, 1):
        cell = ws.cell(row=row, column=col, value=val)
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center")


def _auto_width(ws, min_width: float = 8.0) -> None:
    """Set column widths based on content, with reasonable overrides."""
    for col in ws.columns:
        max_len = min_width
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            if cell.value is not None:
                max_len = max(max_len, len(str(cell.value)) + 2)
        ws.column_dimensions[col_letter].width = min(max_len, 35)


# --- Public API --------------------------------------------------------------

def export(snapshot_id: int | None = None) -> str | None:
    """Build the xlsx from a snapshot. Returns the output path, or None if no data."""
    if snapshot_id is None:
        snapshot_id = latest_snapshot_id()
    if snapshot_id is None:
        return None

    with db() as conn:
        snap = conn.execute(
            "SELECT * FROM snapshots WHERE id = ?", (snapshot_id,)
        ).fetchone()
        if snap is None or snap["fetch_status"] != "success":
            return None

        units = [dict(r) for r in conn.execute(
            "SELECT * FROM units WHERE snapshot_id = ? "
            "ORDER BY beds, floorplan_name, unit_code",
            (snapshot_id,),
        ).fetchall()]

        floorplans = [dict(r) for r in conn.execute(
            "SELECT * FROM floorplans WHERE snapshot_id = ? "
            "ORDER BY beds, name",
            (snapshot_id,),
        ).fetchall()]

    if not units:
        return None

    snap = dict(snap)
    snap_date = datetime.fromisoformat(
        snap["fetched_at"].replace("Z", "+00:00")
    )
    snap_date_str = snap_date.strftime("%b %d, %Y")
    unit_count = snap["unit_count"]

    wb = Workbook()

    # ── Sheet 1: Availability Matrix ──────────────────────────────────────
    ws1 = wb.active
    ws1.title = "Availability Matrix"

    # Title row
    ws1.merge_cells("A1:G1")
    c = ws1["A1"]
    c.value = f"{PROPERTY_NAME} — Availability Matrix"
    c.font = _TITLE_FONT

    # Subtitle row
    domain = PROPERTY_URL.split("//")[-1].split("/")[0].replace("www.", "")
    ws1.merge_cells("A2:F2")
    c = ws1["A2"]
    c.value = f"Source: {domain}/floorplans  |  Snapshot: {snap_date_str}  |  Total available units: {unit_count}"
    c.font = _SUB_FONT

    # Header row (row 4)
    headers = ["Unit Type", "Floorplan / Tier", "Unit Number",
               "Beds / Baths", "Sq Ft", "Rent", "Available Date"]
    _apply_header_row(ws1, 4, headers)

    # Group units by bed type
    by_bed: dict[int, list[dict]] = defaultdict(list)
    for u in units:
        by_bed[u["beds"]].append(u)

    row = 5
    for beds in sorted(by_bed.keys()):
        bed_units = by_bed[beds]
        label = _bed_label(beds)
        count = len(bed_units)

        # Section header (merged row)
        ws1.merge_cells(f"A{row}:G{row}")
        c = ws1.cell(row=row, column=1, value=f"{label}  ({count} available)")
        c.font = _SECTION_FONT
        row += 1

        for u in bed_units:
            ws1.cell(row=row, column=1, value=label)
            ws1.cell(row=row, column=2, value=u["floorplan_name"])
            ws1.cell(row=row, column=3, value=u["unit_code"])
            ws1.cell(row=row, column=4, value=f"{u['beds']} / {int(u['baths'])}")
            c = ws1.cell(row=row, column=5, value=int(u["sqft"]))
            c.number_format = _NUM_FMT
            c = ws1.cell(row=row, column=6, value=int(u["min_rent"]))
            c.number_format = _MONEY_FMT
            try:
                dt = datetime.fromisoformat(u["available_date"].replace("Z", "+00:00"))
                c = ws1.cell(row=row, column=7, value=dt.replace(tzinfo=None))
                c.number_format = _DATE_FMT
            except (ValueError, AttributeError):
                ws1.cell(row=row, column=7, value=u.get("available_date", ""))
            row += 1

    # Column widths
    ws1.column_dimensions["A"].width = 18
    ws1.column_dimensions["B"].width = 30
    ws1.column_dimensions["C"].width = 14
    ws1.column_dimensions["D"].width = 12
    ws1.column_dimensions["E"].width = 10
    ws1.column_dimensions["F"].width = 12
    ws1.column_dimensions["G"].width = 16

    # ── Sheet 2: Tier Summary ────────────────────────────────────────────
    ws2 = wb.create_sheet("Tier Summary")

    ws2.merge_cells("A1:H1")
    c = ws2["A1"]
    c.value = "Floor Plan Tier Summary"
    c.font = _TITLE_FONT

    ws2.merge_cells("A2:H2")
    c = ws2["A2"]
    c.value = (f"{len(floorplans)} floor plan types  |  "
               f"{unit_count} available units  |  Snapshot: {snap_date_str}")
    c.font = _SUB_FONT

    headers2 = ["Tier / Floorplan", "Type", "Beds", "Baths",
                "Sq Ft", "Rent Range", "# Available", "Earliest Move-In"]
    _apply_header_row(ws2, 4, headers2)

    row = 5
    for fp in floorplans:
        label = _bed_label(fp["beds"])
        ws2.cell(row=row, column=1, value=fp["name"])
        ws2.cell(row=row, column=2, value=label)
        ws2.cell(row=row, column=3, value=fp["beds"])
        ws2.cell(row=row, column=4, value=int(fp["baths"]))
        c = ws2.cell(row=row, column=5, value=int(fp["min_sqft"]))
        c.number_format = _NUM_FMT

        # Rent range as formatted string (matches reference)
        mn, mx = int(fp["min_rent"]), int(fp["max_rent"])
        rent_str = f"${mn:,}" if mn == mx else f"${mn:,} – ${mx:,}"
        ws2.cell(row=row, column=6, value=rent_str)

        ws2.cell(row=row, column=7, value=fp["available_count"])

        try:
            dt = datetime.fromisoformat(fp["available_date"].replace("Z", "+00:00"))
            c = ws2.cell(row=row, column=8, value=dt.replace(tzinfo=None))
            c.number_format = _DATE_FMT
        except (ValueError, AttributeError, TypeError):
            ws2.cell(row=row, column=8, value=fp.get("available_date", ""))
        row += 1

    # Totals row
    total_row = row
    ws2.cell(row=total_row, column=1, value="TOTAL")
    ws2.cell(row=total_row, column=7,
             value=f"=SUM(G5:G{total_row - 1})")

    ws2.column_dimensions["A"].width = 32
    ws2.column_dimensions["B"].width = 14
    ws2.column_dimensions["C"].width = 8
    ws2.column_dimensions["D"].width = 8
    ws2.column_dimensions["E"].width = 10
    ws2.column_dimensions["F"].width = 22
    ws2.column_dimensions["G"].width = 14
    ws2.column_dimensions["H"].width = 18

    # ── Sheet 3: Raw Data ────────────────────────────────────────────────
    ws3 = wb.create_sheet("Raw Data")

    raw_headers = ["Unit Code", "Floorplan", "Bed Type", "Beds", "Baths",
                   "Sq Ft", "Min Rent", "Max Rent", "Available Date", "Rent / Sq Ft"]
    _apply_header_row(ws3, 1, raw_headers)

    for i, u in enumerate(units, 2):
        ws3.cell(row=i, column=1, value=u["unit_code"])
        ws3.cell(row=i, column=2, value=u["floorplan_name"])
        ws3.cell(row=i, column=3, value=_bed_label(u["beds"]))
        ws3.cell(row=i, column=4, value=u["beds"])
        ws3.cell(row=i, column=5, value=int(u["baths"]))
        c = ws3.cell(row=i, column=6, value=int(u["sqft"]))
        c.number_format = _NUM_FMT
        c = ws3.cell(row=i, column=7, value=int(u["min_rent"]))
        c.number_format = _MONEY_FMT
        c = ws3.cell(row=i, column=8, value=int(u["max_rent"]))
        c.number_format = _MONEY_FMT
        try:
            dt = datetime.fromisoformat(u["available_date"].replace("Z", "+00:00"))
            c = ws3.cell(row=i, column=9, value=dt.replace(tzinfo=None))
            c.number_format = _DATE_FMT
        except (ValueError, AttributeError):
            ws3.cell(row=i, column=9, value=u.get("available_date", ""))
        # Rent / Sq Ft formula
        c = ws3.cell(row=i, column=10, value=f"=G{i}/F{i}")
        c.number_format = _PSF_FMT

    ws3.column_dimensions["A"].width = 12
    ws3.column_dimensions["B"].width = 30
    ws3.column_dimensions["C"].width = 12
    ws3.column_dimensions["D"].width = 7
    ws3.column_dimensions["E"].width = 7
    ws3.column_dimensions["F"].width = 9
    ws3.column_dimensions["G"].width = 11
    ws3.column_dimensions["H"].width = 11
    ws3.column_dimensions["I"].width = 16
    ws3.column_dimensions["J"].width = 13

    # ── Save ─────────────────────────────────────────────────────────────
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    slug = _slugify(PROPERTY_NAME)
    out_path = EXPORTS_DIR / f"{slug}_Availability.xlsx"
    wb.save(str(out_path))
    return str(out_path)
