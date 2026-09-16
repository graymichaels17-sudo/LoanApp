"""
Payslip document rendering - an on-screen preview window styled like the
company's standard payslip template, plus a "Save as PDF" export that
matches it. Opened from the Payroll > Payslips table (row click or the
"View Payslip" button) in main_window.py.
"""
import customtkinter as ctk
from tkinter import filedialog

from .widgets import NAVY_BORDER, BLUE_ACCENT, BLUE_HOVER, info, error
from .. import config
from ..models import payroll as payroll_model
from ..money import fmt as _fmt_cents

# ---------------------------------------------------------------------
# Styling & Colors
# ---------------------------------------------------------------------
CURRENCY_LABEL = "Dollar"  # used in the "(All figures in ...)" footer line

INK = "#1A1A1A"          # near-black, for values/labels on the white "paper"
ACCENT_INK = "#8A5A2B"   # warm brown, matching the sample template's field labels
PAPER = "#FFFFFF"


def _money(v):
    """v is INTEGER CENTS (payslips.*, payslip_lines.amount, etc. are all
    stored as cents - see ../money.py). Formats as e.g. '1,234.56'."""
    try:
        return _fmt_cents(v)
    except (TypeError, ValueError):
        return str(v)


def get_company_details(conn) -> dict:
    """Helper to fetch dynamic company profile from SQLite."""
    try:
        rows = conn.execute("SELECT key, value FROM company_details").fetchall()
        return {r["key"]: r["value"] for r in rows}
    except Exception:
        return {}


def _payslip_context(conn, payslip, period):
    """Gathers everything the template needs: the full employee record
    (list_payslips only carries a few employee columns) plus the
    earnings/deductions line items."""
    employee = payroll_model.get_employee(conn, payslip["employee_id"])
    lines = payroll_model.get_payslip_lines(conn, payslip["id"])
    earnings = [l for l in lines if l["line_type"] == "Earning"]
    deductions = [l for l in lines if l["line_type"] == "Deduction"]
    return employee, earnings, deductions


# ---------------------------------------------------------------------
# On-screen preview
# ---------------------------------------------------------------------
def open_payslip_window(parent, conn, payslip, period):
    """
    parent: the window/frame to attach the popup to (pass `self` from a
        main_window.py method).
    payslip: one row from payroll_model.list_payslips(...).
    period: payroll_model.get_payroll_period(conn, payroll_period_id).
    """
    employee, earnings, deductions = _payslip_context(conn, payslip, period)
    company = get_company_details(conn)

    win = ctk.CTkToplevel(parent)
    win.title(f"Payslip - {payslip['first_name']} {payslip['last_name']}")
    win.geometry("680x720")
    win.minsize(560, 420)
    win.transient(parent.winfo_toplevel())
    win.lift()
    win.focus_force()
    win.after(50, win.lift)

    # Pack the footer FIRST, pinned to the bottom
    btn_row = ctk.CTkFrame(win, fg_color="transparent")
    btn_row.pack(side="bottom", fill="x", padx=14, pady=14)
    ctk.CTkButton(
        btn_row, text="Save as PDF", fg_color=BLUE_ACCENT, hover_color=BLUE_HOVER,
        command=lambda: _save_pdf(win, employee, payslip, period, earnings, deductions, company),
    ).pack(side="right")

    outer = ctk.CTkFrame(win, fg_color=NAVY_BORDER)
    outer.pack(side="top", fill="both", expand=True, padx=14, pady=(14, 0))

    # Scrollable frame for payslip content
    card = ctk.CTkScrollableFrame(outer, fg_color=PAPER, corner_radius=4)
    card.pack(fill="both", expand=True, padx=2, pady=2)

    _render_card(card, employee, payslip, period, earnings, deductions, company)


def _label_value_row(parent, label, value, row, col):
    ctk.CTkLabel(parent, text=label, text_color=ACCENT_INK, font=("Segoe UI", 11, "bold"),
                 fg_color="transparent", anchor="w").grid(row=row, column=col, sticky="w", pady=2)
    ctk.CTkLabel(parent, text=":", text_color=INK, fg_color="transparent",
                 width=10).grid(row=row, column=col + 1, sticky="w")
    ctk.CTkLabel(parent, text=str(value or "-"), text_color=INK, font=("Segoe UI", 11),
                 fg_color="transparent", anchor="w").grid(row=row, column=col + 2, sticky="w", pady=2)


def _render_card(card, employee, payslip, period, earnings, deductions, company):
    for c in range(6):
        card.grid_columnconfigure(c, weight=1)

    comp_name = company.get("name") or getattr(config, "APP_NAME", "Your Company Name")
    comp_address = company.get("address") or "Company Address Not Set"
    zimra_bp = company.get("tax_number", "")
    reg_number = company.get("reg_number", "")

    # --- Letterhead ---
    ctk.CTkLabel(card, text=comp_name, text_color=INK,
                 font=("Segoe UI", 20, "bold")).grid(row=0, column=0, columnspan=6, pady=(18, 0))
    ctk.CTkLabel(card, text=comp_address, text_color=ACCENT_INK,
                 font=("Segoe UI", 11)).grid(row=1, column=0, columnspan=6, pady=(2, 2))
    
    if zimra_bp or reg_number:
        statutory_text = " | ".join(filter(None, [f"ZIMRA BP: {zimra_bp}" if zimra_bp else "", f"Reg No: {reg_number}" if reg_number else ""]))
        ctk.CTkLabel(card, text=statutory_text, text_color=ACCENT_INK,
                     font=("Segoe UI", 10, "italic")).grid(row=2, column=0, columnspan=6, pady=(0, 8))

    ctk.CTkLabel(card, text=f"Payslip for the period of {period['period_label']}", text_color=INK,
                 font=("Segoe UI", 12, "bold")).grid(row=3, column=0, columnspan=6, pady=(0, 12))

    ctk.CTkFrame(card, height=1, fg_color=NAVY_BORDER).grid(
        row=4, column=0, columnspan=6, sticky="ew", padx=16)

    # --- Employee details, two columns ---
    details = ctk.CTkFrame(card, fg_color="transparent")
    details.grid(row=5, column=0, columnspan=6, sticky="ew", padx=20, pady=14)
    for c in (0, 3):
        details.grid_columnconfigure(c, weight=0)

    _label_value_row(details, "Employee Id", employee["employee_no"], 0, 0)
    _label_value_row(details, "Department", employee["department"], 1, 0)
    _label_value_row(details, "Date Of Joining", employee["hire_date"], 2, 0)
    bank = employee["bank_name"] or "-"
    _label_value_row(details, "Bank Name", bank, 3, 0)

    _label_value_row(details, "Name", f"{employee['first_name']} {employee['last_name']}", 0, 4)
    _label_value_row(details, "Designation", employee["job_title"], 1, 4)
    _label_value_row(details, "Pay Frequency", (employee["pay_frequency"] or "-").title(), 2, 4)
    _label_value_row(details, "Bank Acct Number", employee["bank_account_no"], 3, 4)

    ctk.CTkFrame(card, height=1, fg_color=NAVY_BORDER).grid(
        row=6, column=0, columnspan=6, sticky="ew", padx=16)

    # --- Earnings / Deductions ---
    ed = ctk.CTkFrame(card, fg_color="transparent")
    ed.grid(row=7, column=0, columnspan=6, sticky="ew", padx=20, pady=(10, 4))
    ed.grid_columnconfigure(0, weight=1)
    ed.grid_columnconfigure(1, weight=1)

    left = ctk.CTkFrame(ed, fg_color="transparent")
    left.grid(row=0, column=0, sticky="new", padx=(0, 8))
    right = ctk.CTkFrame(ed, fg_color="transparent")
    right.grid(row=0, column=1, sticky="new", padx=(8, 0))

    ctk.CTkLabel(left, text="Earnings", text_color=INK, font=("Segoe UI", 11, "bold")).grid(
        row=0, column=0, sticky="w")
    ctk.CTkLabel(left, text="Amount", text_color=INK, font=("Segoe UI", 11, "bold")).grid(
        row=0, column=1, sticky="e")
    for i, line in enumerate(earnings, start=1):
        ctk.CTkLabel(left, text=line["label"], text_color=ACCENT_INK, font=("Segoe UI", 11)).grid(
            row=i, column=0, sticky="w", pady=1)
        ctk.CTkLabel(left, text=_money(line["amount"]), text_color=ACCENT_INK, font=("Segoe UI", 11)).grid(
            row=i, column=1, sticky="e", pady=1)
    left.grid_columnconfigure(0, weight=1)
    left.grid_columnconfigure(1, weight=0)

    ctk.CTkLabel(right, text="Deductions", text_color=INK, font=("Segoe UI", 11, "bold")).grid(
        row=0, column=0, sticky="w")
    ctk.CTkLabel(right, text="Amount", text_color=INK, font=("Segoe UI", 11, "bold")).grid(
        row=0, column=1, sticky="e")
    for i, line in enumerate(deductions, start=1):
        ctk.CTkLabel(right, text=line["label"], text_color=ACCENT_INK, font=("Segoe UI", 11)).grid(
            row=i, column=0, sticky="w", pady=1)
        ctk.CTkLabel(right, text=_money(line["amount"]), text_color=ACCENT_INK, font=("Segoe UI", 11)).grid(
            row=i, column=1, sticky="e", pady=1)
    right.grid_columnconfigure(0, weight=1)
    right.grid_columnconfigure(1, weight=0)

    ctk.CTkFrame(card, height=1, fg_color=NAVY_BORDER).grid(
        row=8, column=0, columnspan=6, sticky="ew", padx=16, pady=(8, 0))

    # --- Totals ---
    totals = ctk.CTkFrame(card, fg_color="transparent")
    totals.grid(row=9, column=0, columnspan=6, sticky="ew", padx=20, pady=8)
    totals.grid_columnconfigure(0, weight=1)
    totals.grid_columnconfigure(1, weight=1)
    ctk.CTkLabel(totals, text=f"Total Earnings: {_money(payslip['gross_pay'])}",
                 text_color=INK, font=("Segoe UI", 11, "bold")).grid(row=0, column=0, sticky="w")
    total_deductions = (payslip["gross_pay"] - payslip["net_pay"])
    ctk.CTkLabel(totals, text=f"Total Deductions: {_money(total_deductions)}",
                 text_color=INK, font=("Segoe UI", 11, "bold")).grid(row=0, column=1, sticky="w")

    ctk.CTkFrame(card, height=1, fg_color=NAVY_BORDER).grid(
        row=10, column=0, columnspan=6, sticky="ew", padx=16)

    ctk.CTkLabel(card, text=f"Net Pay (Rounded): {_money(payslip['net_pay'])}",
                 text_color=INK, font=("Segoe UI", 13, "bold")).grid(
        row=11, column=0, columnspan=6, pady=10)

    ctk.CTkLabel(card, text=f"(All figures in {CURRENCY_LABEL})", text_color=ACCENT_INK,
                 font=("Segoe UI", 10, "italic")).grid(row=12, column=0, columnspan=6)

    # --- Signatures ---
    sig = ctk.CTkFrame(card, fg_color="transparent")
    sig.grid(row=13, column=0, columnspan=6, sticky="ew", padx=20, pady=(30, 20))
    sig.grid_columnconfigure(0, weight=1)
    sig.grid_columnconfigure(1, weight=1)
    ctk.CTkFrame(sig, height=1, width=200, fg_color=INK).grid(row=0, column=0, pady=(0, 4))
    ctk.CTkFrame(sig, height=1, width=200, fg_color=INK).grid(row=0, column=1, pady=(0, 4))
    ctk.CTkLabel(sig, text="Employer's Signature", text_color=ACCENT_INK,
                 font=("Segoe UI", 10)).grid(row=1, column=0)
    ctk.CTkLabel(sig, text="Employee's Signature", text_color=ACCENT_INK,
                 font=("Segoe UI", 10)).grid(row=1, column=1)


# ---------------------------------------------------------------------
# PDF export
# ---------------------------------------------------------------------
def _save_pdf(win, employee, payslip, period, earnings, deductions, company):
    default_name = f"Payslip_{employee['employee_no']}_{period['period_label']}".replace(" ", "_")
    path = filedialog.asksaveasfilename(
        defaultextension=".pdf", filetypes=[("PDF files", "*.pdf")],
        initialfile=f"{default_name}.pdf", parent=win,
    )
    if not path:
        return
    try:
        build_payslip_pdf(path, employee, payslip, period, earnings, deductions, company)
    except ImportError:
        error(
            "PDF export requires the 'reportlab' package, which isn't installed.\n\n"
            "Install it with:\n    pip install reportlab"
        )
        return
    except Exception as e:
        error(f"Could not save the PDF:\n{e}")
        return
    info(f"Payslip saved to:\n{path}")


def build_payslip_pdf(path, employee, payslip, period, earnings, deductions, company):
    """Renders the same layout as the on-screen preview to a PDF file."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.enums import TA_CENTER
    from reportlab.platypus import (
        SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer,
    )

    ink = colors.HexColor(INK)
    accent = colors.HexColor(ACCENT_INK)

    comp_name = company.get("name") or getattr(config, "APP_NAME", "Your Company Name")
    comp_address = company.get("address") or "Company Address Not Set"
    zimra_bp = company.get("tax_number", "")
    reg_number = company.get("reg_number", "")

    styles = {
        "company": ParagraphStyle("company", fontName="Helvetica-Bold", fontSize=16,
                                   textColor=ink, alignment=TA_CENTER, spaceAfter=2),
        "address": ParagraphStyle("address", fontName="Helvetica", fontSize=9,
                                   textColor=accent, alignment=TA_CENTER, spaceAfter=2),
        "statutory": ParagraphStyle("statutory", fontName="Helvetica-Oblique", fontSize=9,
                                   textColor=accent, alignment=TA_CENTER, spaceAfter=8),
        "period": ParagraphStyle("period", fontName="Helvetica-Bold", fontSize=11,
                                  textColor=ink, alignment=TA_CENTER, spaceAfter=6),
        "footer": ParagraphStyle("footer", fontName="Helvetica-Oblique", fontSize=9,
                                  textColor=accent, alignment=TA_CENTER),
    }

    doc = SimpleDocTemplate(path, pagesize=A4, topMargin=16 * mm, bottomMargin=16 * mm,
                             leftMargin=16 * mm, rightMargin=16 * mm)
    story = []

    story.append(Paragraph(comp_name, styles["company"]))
    story.append(Paragraph(comp_address, styles["address"]))
    
    if zimra_bp or reg_number:
        statutory_text = " | ".join(filter(None, [f"ZIMRA BP: {zimra_bp}" if zimra_bp else "", f"Reg No: {reg_number}" if reg_number else ""]))
        story.append(Paragraph(statutory_text, styles["statutory"]))

    story.append(Paragraph(f"Payslip for the period of {period['period_label']}", styles["period"]))

    # Employee details grid
    details_data = [
        ["Employee Id", ":", employee["employee_no"] or "-", "", "Name", ":",
         f"{employee['first_name']} {employee['last_name']}"],
        ["Department", ":", employee["department"] or "-", "", "Designation", ":",
         employee["job_title"] or "-"],
        ["Date Of Joining", ":", employee["hire_date"] or "-", "", "Pay Frequency", ":",
         (employee["pay_frequency"] or "-").title()],
        ["Bank Name", ":", employee["bank_name"] or "-", "", "Bank Acct Number", ":",
         employee["bank_account_no"] or "-"],
    ]
    details_table = Table(details_data, colWidths=[85, 8, 110, 20, 90, 8, 90])
    details_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 0), (0, -1), accent),
        ("TEXTCOLOR", (4, 0), (4, -1), accent),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME", (4, 0), (4, -1), "Helvetica-Bold"),
        ("TEXTCOLOR", (2, 0), (2, -1), ink),
        ("TEXTCOLOR", (6, 0), (6, -1), ink),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(Spacer(1, 8))
    story.append(details_table)
    story.append(Spacer(1, 10))

    # Earnings / deductions
    rows = max(len(earnings), len(deductions))
    ed_data = [["Earnings", "Amount", "Deductions", "Amount"]]
    for i in range(rows):
        e = earnings[i] if i < len(earnings) else None
        d = deductions[i] if i < len(deductions) else None
        ed_data.append([
            e["label"] if e else "", _money(e["amount"]) if e else "",
            d["label"] if d else "", _money(d["amount"]) if d else "",
        ])
    total_deductions = payslip["gross_pay"] - payslip["net_pay"]
    ed_data.append(["Total Earnings", _money(payslip["gross_pay"]),
                     "Total Deductions", _money(total_deductions)])

    ed_table = Table(ed_data, colWidths=[130, 65, 130, 65])
    ed_style = [
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 1), (0, -2), accent),
        ("TEXTCOLOR", (2, 1), (2, -2), accent),
        ("TEXTCOLOR", (1, 1), (1, -2), accent),
        ("TEXTCOLOR", (3, 1), (3, -2), accent),
        ("TEXTCOLOR", (0, 0), (-1, 0), ink),
        ("TEXTCOLOR", (0, -1), (-1, -1), ink),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("ALIGN", (3, 0), (3, -1), "RIGHT"),
        ("LINEBELOW", (0, 0), (-1, 0), 0.75, ink),
        ("LINEABOVE", (0, -1), (-1, -1), 0.75, ink),
        ("LINEAFTER", (1, 0), (1, -1), 0.5, ink),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
    ]
    ed_table.setStyle(TableStyle(ed_style))
    story.append(ed_table)
    story.append(Spacer(1, 4))

    net_style = ParagraphStyle("net", fontName="Helvetica-Bold", fontSize=12,
                                textColor=ink, alignment=TA_CENTER, spaceBefore=6, spaceAfter=4)
    story.append(Paragraph(f"Net Pay (Rounded): {_money(payslip['net_pay'])}", net_style))
    story.append(Paragraph(f"(All figures in {CURRENCY_LABEL})", styles["footer"]))

    story.append(Spacer(1, 40))
    sig_table = Table([["_" * 30, "_" * 30], ["Employer's Signature", "Employee's Signature"]],
                       colWidths=[240, 240])
    sig_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 0), (-1, -1), accent),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
    ]))
    story.append(sig_table)

    doc.build(story)