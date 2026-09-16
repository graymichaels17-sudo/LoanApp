"""
Shared PDF export helper. Used by DataTable.export_pdf() (widgets.py) so every
table in the app - Reports, Loan Statement, Amortisation Schedule, Clients,
Loans, Loan History, etc. - can be saved as a PDF, not just CSV.

Requires the 'reportlab' package:  pip install reportlab
"""
import re
from datetime import datetime
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer

from .. import config

def _parse_money(val):
    """Safely extract a float value from formatted money strings."""
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        # Remove currency symbols, commas, and spaces
        cleaned = re.sub(r'[^\d\.-]', '', val)
        if cleaned and cleaned not in ('.', '-'):
            try:
                return float(cleaned)
            except ValueError:
                pass
    return None

def export_table_pdf(filepath, title, columns, rows, meta_lines=None, show_summary=False):
    """
    filepath: where to save the .pdf
    title: heading shown at the top of the document
    columns: list of (key, label) tuples, same shape DataTable uses
    rows: list of dicts, values looked up by key
    meta_lines: optional list of strings shown as a details block above the table.
    show_summary: if True, include the auto-generated "Summary Totals" block.
                  Defaults to False - only pass True for tables in the Reports
                  module. Everywhere else (Loan Statement, Amortisation
                  Schedule, Clients, Loans, Loan History, etc.) totalling
                  columns like running balance or principal doesn't make
                  sense, so it must stay off unless explicitly requested.
    """
    # 1. Safe fetch dynamic company details
    company = {}
    try:
        from ..database import get_connection
        with get_connection() as conn:
            db_rows = conn.execute("SELECT key, value FROM company_details").fetchall()
            company = {r["key"]: r["value"] for r in db_rows}
    except Exception as e:
        print(f"Warning: Could not load company details for PDF export: {e}")
        # The export will safely continue using the fallbacks below
    
    comp_name = company.get("name") or getattr(config, "APP_NAME", "Company Name Not Set")
    comp_address = company.get("address", "")
    comp_contact = company.get("phone", "")
    comp_email = company.get("email", "")

    # 2. Setup Document Layout
    # Auto-landscape for wide tables, portrait for smaller ones
    page_size = landscape(letter) if len(columns) > 6 else letter
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(filepath, pagesize=page_size, topMargin=36, bottomMargin=36,
                             leftMargin=36, rightMargin=36)
    story = []

    # 3. Dynamic Company Header Formatting
    company_style = ParagraphStyle("company", parent=styles["Title"], alignment=TA_CENTER)
    contact_style = ParagraphStyle("contact", parent=styles["Normal"], alignment=TA_CENTER, textColor=colors.HexColor("#546E7A"))
    title_style = ParagraphStyle("DocTitle", parent=styles["Heading2"], alignment=TA_CENTER)

    story.append(Paragraph(comp_name, company_style))
    contact_info = " | ".join(filter(None, [comp_address, comp_contact, comp_email]))
    if contact_info:
        story.append(Paragraph(contact_info, contact_style))
        
    story.append(Spacer(1, 15))

    story.append(Paragraph(title, title_style))
    story.append(Paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}", styles["Normal"]))
    story.append(Spacer(1, 10))

    if meta_lines:
        for line in meta_lines:
            story.append(Paragraph(line, styles["Normal"]))
        story.append(Spacer(1, 14))

    # Calculate the exact printable width
    available_width = page_size[0] - 72
    col_width = available_width / max(len(columns), 1)

    cell_style = ParagraphStyle('CellStyle', parent=styles['Normal'], fontSize=8, leading=10)
    bold_cell_style = ParagraphStyle('BoldCell', parent=cell_style, fontName='Helvetica-Bold')
    header_style = ParagraphStyle('HeaderStyle', parent=styles['Normal'], fontSize=8, leading=10, textColor=colors.white, fontName='Helvetica-Bold')

    # Wrap every cell in a Paragraph
    header_row = [Paragraph(label, header_style) for _, label in columns]
    data = [header_row]
    for r in rows:
        data.append([Paragraph(str(r.get(key, "")), cell_style) for key, _ in columns])

    if len(data) == 1:
        story.append(Paragraph("No data.", styles["Normal"]))
    else:
        if show_summary:
            # 1. IDENTIFY SUMMABLE COLUMNS
            # Prevent summing of IDs, phone numbers, or dates that accidentally parse as floats
            exclude_keys = {'id', 'loan_no', 'client_no', 'employee_no', 'phone', 'contact', 'national_id', 'installment_no', 'aging_bucket', 'max_days_overdue', 'ageing_days', 'term_months'}
            sum_keywords = ['amount', 'principal', 'balance', 'interest', 'total', 'paye', 'levy', 'deduct', 'fee', 'dr', 'cr', 'charge', 'received']

            summable_keys = []
            for key, _ in columns:
                if key in exclude_keys:
                    continue
                # Automatically detect monetary/financial columns based on keywords
                if any(k in key.lower() for k in sum_keywords):
                    summable_keys.append(key)
        else:
            summable_keys = []

        # 2. GENERATE SUMMARY TOTALS AT THE TOP (IF APPLICABLE)
        if summable_keys:
            story.append(Paragraph("Summary Totals", styles["Heading3"]))
            story.append(Spacer(1, 5))
            
            has_location = any(k == "location" for k, _ in columns)
            currency = getattr(config, 'CURRENCY_SYMBOL', '$')
            
            if has_location:
                # Group totals by Location
                loc_totals = {}
                for r in rows:
                    loc = r.get("location") or "Unknown"
                    if loc not in loc_totals:
                        loc_totals[loc] = {k: 0.0 for k in summable_keys}
                    for k in summable_keys:
                        loc_totals[loc][k] += _parse_money(r.get(k)) or 0.0
                
                # Calculate Grand Totals
                grand_totals = {k: sum(loc_totals[loc][k] for loc in loc_totals) for k in summable_keys}
                
                # Build Summary Table
                summary_data = []
                summ_headers = ["Location"] + [label for k, label in columns if k in summable_keys]
                summary_data.append([Paragraph(h, header_style) for h in summ_headers])
                
                # Per Location Rows
                for loc in sorted(loc_totals.keys()):
                    row_data = [Paragraph(loc, cell_style)]
                    for k in summable_keys:
                        row_data.append(Paragraph(f"{currency}{loc_totals[loc][k]:,.2f}", cell_style))
                    summary_data.append(row_data)
                
                # Grand Total Row
                grand_row = [Paragraph("GRAND TOTAL", bold_cell_style)]
                for k in summable_keys:
                    grand_row.append(Paragraph(f"{currency}{grand_totals[k]:,.2f}", bold_cell_style))
                summary_data.append(grand_row)
                
                # Format Summary Table
                summ_col_width = available_width / max(len(summ_headers), 1)
                summ_table = Table(summary_data, colWidths=[summ_col_width] * len(summ_headers), repeatRows=1)
                summ_table.setStyle(TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E3A5F")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#D3D3D3")), # Highlight Grand Total Row
                ]))
                story.append(summ_table)
                
            else:
                # No Location Column Found - Generate Flat Grand Totals
                grand_totals = {k: 0.0 for k in summable_keys}
                for r in rows:
                    for k in summable_keys:
                        grand_totals[k] += _parse_money(r.get(k)) or 0.0
                        
                summary_data = []
                for k in summable_keys:
                    label = next((l for key, l in columns if key == k), k)
                    summary_data.append([
                        Paragraph(label, bold_cell_style),
                        Paragraph(f"{currency}{grand_totals[k]:,.2f}", cell_style)
                    ])
                    
                summ_table = Table(summary_data, colWidths=[available_width * 0.4, available_width * 0.6])
                summ_table.setStyle(TableStyle([
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                    ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F2F2F2")),
                ]))
                story.append(summ_table)

            # Add spacing between the summary and the main detailed table
            story.append(Spacer(1, 25))
            story.append(Paragraph("Detailed Records", styles["Heading3"]))
            story.append(Spacer(1, 5))

        # 3. GENERATE MAIN DETAILED TABLE
        table = Table(data, colWidths=[col_width] * len(columns), repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2D9CDB")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F2F2")]),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(table)

    doc.build(story)