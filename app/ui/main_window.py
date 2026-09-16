import customtkinter as ctk
import csv
import ast
import operator
from datetime import date
import tksheet
from tkinter import filedialog
from datetime import timedelta

from ..database import get_connection, get_or_create_expense_account
from ..auth import Session, hash_password, set_security_question
from .. import config
from ..models import clients as client_model
from ..models import loans as loan_model
from ..models import disbursements as disb_model
from ..models import repayments as repay_model
from ..models import rollovers as rollover_model
from ..models import bad_debts as bd_model
from ..models import fees as fee_model
from ..models import expenses as expense_model
from ..models import equity_liabilities as eq_model
from ..models import reports as report_model
from ..models import financials as fin_model
from ..models import chart_of_accounts as coa_model
from ..models import accounting
from ..models import settings as settings_model
from ..models import payroll as payroll_model
from ..models import leave as leave_model
from ..models import budgets as budget_model
from .. import permissions as perm_model
from .widgets import (DataTable, FormDialog, SearchableCombobox, DatePicker, SectionedFormDialog, SectionedFormFrame, info, error, confirm,
                      TrendChart, status_label, enable_quick_math,
                      NAVY_DEEP, NAVY_MID, NAVY_CARD, NAVY_BORDER, BLUE_ACCENT, BLUE_HOVER, BLUE_LIGHT,
                      TEXT_PRIMARY, TEXT_MUTED, TEXT_DIM,
                      PRIMARY, PRIMARY_HOVER, SUCCESS, SUCCESS_HOVER, DANGER, DANGER_HOVER,
                      WARNING, WARNING_HOVER, SLATE, SLATE_HOVER,
                      primary_button, success_button, danger_button, secondary_button, outline_button,
                      card_header, styled_tabview, resizable_split)
from . import payslip_document
from ..money import fmt as _fmt_cents, to_cents


# ---------------------------------------------------------------------
# Safe arithmetic evaluator used for "=" formulas typed into sheet cells.
# Deliberately does NOT use eval()/exec() - only a whitelist of arithmetic
# AST nodes/operators is allowed, so a cell can never execute arbitrary code.
# ---------------------------------------------------------------------
_FORMULA_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub,
    ast.Mult: operator.mul, ast.Div: operator.truediv,
    ast.Pow: operator.pow, ast.USub: operator.neg, ast.UAdd: operator.pos,
}

def evaluate_cell_formula(expr: str) -> float:
    expr = expr.strip()
    if expr.startswith("="):
        expr = expr[1:]
    if not expr.strip():
        raise ValueError("Empty formula.")

    try:
        node = ast.parse(expr, mode="eval").body
    except SyntaxError:
        raise ValueError(f"Couldn't parse formula: {expr}")

    def _eval(n):
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return n.value
        if isinstance(n, ast.BinOp) and type(n.op) in _FORMULA_OPS:
            return _FORMULA_OPS[type(n.op)](_eval(n.left), _eval(n.right))
        if isinstance(n, ast.UnaryOp) and type(n.op) in _FORMULA_OPS:
            return _FORMULA_OPS[type(n.op)](_eval(n.operand))
        raise ValueError(f"Unsupported expression: {expr}")

    return _eval(node)

CUR = config.CURRENCY_SYMBOL


def money(v):
    """Display formatter. `v` is INTEGER CENTS (as stored in the DB and
    returned by every model function) - NOT dollars. Formats as e.g.
    '$1,234.56'. Falls back to returning v unchanged if it isn't numeric
    (e.g. None, or an already-formatted string passed through by mistake)."""
    try:
        return _fmt_cents(v, symbol=CUR)
    except (TypeError, ValueError):
        return v


def money_edit_str(cents):
    """Plain decimal string (no $ symbol, no thousands separator) for
    pre-filling an editable entry field with an existing money value, e.g.
    money_edit_str(123456) -> '1234.56'. Use this (not money()) whenever
    populating an Entry/field the user can then edit and re-submit through
    parse_money()."""
    if cents in (None, ""):
        return ""
    return f"{int(cents) / 100:.2f}"


def parse_money(s):
    """Input parser: takes whatever a user typed into a dollar-amount entry
    field (a string like '1,000.50' or '$45') and returns INTEGER CENTS,
    ready to hand to a model function. This is the boundary going the other
    direction from money() above - every money CTkEntry.get() should be
    parsed through this before being used, not through bare float()."""
    if s is None:
        return 0
    if isinstance(s, str):
        s = s.strip().replace(",", "").replace(CUR, "").replace("$", "")
        if not s:
            return 0
    return to_cents(s)


FREQUENCY_TERM_LABEL = {"weekly": "Term (weeks)*", "biweekly": "Term (fortnights)*", "monthly": "Term (months)*"}


# ---------------------------------------------------------------------
# Shared bulk-upload helpers (CSV template download + CSV upload + a
# consistent success/error summary dialog). Used by Clients, Loans, and
# Repayments bulk-import buttons.
# ---------------------------------------------------------------------
def _download_csv_template(headers, suggested_name):
    path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV files", "*.csv")],
                                         initialfile=suggested_name)
    if not path:
        return
    try:
        with open(path, "w", newline="") as f:
            csv.writer(f).writerow(headers)
        info(f"Template saved to:\n{path}\n\nFill it in and use the matching Bulk Upload button to import it.")
    except PermissionError:
        error("Cannot write to that location. Please choose a different folder (e.g., Desktop or Documents).")
    except Exception as e:
        error(f"Error saving template: {str(e)}")


def _pick_csv_upload():
    path = filedialog.askopenfilename(filetypes=[("CSV files", "*.csv"), ("All files", "*.*")])
    if not path:
        return None
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _show_bulk_result(entity_label, success, errors):
    msg = f"{success} {entity_label} imported successfully."
    if errors:
        shown = errors[:20]
        msg += f"\n\n{len(errors)} row(s) failed:\n" + "\n".join(shown)
        if len(errors) > 20:
            msg += f"\n...and {len(errors) - 20} more."
    if errors and success == 0:
        error(msg)
    else:
        info(msg)


# =====================================================================
# MAIN WINDOW
# =====================================================================
class MainWindowFrame(ctk.CTkFrame):
    def __init__(self, master, user):
        super().__init__(master, fg_color="transparent")
        Session.current_user = dict(user)
        self.conn = get_connection()
        # master is the single persistent AppRoot; it already owns the
        # window chrome (title/geometry/appearance mode), so just set the title here.
        master.title(f"{config.APP_NAME} - {config.APP_VERSION}")

        # Automatic overdue-penalty engine disabled: penalties should only ever
        # appear on a statement when a staff member manually charges one
        # (see LoansView._charge_penalty), otherwise penalty stays at 0.
        # fee_model.apply_overdue_penalties(self.conn, user_id=user["id"])

        self.configure(fg_color=NAVY_DEEP)

        # Draggable divider between sidebar and content, so the sidebar can
        # be made wider/narrower to taste.
        self.split = resizable_split(self, orient="horizontal", bg=NAVY_DEEP)
        self.split.pack(fill="both", expand=True)

        self.sidebar = ctk.CTkFrame(self.split, width=240, corner_radius=0, fg_color=NAVY_MID)
        content_outer = ctk.CTkFrame(self.split, fg_color=NAVY_DEEP)
        self.content = ctk.CTkFrame(content_outer, fg_color=NAVY_DEEP)
        self.content.pack(fill="both", expand=True, padx=20, pady=20)

        self.split.add(self.sidebar, width=240, minsize=200)
        self.split.add(content_outer, minsize=500, stretch="always")

        # ---- Brand block ----
        brand = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        brand.pack(fill="x", pady=(24, 0))
        ctk.CTkLabel(brand, text="💎", font=("Segoe UI", 28)).pack()
        ctk.CTkLabel(brand, text=config.APP_NAME, font=("Segoe UI", 17, "bold"),
                     text_color=BLUE_LIGHT, wraplength=200).pack(pady=(4, 0), padx=14)

        # ---- Signed-in-user card ----
        user_card = ctk.CTkFrame(self.sidebar, fg_color=NAVY_CARD, corner_radius=10)
        user_card.pack(fill="x", padx=16, pady=(16, 10))
        initials = "".join(w[0] for w in user["full_name"].split()[:2]).upper() or "U"
        avatar = ctk.CTkFrame(user_card, width=36, height=36, corner_radius=18, fg_color=BLUE_ACCENT)
        avatar.grid(row=0, column=0, rowspan=2, padx=(10, 8), pady=10)
        avatar.grid_propagate(False)
        ctk.CTkLabel(avatar, text=initials, font=("Segoe UI", 13, "bold"), text_color="white").place(relx=0.5, rely=0.5, anchor="center")
        ctk.CTkLabel(user_card, text=user["full_name"], font=("Segoe UI", 12, "bold"),
                     text_color=TEXT_PRIMARY, anchor="w").grid(row=0, column=1, sticky="w", pady=(10, 0))
        ctk.CTkLabel(user_card, text=user["role"].replace("_", " ").title(),
                     font=("Segoe UI", 10), text_color=TEXT_MUTED, anchor="w").grid(row=1, column=1, sticky="w", pady=(0, 10))
        user_card.grid_columnconfigure(1, weight=1)

        # ---- Navigation, grouped into clear sections ----
        nav_scroll = ctk.CTkScrollableFrame(self.sidebar, fg_color="transparent")
        nav_scroll.pack(fill="both", expand=True, padx=8, pady=(4, 0))

        def section_label(text):
            ctk.CTkLabel(nav_scroll, text=text.upper(), font=("Segoe UI", 10, "bold"),
                         text_color=TEXT_DIM, anchor="w").pack(fill="x", padx=8, pady=(14, 4))

        self.nav_buttons = {}
        # Ordered (view_cls, name) pairs for the first 9 nav items, so they can
        # be jumped to with Alt+1..Alt+9 (see keyboard-shortcut binding below).
        self._nav_shortcuts = []

        def add_nav_button(name, view_cls):
            idx = len(self._nav_shortcuts) + 1
            btn = ctk.CTkButton(nav_scroll, text=name, anchor="w", fg_color="transparent",
                                 text_color=TEXT_PRIMARY, hover_color=NAVY_BORDER,
                                 font=("Segoe UI", 13), height=40, corner_radius=8,
                                 command=lambda v=view_cls, n=name: self.show_view(v, n))
            btn.pack(fill="x", padx=4, pady=3)
            self.nav_buttons[name] = btn
            if idx <= 9:
                self._nav_shortcuts.append((view_cls, name))

        section_label("Overview")
        add_nav_button("📊  Dashboard", DashboardView)

        operations_nav = [
            ("👥  Clients", ClientsView, "Clients"),
            ("💰  Loans", LoansView, "Loans"),
            ("🔄  Rollovers", RolloversView, "Rollovers"),
            ("⚠️  Bad Debts", BadDebtsView, "Bad Debts"),
        ]
        finance_nav = [
            ("📑  Reports", ReportsView, "Reports"),
            ("⚖️  Accounting", AccountingView, "Accounting"),
            ("🧾  Payroll", PayrollView, "Payroll"),
        ]
        visible_ops = [(n, v) for n, v, m in operations_nav if perm_model.has_permission(self.conn, user, m)]
        visible_fin = [(n, v) for n, v, m in finance_nav if perm_model.has_permission(self.conn, user, m)]

        if visible_ops:
            section_label("Operations")
            for name, view_cls in visible_ops:
                add_nav_button(name, view_cls)
        if visible_fin:
            section_label("Finance")
            for name, view_cls in visible_fin:
                add_nav_button(name, view_cls)
        if user["role"] == "admin":
            section_label("Administration")
            add_nav_button("👤  Users", UsersView)
            add_nav_button("⚙️  Settings", SettingsView)

        ctk.CTkFrame(self.sidebar, height=1, fg_color=NAVY_BORDER).pack(fill="x", padx=16, pady=(8, 0))
        danger_button(self.sidebar, "Log Out", self._logout, icon="🚪", height=38,
                      corner_radius=8).pack(side="bottom", fill="x", padx=12, pady=18)

        # ---- Keyboard shortcuts: Alt+1..Alt+9 jump straight to a sidebar
        # section, in the order the buttons appear. Bound on the root window
        # (not just this frame) so it works no matter what has focus.
        root = self.winfo_toplevel()
        for i, (view_cls, name) in enumerate(self._nav_shortcuts, start=1):
            root.bind(f"<Alt-KeyPress-{i}>", lambda e, v=view_cls, n=name: self.show_view(v, n))

        self.current_view = None
        self.show_view(DashboardView, "📊  Dashboard")

    def show_view(self, view_cls, name):
        for widget in self.content.winfo_children():
            widget.destroy()
        for n, btn in self.nav_buttons.items():
            btn.configure(fg_color=BLUE_ACCENT if n == name else "transparent",
                          font=("Segoe UI", 13, "bold" if n == name else "normal"))
        self.current_view = view_cls(self.content, self.conn, self)
        self.current_view.pack(fill="both", expand=True)

    def _logout(self):
        self.conn.close()
        Session.logout()
        # self.master is the single persistent AppRoot. Ask it to swap back
        # to the login frame instead of destroying this window and creating
        # a second ctk.CTk() root (that second-root pattern is what caused
        # the "invalid command name ... check_dpi_scaling / _click_animation" errors).
        self.master.show_login()


class BaseView(ctk.CTkFrame):
    def __init__(self, master, conn, app):
        super().__init__(master, fg_color="transparent")
        self.conn = conn
        self.app = app

    def header(self, text):
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(fill="x", pady=(0, 16))
        ctk.CTkFrame(hdr, width=5, height=28, fg_color=BLUE_ACCENT, corner_radius=3).pack(side="left", padx=(0, 10))
        ctk.CTkLabel(hdr, text=text, font=("Segoe UI", 21, "bold"), text_color=TEXT_PRIMARY).pack(side="left")

    def toolbar(self):
        bar = ctk.CTkFrame(self, fg_color=NAVY_CARD, corner_radius=10,
                            border_width=1, border_color=NAVY_BORDER)
        bar.pack(fill="x", pady=(0, 14), ipady=10)
        return bar


# =====================================================================
# DASHBOARD
# =====================================================================
class DashboardView(BaseView):
    def __init__(self, master, conn, app):
        super().__init__(master, conn, app)
        self.header("Dashboard")
        summary = report_model.portfolio_summary(conn)

        # Active clients = those with at least one active loan
        active_count = conn.execute("""
            SELECT COUNT(DISTINCT c.id)
            FROM clients c
            JOIN loans l ON l.client_id = c.id AND l.status = 'Active'
        """).fetchone()[0]

        inactive_count = conn.execute("""
            SELECT COUNT(DISTINCT c.id)
            FROM clients c
            LEFT JOIN loans l ON l.client_id = c.id AND l.status = 'Active'
            WHERE c.status != 'Blacklisted' AND l.id IS NULL
        """).fetchone()[0]

        # ---- Today / this-week collections snapshot ----
        # Reuses the same report_model function that powers the "Clients Due
        # Per Day" report elsewhere, so the numbers always agree with it.
        today = date.today()
        due_today_total, due_today_count, week_total = 0, 0, 0
        try:
            today_data = report_model.clients_due_per_day_report(conn, today.isoformat())
            due_today_total = today_data.get("total", 0) or 0
            due_today_count = today_data.get("count", 0) or 0
            week_total = due_today_total
            for i in range(1, 7):
                day_data = report_model.clients_due_per_day_report(
                    conn, (today + timedelta(days=i)).isoformat()
                )
                week_total += day_data.get("total", 0) or 0
        except Exception:
            # Collections snapshot is a nice-to-have; never let it break the dashboard.
            pass

        # Everything below the header lives in a scrollable body so the
        # page can grow (stats + trend chart + location performance +
        # aging breakdown + arrears) without ever clipping content off
        # the bottom of the window.
        body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True)

        # ---- Stats cards ----
        cards_frame = ctk.CTkFrame(body, fg_color="transparent")
        cards_frame.pack(fill="x", pady=10)

        stats = [
            ("👥 Active Clients", active_count, "#2D9CDB"),
            ("👥 Inactive Clients", inactive_count, "#2D9CDB"),
            ("💰 Active Loans", summary["active_loans"], "#27AE60"),
            ("⏳ Pending Approval", summary["pending_approval"], "#27AE60"),
            ("📊 Gross Outstanding", money(summary["gross_outstanding_principal"]), "#F2994A"),
            ("📊 Portfolio at Risk", money(summary["portfolio_at_risk"]), "#F2994A"),
            ("📊 PAR Ratio", f"{summary['par_ratio_pct']}%", "#F2994A"),
            ("🗓️ Due Today", f"{money(due_today_total)}  ({due_today_count})", "#9B59B6"),
            ("📅 Due This Week", money(week_total), "#9B59B6"),
        ]

        for i, (label, value, color) in enumerate(stats):
            row = i // 3
            col = i % 3
            card = ctk.CTkFrame(
                cards_frame,
                corner_radius=12,
                fg_color=NAVY_MID,
                border_width=1,
                border_color=NAVY_BORDER,
            )
            card.grid(row=row, column=col, padx=8, pady=8, sticky="nsew")
            cards_frame.grid_columnconfigure(col, weight=1)

            accent = ctk.CTkFrame(card, height=4, fg_color=color, corner_radius=0)
            accent.pack(fill="x")
            ctk.CTkLabel(card, text=str(value), font=("Segoe UI", 22, "bold"),
                         text_color=BLUE_LIGHT).pack(padx=16, pady=(12, 2))
            ctk.CTkLabel(card, text=label, font=("Segoe UI", 11),
                         text_color=TEXT_MUTED).pack(padx=16, pady=(0, 14))

        # ---- 6-month Disbursements vs Collections trend ----
        ctk.CTkLabel(
            body,
            text="📈 Disbursements vs Collections vs Budget (Last 6 Months)",
            font=("Segoe UI", 14, "bold"),
            text_color=TEXT_PRIMARY,
        ).pack(anchor="w", pady=(16, 4))

        months = []
        for i in range(5, -1, -1):
            y, m = today.year, today.month - i
            while m <= 0:
                m += 12
                y -= 1
            months.append((y, m))

        disb_rows = conn.execute("""
            SELECT strftime('%Y-%m', disbursement_date) AS ym, COALESCE(SUM(principal), 0) AS total
            FROM loans
            WHERE disbursement_date IS NOT NULL
            GROUP BY ym
        """).fetchall()
        disb_map = {r["ym"]: r["total"] for r in disb_rows}

        repay_rows = conn.execute("""
            SELECT strftime('%Y-%m', payment_date) AS ym, COALESCE(SUM(amount), 0) AS total
            FROM repayments
            WHERE payment_date IS NOT NULL
            GROUP BY ym
        """).fetchall()
        repay_map = {r["ym"]: r["total"] for r in repay_rows}

        trend_data = [
            {
                "label": date(y, m, 1).strftime("%b"),
                "values": {
                    "Disbursed": disb_map.get(f"{y:04d}-{m:02d}", 0) or 0,
                    "Collected": repay_map.get(f"{y:04d}-{m:02d}", 0) or 0,
                },
            }
            for y, m in months
        ]

        # Budgeted disbursements/collections for the same 6 months, so each
        # bar can be measured against its target. Cached per calendar year
        # since the trailing 6-month window can span a year boundary.
        budget_by_year = {}
        disb_targets, collect_targets = [], []
        for y, m in months:
            if y not in budget_by_year:
                try:
                    budget_by_year[y] = budget_model.monthly_disbursements_and_collections_budget(self.conn, y)
                except Exception:
                    # Budget targets are a nice-to-have; never let them break the dashboard.
                    budget_by_year[y] = ([0.0] * 12, [0.0] * 12)
            disb_by_month, coll_by_month = budget_by_year[y]
            disb_targets.append(disb_by_month[m - 1])
            collect_targets.append(coll_by_month[m - 1])

        trend_chart = TrendChart(
            body,
            data=trend_data,
            series=[("Disbursed", "#2D9CDB"), ("Collected", "#27AE60")],
            targets={"Disbursed": disb_targets, "Collected": collect_targets},
            height=200,
            value_fmt=lambda v: money(v),
        )
        trend_chart.pack(fill="x", pady=8, padx=2)

        # ---- Location Performance ----
        ctk.CTkLabel(
            body,
            text="📍 Location Performance",
            font=("Segoe UI", 14, "bold"),
            text_color=TEXT_PRIMARY,
        ).pack(anchor="w", pady=(16, 4))

        location_data = report_model.location_performance(conn)
        location_table = DataTable(
            body,
            columns=[
                ("location", "Location"),
                ("active_clients", "Active Clients"),
                ("active_loans", "Active Loans"),
                ("outstanding_principal", "Outstanding"),
                ("par_amount", "PAR Amount"),
                ("par_ratio", "PAR Ratio"),
            ],
            height=6,
        )
        location_table.pack(fill="x", pady=8, padx=2)
        # Format the numeric columns
        for row in location_data:
            row["outstanding_principal"] = money(row["outstanding_principal"])
            row["par_amount"] = money(row["par_amount"])
            row["par_ratio"] = f"{row['par_ratio']}%"
        location_table.set_rows(location_data)

        # ---- Overdue aging breakdown ----
        ctk.CTkLabel(
            body,
            text="⏰ Overdue Aging Breakdown (Past Maturity)",
            font=("Segoe UI", 14, "bold"),
            text_color=TEXT_PRIMARY,
        ).pack(anchor="w", pady=(16, 4))

        try:
            past_maturity_rows = report_model.past_maturity_report(conn)
        except Exception:
            past_maturity_rows = []

        aging_buckets = [
            ("1-30 days", 1, 30),
            ("31-60 days", 31, 60),
            ("61-90 days", 61, 90),
            ("90+ days", 91, None),
        ]
        aging_data = []
        for label, lo, hi in aging_buckets:
            matched = [
                r for r in past_maturity_rows
                if r.get("ageing_days") is not None and r["ageing_days"] >= lo and (hi is None or r["ageing_days"] <= hi)
            ]
            aging_data.append({
                "bucket": label,
                "loan_count": len(matched),
                "balance": money(sum(r["balance"] for r in matched)),
            })

        aging_table = DataTable(
            body,
            columns=[
                ("bucket", "Aging Bucket"),
                ("loan_count", "Loans"),
                ("balance", "Outstanding Balance"),
            ],
            height=4,
        )
        aging_table.pack(fill="x", pady=8, padx=2)
        aging_table.set_rows(aging_data)

        # ---- Arrears table ----
        ctk.CTkLabel(
            body,
            text="🔴 Top Arrears (Portfolio at Risk)",
            font=("Segoe UI", 14, "bold"),
            text_color=TEXT_PRIMARY,
        ).pack(anchor="w", pady=(16, 4))

        table = DataTable(
            body,
            columns=[
                ("loan_no", "Loan #"),
                ("client_name", "Client"),
                ("aging_bucket", "Aging"),
                ("max_days_overdue", "Days Overdue"),
                ("amount_overdue", "Overdue Amount"),
            ],
            height=10,
        )
        table.pack(fill="both", expand=True, pady=8)
        rows = report_model.arrears_report(conn)[:15]
        for r in rows:
            r["amount_overdue"] = money(r["amount_overdue"])
        table.set_rows(rows)


# =====================================================================
# CLIENTS
# =====================================================================
class ClientsView(BaseView):
    def __init__(self, master, conn, app):
        super().__init__(master, conn, app)

        # ---- Header with title + bulk upload buttons ----
        header_frame = ctk.CTkFrame(self, fg_color="transparent")
        header_frame.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(header_frame, text="Client Registry", font=("Segoe UI", 21, "bold"), text_color=TEXT_PRIMARY).pack(side="left")

        bulk_buttons = ctk.CTkFrame(header_frame, fg_color="transparent")
        bulk_buttons.pack(side="right")
        ctk.CTkButton(bulk_buttons, text="Download Template", fg_color="gray40", height=26, width=130,
                      command=self._download_client_template).pack(side="left", padx=(0, 6))
        ctk.CTkButton(bulk_buttons, text="Bulk Upload Clients", fg_color="#27AE60", height=26, width=130,
                      font=("Segoe UI", 11, "bold"), command=self._bulk_upload_clients).pack(side="left")

        # ---- Action bar (New, Edit, Delete, View History) ----
        bar = ctk.CTkFrame(self, fg_color=NAVY_MID, corner_radius=10)
        bar.pack(fill="x", pady=(0, 14), ipady=6)
        ctk.CTkButton(bar, text="+ New Client", command=self._new_client).pack(side="left", padx=6)
        ctk.CTkButton(bar, text="Edit Selected", command=self._edit_client).pack(side="left", padx=6)
        ctk.CTkButton(bar, text="Delete Selected", fg_color="#EB5757", hover_color="#C0392B",
                      command=self._delete_client).pack(side="left", padx=6)
        ctk.CTkButton(bar, text="View Loan History", command=self._view_history).pack(side="left", padx=6)
        ctk.CTkButton(bar, text="Payment Behavior", command=self._view_payment_behavior).pack(side="left", padx=6)

        # ---- Table ----
        self.table = DataTable(self, columns=[
            ("client_no", "Client #"),
            ("name", "Name"),
            ("national_id", "National ID"),
            ("gender", "Gender"),
            ("location", "Location"),
            ("phone", "Phone"),
            ("address", "Address"),
            ("occupation", "Occupation"),
            ("status", "Status"),
            ("average_income", "Avg Income"),
            ("guarantor", "Guarantor"),
            ("guarantor_phone", "Guarantor Phone"),
            ("notes", "Notes"),
        ], show_summary=False)
        self.table.pack(fill="both", expand=True)
        self.refresh()

    # ========================== EXISTING METHODS ==========================
    def refresh(self):
        cur = self.conn.execute("""
            SELECT
                c.*,
                COUNT(l.id) AS active_loans
            FROM clients c
            LEFT JOIN loans l ON l.client_id = c.id AND l.status = 'Active'
            GROUP BY c.id
        """)
        rows = []
        for c in cur.fetchall():
            stored_status = c["status"]
            if stored_status == "Blacklisted":
                display_status = "Blacklisted"
            elif c["active_loans"] > 0:
                display_status = "Active"
            else:
                display_status = "Inactive"

            rows.append({
                "id": c["id"],
                "client_no": c["client_no"],
                "name": f"{c['first_name']} {c['last_name']}",
                "national_id": c["national_id"] or "",
                "gender": c["gender"] or "",
                "location": c["location"] or "",
                "phone": c["phone"] or "",
                "address": c["address"] or "",
                "occupation": c["occupation"] or "",
                "status": display_status,
                "average_income": money(c["average_income"]) if c["average_income"] else "",
                "guarantor": c["guarantor"] or "",
                "guarantor_phone": c["guarantor_phone"] or "",
                "notes": c["notes"] or "",
            })
        self.table.set_rows(rows)

    def _download_client_template(self):
        _download_csv_template(
            ["first_name", "last_name", "national_id", "gender", "location", "phone",
             "address", "occupation", "average_income", "guarantor", "guarantor_phone", "notes"],
            "clients_template.csv",
        )

    def _bulk_upload_clients(self):
        rows = _pick_csv_upload()
        if rows is None:
            return
        success, errors = 0, []
        for i, row in enumerate(rows, start=2):
            try:
                data = {k: (v.strip() if isinstance(v, str) else v)
                        for k, v in row.items() if v not in (None, "")}
                if not data.get("first_name") or not data.get("last_name"):
                    raise ValueError("first_name and last_name are required.")
                if data.get("average_income"):
                    data["average_income"] = parse_money(data["average_income"])
                client_model.create_client(self.conn, data, user_id=Session.current_user["id"])
                success += 1
            except Exception as e:
                errors.append(f"Row {i}: {e}")
        _show_bulk_result("client(s)", success, errors)
        self.refresh()

    def _delete_client(self):
        if not perm_model.has_permission(self.conn, Session.current_user, "Clients", "delete"):
            error("You do not have permission to delete clients.")
            return

        row = self.table.selected_row()
        if not row:
            error("Select a client first.")
            return

        client_id = int(row["id"])
        client_name = row["name"]

        loans = client_model.client_loan_history(self.conn, client_id)
        if loans:
            error(f"Cannot delete client '{client_name}' because they have {len(loans)} loan(s). "
                  "Please resolve or remove the loans first.")
            return

        if not confirm(f"Permanently delete client '{client_name}'?\n\nThis action cannot be undone."):
            return

        try:
            self.conn.execute("DELETE FROM clients WHERE id = ?", (client_id,))
            self.conn.commit()
            info(f"Client '{client_name}' deleted.")
            self.refresh()
        except Exception as e:
            error(str(e))

    def _view_history(self):
        row = self.table.selected_row()
        if not row:
            error("Select a client first.")
            return

        client = client_model.get_client(self.conn, int(row["id"]))
        loans = client_model.client_loan_history(self.conn, int(row["id"]))

        win = ctk.CTkToplevel(self)
        win.title(f"Loan History - {row['name']}")
        win.geometry("900x400")
        win.resizable(True, True)
        win.transient(self.winfo_toplevel())
        win.lift()
        win.focus_force()
        win.after(50, win.lift)

        table = DataTable(win, columns=[
            ("loan_no", "Loan #"), ("principal", "Principal"), ("status", "Status"),
            ("disbursement_date", "Disbursed"), ("maturity_date", "Maturity"),
            ("cleared_date", "Cleared")
        ], title=f"Loan History - {row['name']}")
        table.pack(fill="both", expand=True, padx=10, pady=10)

        history_rows = []
        for l in loans:
            cleared_date = "-"
            if l["status"] == "Closed":
                cur = self.conn.execute(
                    "SELECT MAX(payment_date) as c_date FROM repayments WHERE loan_id = ?",
                    (l["id"],)
                ).fetchone()
                if cur and cur["c_date"]:
                    cleared_date = cur["c_date"]

            history_rows.append({
                "loan_no": l["loan_no"],
                "principal": money(l["principal"]),
                "status": l["status"],
                "disbursement_date": l["disbursement_date"] or "-",
                "maturity_date": l["maturity_date"] or "-",
                "cleared_date": cleared_date
            })

        table.set_rows(history_rows)

        if client:
            table.set_pdf_meta([
                f"Client: {client['first_name']} {client['last_name']}  (Client #: {client['client_no']})",
                f"National ID: {client['national_id'] or '-'}    Phone: {client['phone'] or '-'}    "
                f"Location: {client['location'] or '-'}",
            ])

        self._history_window = win

    def _view_payment_behavior(self):
        row = self.table.selected_row()
        if not row:
            error("Select a client first.")
            return

        client_id = int(row["id"])
        client = client_model.get_client(self.conn, client_id)
        data = client_model.client_payment_behavior(self.conn, client_id)
        summary = data["summary"]

        win = ctk.CTkToplevel(self)
        win.title(f"Payment Behavior - {row['name']}")
        win.geometry("1050x600")
        win.resizable(True, True)
        win.transient(self.winfo_toplevel())
        win.configure(fg_color=NAVY_DEEP)
        win.lift()
        win.focus_force()
        win.after(50, win.lift)

        ctk.CTkLabel(win, text=f"Payment Behavior - {row['name']} ({row['client_no']})",
                     font=("Segoe UI", 16, "bold"), text_color=TEXT_PRIMARY).pack(anchor="w", padx=14, pady=(12, 4))

        # ---- Summary cards: on-time rate, avg days late, typical payment size ----
        cards_frame = ctk.CTkFrame(win, fg_color="transparent")
        cards_frame.pack(fill="x", padx=14, pady=(0, 10))

        on_time_display = f"{summary['on_time_rate']}%" if summary["on_time_rate"] is not None else "N/A"
        stats = [
            ("✅ On-Time Rate", on_time_display, "#27AE60"),
            ("⏰ Avg Days Late", f"{summary['avg_days_late']} days" if summary["late_count"] else "0 days", "#F2994A"),
            ("💵 Avg Payment", money(summary["avg_payment_amount"]), "#2D9CDB"),
            ("📈 Largest Payment", money(summary["largest_payment"]), "#2D9CDB"),
            ("📉 Smallest Payment", money(summary["smallest_payment"]), "#2D9CDB"),
            ("🧾 Installments Settled", f"{summary['on_time_count']} on-time / {summary['late_count']} late", "#9B59B6"),
        ]
        for i, (label, value, color) in enumerate(stats):
            card = ctk.CTkFrame(cards_frame, corner_radius=12, fg_color=NAVY_MID,
                                 border_width=1, border_color=NAVY_BORDER)
            card.grid(row=0, column=i, padx=6, pady=4, sticky="nsew")
            cards_frame.grid_columnconfigure(i, weight=1)
            ctk.CTkFrame(card, height=4, fg_color=color, corner_radius=0).pack(fill="x")
            ctk.CTkLabel(card, text=str(value), font=("Segoe UI", 15, "bold"),
                         text_color=BLUE_LIGHT).pack(padx=10, pady=(10, 2))
            ctk.CTkLabel(card, text=label, font=("Segoe UI", 10),
                         text_color=TEXT_MUTED).pack(padx=10, pady=(0, 10))

        if summary["total_settled"] == 0:
            ctk.CTkLabel(win, text="No settled installments yet for this client - not enough history "
                                    "to judge payment punctuality.",
                         font=("Segoe UI", 11), text_color=TEXT_MUTED).pack(anchor="w", padx=14, pady=(0, 6))

        # ---- Installment-level detail table ----
        table = DataTable(win, columns=[
            ("loan_no", "Loan #"), ("installment_no", "Installment"), ("due_date", "Due Date"),
            ("amount_due", "Amount Due"), ("amount_paid", "Amount Paid"),
            ("paid_date", "Paid Date"), ("timeliness", "Timeliness"), ("status", "Status"),
        ], title=f"Payment Behavior - {row['name']}")
        table.pack(fill="both", expand=True, padx=14, pady=(0, 14))

        detail_rows = []
        for inst in data["installments"]:
            if inst["days_late"] is None:
                timeliness = "-"
            elif inst["days_late"] > 0:
                timeliness = f"{inst['days_late']}d late"
            elif inst["days_late"] < 0:
                timeliness = f"{-inst['days_late']}d early"
            else:
                timeliness = "On due date"

            detail_rows.append({
                "loan_no": inst["loan_no"],
                "installment_no": inst["installment_no"],
                "due_date": inst["due_date"],
                "amount_due": money(inst["amount_due"]),
                "amount_paid": money(inst["amount_paid"]),
                "paid_date": inst["paid_date"] or "-",
                "timeliness": timeliness,
                "status": inst["status"],
            })
        table.set_rows(detail_rows)

        if client:
            table.set_pdf_meta([
                f"Client: {client['first_name']} {client['last_name']}  (Client #: {client['client_no']})",
                f"On-Time Rate: {on_time_display}    Avg Days Late: {summary['avg_days_late']}    "
                f"Avg Payment: {money(summary['avg_payment_amount'])}",
            ])

        self._payment_behavior_window = win

    # ========================== NEW DIALOG METHODS ==========================
    def _client_dialog(self, title, client=None):
        win = ctk.CTkToplevel(self)
        win.title(title)
        win.geometry("700x580")
        win.resizable(False, True)
        win.transient(self.winfo_toplevel())
        win.grab_set()
        win.configure(fg_color=NAVY_DEEP)

        scroll = ctk.CTkScrollableFrame(win, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=16, pady=16)

        card = ctk.CTkFrame(scroll, fg_color=("gray95", "gray15"), corner_radius=10)
        card.pack(fill="both", expand=True)

        fields = {}
        # All entries use this colour
        ENTRY_BG = "#1A3B5C"

        # ========== SECTION 1: Personal Details ==========
        sec1 = ctk.CTkFrame(card, fg_color="transparent")
        sec1.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(sec1, text="Personal Details", font=("Segoe UI", 13, "bold"), text_color=BLUE_LIGHT).pack(anchor="w")
        ctk.CTkFrame(sec1, height=2, fg_color=NAVY_BORDER).pack(fill="x", pady=(2, 4))

        row1 = ctk.CTkFrame(sec1, fg_color="transparent")
        row1.pack(fill="x", pady=2)
        row1.columnconfigure(0, weight=1, pad=4)
        row1.columnconfigure(1, weight=1, pad=4)

        # First Name
        fname_frame = ctk.CTkFrame(row1, fg_color="transparent")
        fname_frame.grid(row=0, column=0, sticky="nsew")
        ctk.CTkLabel(fname_frame, text="FIRST NAME*", font=("Segoe UI", 9, "bold"), text_color=TEXT_MUTED).pack(anchor="w")
        fname_entry = ctk.CTkEntry(fname_frame, height=26, fg_color=ENTRY_BG, text_color="white")
        fname_entry.pack(anchor="w", fill="x")
        fields["first_name"] = fname_entry

        # Last Name
        lname_frame = ctk.CTkFrame(row1, fg_color="transparent")
        lname_frame.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        ctk.CTkLabel(lname_frame, text="SURNAME*", font=("Segoe UI", 9, "bold"), text_color=TEXT_MUTED).pack(anchor="w")
        lname_entry = ctk.CTkEntry(lname_frame, height=26, fg_color=ENTRY_BG, text_color="white")
        lname_entry.pack(anchor="w", fill="x")
        fields["last_name"] = lname_entry

        row2 = ctk.CTkFrame(sec1, fg_color="transparent")
        row2.pack(fill="x", pady=2)
        row2.columnconfigure(0, weight=1, pad=4)
        row2.columnconfigure(1, weight=1, pad=4)

        # National ID
        nid_frame = ctk.CTkFrame(row2, fg_color="transparent")
        nid_frame.grid(row=0, column=0, sticky="nsew")
        ctk.CTkLabel(nid_frame, text="NATIONAL ID", font=("Segoe UI", 9, "bold"), text_color=TEXT_MUTED).pack(anchor="w")
        nid_entry = ctk.CTkEntry(nid_frame, height=26, fg_color=ENTRY_BG, text_color="white")
        nid_entry.pack(anchor="w", fill="x")
        fields["national_id"] = nid_entry

        # Gender
        gender_frame = ctk.CTkFrame(row2, fg_color="transparent")
        gender_frame.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        ctk.CTkLabel(gender_frame, text="GENDER", font=("Segoe UI", 9, "bold"), text_color=TEXT_MUTED).pack(anchor="w")
        gender_combo = ctk.CTkComboBox(gender_frame, values=["Male", "Female", "Other"], height=26,
                                    fg_color=ENTRY_BG, button_color=NAVY_BORDER, text_color="white")
        gender_combo.pack(anchor="w", fill="x")
        fields["gender"] = gender_combo

        row3 = ctk.CTkFrame(sec1, fg_color="transparent")
        row3.pack(fill="x", pady=2)
        row3.columnconfigure(0, weight=1, pad=4)
        row3.columnconfigure(1, weight=1, pad=4)

        # Occupation
        occ_frame = ctk.CTkFrame(row3, fg_color="transparent")
        occ_frame.grid(row=0, column=0, sticky="nsew")
        ctk.CTkLabel(occ_frame, text="OCCUPATION", font=("Segoe UI", 9, "bold"), text_color=TEXT_MUTED).pack(anchor="w")
        occ_entry = ctk.CTkEntry(occ_frame, height=26, fg_color=ENTRY_BG, text_color="white")
        occ_entry.pack(anchor="w", fill="x")
        fields["occupation"] = occ_entry

        # ========== SECTION 2: Contact & Address ==========
        sec2 = ctk.CTkFrame(card, fg_color="transparent")
        sec2.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(sec2, text="Contact & Address", font=("Segoe UI", 13, "bold"), text_color=BLUE_LIGHT).pack(anchor="w")
        ctk.CTkFrame(sec2, height=2, fg_color=NAVY_BORDER).pack(fill="x", pady=(2, 4))

        row4 = ctk.CTkFrame(sec2, fg_color="transparent")
        row4.pack(fill="x", pady=2)
        row4.columnconfigure(0, weight=1, pad=4)
        row4.columnconfigure(1, weight=1, pad=4)

        # Phone
        phone_frame = ctk.CTkFrame(row4, fg_color="transparent")
        phone_frame.grid(row=0, column=0, sticky="nsew")
        ctk.CTkLabel(phone_frame, text="PHONE", font=("Segoe UI", 9, "bold"), text_color=TEXT_MUTED).pack(anchor="w")
        phone_entry = ctk.CTkEntry(phone_frame, height=26, fg_color=ENTRY_BG, text_color="white")
        phone_entry.pack(anchor="w", fill="x")
        fields["phone"] = phone_entry

        # Location
        location_options = [r["name"] for r in settings_model.list_locations(self.conn, active_only=True)]
        loc_frame = ctk.CTkFrame(row4, fg_color="transparent")
        loc_frame.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        ctk.CTkLabel(loc_frame, text="LOCATION", font=("Segoe UI", 9, "bold"), text_color=TEXT_MUTED).pack(anchor="w")
        loc_combo = ctk.CTkComboBox(loc_frame, values=location_options, height=26,
                                    fg_color=ENTRY_BG, button_color=NAVY_BORDER, text_color="white")
        loc_combo.pack(anchor="w", fill="x")
        fields["location"] = loc_combo

        # Address (full width)
        row5 = ctk.CTkFrame(sec2, fg_color="transparent")
        row5.pack(fill="x", pady=2)
        ctk.CTkLabel(row5, text="ADDRESS", font=("Segoe UI", 9, "bold"), text_color=TEXT_MUTED).pack(anchor="w")
        addr_entry = ctk.CTkEntry(row5, height=26, fg_color=ENTRY_BG, text_color="white")
        addr_entry.pack(anchor="w", fill="x")
        fields["address"] = addr_entry

        # ========== SECTION 3: Financial & Guarantor ==========
        sec3 = ctk.CTkFrame(card, fg_color="transparent")
        sec3.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(sec3, text="Financial & Guarantor", font=("Segoe UI", 13, "bold"), text_color=BLUE_LIGHT).pack(anchor="w")
        ctk.CTkFrame(sec3, height=2, fg_color=NAVY_BORDER).pack(fill="x", pady=(2, 4))

        row6 = ctk.CTkFrame(sec3, fg_color="transparent")
        row6.pack(fill="x", pady=2)
        row6.columnconfigure(0, weight=1, pad=4)
        row6.columnconfigure(1, weight=1, pad=4)

        # Average Income
        inc_frame = ctk.CTkFrame(row6, fg_color="transparent")
        inc_frame.grid(row=0, column=0, sticky="nsew")
        ctk.CTkLabel(inc_frame, text="AVERAGE INCOME", font=("Segoe UI", 9, "bold"), text_color=TEXT_MUTED).pack(anchor="w")
        inc_entry = ctk.CTkEntry(inc_frame, height=26, fg_color=ENTRY_BG, text_color="white")
        inc_entry.pack(anchor="w", fill="x")
        fields["average_income"] = inc_entry

        # Guarantor Name
        guar_frame = ctk.CTkFrame(row6, fg_color="transparent")
        guar_frame.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        ctk.CTkLabel(guar_frame, text="GUARANTOR NAME", font=("Segoe UI", 9, "bold"), text_color=TEXT_MUTED).pack(anchor="w")
        guar_entry = ctk.CTkEntry(guar_frame, height=26, fg_color=ENTRY_BG, text_color="white")
        guar_entry.pack(anchor="w", fill="x")
        fields["guarantor"] = guar_entry

        row7 = ctk.CTkFrame(sec3, fg_color="transparent")
        row7.pack(fill="x", pady=2)
        row7.columnconfigure(0, weight=1, pad=4)
        row7.columnconfigure(1, weight=1, pad=4)

        # Guarantor Phone
        gphone_frame = ctk.CTkFrame(row7, fg_color="transparent")
        gphone_frame.grid(row=0, column=0, sticky="nsew")
        ctk.CTkLabel(gphone_frame, text="GUARANTOR PHONE", font=("Segoe UI", 9, "bold"), text_color=TEXT_MUTED).pack(anchor="w")
        gphone_entry = ctk.CTkEntry(gphone_frame, height=26, fg_color=ENTRY_BG, text_color="white")
        gphone_entry.pack(anchor="w", fill="x")
        fields["guarantor_phone"] = gphone_entry

        # Notes (full width)
        row8 = ctk.CTkFrame(sec3, fg_color="transparent")
        row8.pack(fill="x", pady=2)
        ctk.CTkLabel(row8, text="NOTES", font=("Segoe UI", 9, "bold"), text_color=TEXT_MUTED).pack(anchor="w")
        notes_text = ctk.CTkTextbox(row8, height=60, fg_color=ENTRY_BG, text_color="white")
        notes_text.pack(anchor="w", fill="x")
        fields["notes"] = notes_text

        # ---- Populate if editing ----
        if client:
            fname_entry.insert(0, client["first_name"] or "")
            lname_entry.insert(0, client["last_name"] or "")
            nid_entry.insert(0, client["national_id"] or "")
            gender_combo.set(client["gender"] or "Male")
            occ_entry.insert(0, client["occupation"] or "")
            phone_entry.insert(0, client["phone"] or "")
            current_loc = client["location"] or ""
            if current_loc and current_loc not in location_options:
                location_options = location_options + [current_loc]
                loc_combo.configure(values=location_options)
            loc_combo.set(current_loc)
            addr_entry.insert(0, client["address"] or "")
            inc_entry.insert(0, money_edit_str(client["average_income"]) if client["average_income"] else "")
            guar_entry.insert(0, client["guarantor"] or "")
            gphone_entry.insert(0, client["guarantor_phone"] or "")
            if client["notes"]:
                notes_text.insert("1.0", client["notes"])

        # ---- Buttons ----
        btn_frame = ctk.CTkFrame(card, fg_color="transparent")
        btn_frame.pack(fill="x", pady=(12, 6))
        ctk.CTkButton(btn_frame, text="Cancel", fg_color="gray40", height=30, width=100,
                    command=win.destroy).pack(side="right", padx=6)
        ctk.CTkButton(btn_frame, text="Save Client", fg_color="#2D9CDB", height=30, width=120,
                    font=("Segoe UI", 12, "bold"),
                    command=lambda: self._submit_client(win, fields, client, title)).pack(side="right")


    
    def _submit_client(self, win, fields, client, title):
        """Gather values, validate, and save."""
        try:
            values = {}
            values["first_name"] = fields["first_name"].get().strip()
            values["last_name"] = fields["last_name"].get().strip()
            values["national_id"] = fields["national_id"].get().strip()
            values["gender"] = fields["gender"].get()
            values["occupation"] = fields["occupation"].get().strip()
            values["phone"] = fields["phone"].get().strip()
            values["location"] = fields["location"].get().strip()
            values["address"] = fields["address"].get().strip()
            inc_str = fields["average_income"].get().strip()
            values["average_income"] = parse_money(inc_str) if inc_str else None
            values["guarantor"] = fields["guarantor"].get().strip()
            values["guarantor_phone"] = fields["guarantor_phone"].get().strip()
            values["notes"] = fields["notes"].get("1.0", "end").strip()

            if not values["first_name"] or not values["last_name"]:
                raise ValueError("First name and surname are required.")

            if client:
                # For edit, we also need to handle the 'status' field, but we didn't include it in the dialog.
                # We'll keep the original status unchanged (or we can add a status dropdown in the dialog).
                # For now, we'll not update status via this dialog; we can add it later.
                client_model.update_client(self.conn, client["id"], values)
                info("Client updated.")
            else:
                client_model.create_client(self.conn, values, Session.current_user["id"])
                info("Client registered successfully.")

            win.destroy()
            self.refresh()
        except Exception as e:
            error(str(e))

    # ---- Override _new_client and _edit_client ----
    def _new_client(self):
        self._client_dialog("New Client")

    def _edit_client(self):
        if not perm_model.has_permission(self.conn, Session.current_user, "Clients", "edit"):
            error("You do not have permission to edit clients.")
            return
        row = self.table.selected_row()
        if not row:
            error("Select a client first.")
            return
        client = client_model.get_client(self.conn, int(row["id"]))
        self._client_dialog(f"Edit {client['first_name']} {client['last_name']}", client)
            
# =====================================================================
# LOANS  (list, approvals, new loan, disburse, repayment, statement)
# =====================================================================


# Make sure you have your models imported at the top of your file, e.g.:
# from models import loans as loan_model, clients as client_model, disbursements as disb_model, repayments as repay_model

class LoansView(BaseView):
    # Tab keys carry their icon so CTkTabview needs no extra "text" hack -
    # the icon+label combo IS the tab key, referenced consistently below.
    TAB_ALL_LOANS = "📋  All Loans"
    TAB_APPROVALS = "✔  Approvals"
    TAB_NEW_LOAN = "＋  New Loan"
    TAB_REPAYMENT = "💵  Record Repayment"
    TAB_STATEMENT = "📄  Loan Statement"
    TAB_AMORTISATION = "📊  Amortisation Schedule"

    def __init__(self, master, conn, app):
        super().__init__(master, conn, app)
        self.header("Loan Management")

        self.tabs = ctk.CTkTabview(
            self,
            corner_radius=12,
            border_width=1,
            border_color=NAVY_BORDER,
            fg_color=NAVY_DEEP,
            segmented_button_fg_color=NAVY_MID,
            segmented_button_selected_color=BLUE_ACCENT,
            segmented_button_selected_hover_color=BLUE_HOVER,
            segmented_button_unselected_color=NAVY_MID,
            segmented_button_unselected_hover_color=NAVY_BORDER,
            text_color=TEXT_PRIMARY,
        )
        self.tabs.pack(fill="both", expand=True, padx=15, pady=(0, 15))

        # Give the tab buttons themselves more presence - taller, bolder,
        # a bit of letter-spacing via padding - instead of the default
        # thin/small segmented-button look.
        try:
            self.tabs._segmented_button.configure(
                font=("Segoe UI", 13, "bold"), height=40, corner_radius=8,
            )
            for btn in self.tabs._segmented_button._buttons_dict.values():
                btn.configure(corner_radius=8)
        except Exception:
            pass  # Cosmetic only - never let a customtkinter internals shift break the view.

        tab_builders = [
            (self.TAB_ALL_LOANS, self._build_all_loans),
            (self.TAB_APPROVALS, self._build_approvals),
            (self.TAB_NEW_LOAN, self._build_new_loan),
            (self.TAB_REPAYMENT, self._build_repayment),
            (self.TAB_STATEMENT, self._build_statement),
            (self.TAB_AMORTISATION, self._build_amortisation_schedule),
        ]
        for name, _ in tab_builders:
            self.tabs.add(name)
        for name, builder in tab_builders:
            builder(self.tabs.tab(name))
        # ==========================================
        # HELPER: Control Bars & Cards
    # ==========================================
    def _create_control_bar(self, parent):
        bar = ctk.CTkFrame(parent, fg_color=("gray85", "gray20"), corner_radius=8)
        bar.pack(fill="x", pady=(0, 15), ipadx=10, ipady=10)
        return bar

    # ==========================================
    # TAB 1: ALL LOANS
    # ==========================================
    def _build_all_loans(self, tab):
        bar = self._create_control_bar(tab)

        ctk.CTkLabel(bar, text="Filter Status:", font=("Segoe UI", 12, "bold")).pack(side="left", padx=(10, 5))
        self.status_filter = ctk.CTkComboBox(
            bar, values=["All", "Pending", "Active", "Closed", "RolledOver", "BadDebt", "Rejected"],
            command=lambda _: self._refresh_loans(), width=140
        )
        self.status_filter.set("All")
        self.status_filter.pack(side="left")

        ctk.CTkButton(bar, text="Refresh List", command=self._refresh_loans, width=100).pack(side="left", padx=15)
        ctk.CTkFrame(bar, width=2, height=20, fg_color="gray50").pack(side="left", padx=10)

        ctk.CTkButton(bar, text="✎ Edit", fg_color="#2D9CDB", width=80,
                    command=lambda: self._edit_loan_row(self.loans_table)).pack(side="left", padx=5)

        # ---- Unified Delete Selected (single or multiple) ----
        ctk.CTkButton(bar, text="🗑 Delete Selected", fg_color="#EB5757", hover_color="#C0392B",
                    width=120, command=self._delete_selected_loans).pack(side="left", padx=5)

        self.loans_table = DataTable(tab, columns=[
            ("loan_no", "Loan #"),
            ("client_no", "Client No."),
            ("client_name", "Client"),
            ("location", "Location"),
            ("phone", "Contact"),
            ("principal", "Principal"),
            ("interest_method", "Method"),
            ("term_months", "Term"),
            ("approval_status", "Approval"),
            ("status", "Status"),
            ("disbursement_date", "Disbursed")
        ])
        self.loans_table.pack(fill="both", expand=True)
        self._refresh_loans()

    def _refresh_loans(self):
        status = self.status_filter.get()
        rows = loan_model.list_loans(self.conn, status=None if status == "All" else status)
        self.loans_table.set_rows([{
            "id": l["id"],
            "loan_no": l["loan_no"],
            "client_no": l["client_no"],
            "client_name": f"{l['first_name']} {l['last_name']}",
            "location": l["location"] or "",
            "phone": l["phone"] or "",
            "principal": money(l["principal"]),
            "interest_method": l["interest_method"].replace("_", " ").title(),
            "term_months": l["term_months"],
            "approval_status": status_label(l["approval_status"]),
            "status": status_label(l["status"]),
            "disbursement_date": l["disbursement_date"] or "-"
        } for l in rows])

    # ==========================================
    # TAB 2: APPROVALS (Approve, Decline, Edit, Delete)
    # ==========================================
    def _build_approvals(self, tab):
        bar = self._create_control_bar(tab)

        # Approve Selected – works for any number of selected loans
        ctk.CTkButton(bar, text="✔ Approve Selected", fg_color="#27AE60", hover_color="#219653",
                    font=("Segoe UI", 13, "bold"), command=self._approve_selected_loans).pack(side="left", padx=(10, 5))
        # Decline Selected – also batch
        ctk.CTkButton(bar, text="✖ Decline Selected", fg_color="#EB5757", hover_color="#C0392B",
                    font=("Segoe UI", 13, "bold"), command=self._decline_selected_loans).pack(side="left", padx=5)

        ctk.CTkFrame(bar, width=2, height=20, fg_color="gray50").pack(side="left", padx=10)

        ctk.CTkButton(bar, text="✎ Edit", fg_color="#2D9CDB", command=lambda: self._edit_loan_row(self.approvals_table), width=80).pack(side="left", padx=5)
        ctk.CTkButton(bar, text="🗑 Delete", fg_color="gray40", hover_color="gray20", command=lambda: self._delete_loan_row(self.approvals_table), width=80).pack(side="left", padx=5)

        ctk.CTkButton(bar, text="Refresh", command=self._refresh_approvals, width=80).pack(side="right", padx=10)

        self.approvals_table = DataTable(tab, columns=[
            ("loan_no", "Loan #"),
            ("client_no", "Client No."),
            ("client_name", "Client"),
            ("location", "Location"),
            ("type", "Type"),
            ("principal", "Principal"),
            ("interest_rate", "Rate %"),
            ("interest_method", "Method"),
            ("term_months", "Term"),
            ("purpose", "Purpose"),
            ("application_date", "Applied On")
        ])
        self.approvals_table.pack(fill="both", expand=True)
        self._refresh_approvals()

    def _pending_rollover_for_loan(self, loan_id):
        return rollover_model.pending_rollover_for_loan(self.conn, loan_id)

    def _refresh_approvals(self):
        rows = loan_model.list_loans(self.conn, approval_status="Pending")
        rows = [r for r in rows if r["status"] == "Pending"]
        self.approvals_table.set_rows([{
            "id": l["id"], "loan_no": l["loan_no"], "client_name": f"{l['first_name']} {l['last_name']}",
            "location": l["location"] or "", "principal": money(l["principal"]),
            "type": "🔁 Rollover" if l["parent_loan_id"] else "🆕 New Loan",
            "interest_rate": l["interest_rate"], "interest_method": l["interest_method"].replace("_", " ").title(),
            "term_months": l["term_months"], "purpose": l["purpose"] or "",
            "application_date": l["application_date"]
        } for l in rows])

    def _decide_approval(self, new_status):
        if not perm_model.has_permission(self.conn, Session.current_user, "Loans", "approve"):
            return error("You do not have permission to approve/decline loans.")
        row = self.approvals_table.selected_row()
        if not row:
            return error("Select a loan awaiting approval first.")

        loan_id = int(row["id"])
        rollover = self._pending_rollover_for_loan(loan_id)
        if rollover and not perm_model.has_permission(self.conn, Session.current_user, "Rollovers", "approve"):
            return error("You do not have permission to approve/decline rollovers.")

        if new_status == "Declined":
            if not confirm(f"Decline {'rollover request' if rollover else 'loan'} {row['loan_no']}?"):
                return
            try:
                if rollover:
                    rollover_model.reject_rollover(self.conn, rollover["id"],
                                                    rejected_by=Session.current_user["id"])
                    info(f"Rollover request for {row['loan_no']} declined. Original loan remains Active.")
                else:
                    loan_model.set_approval_status(self.conn, loan_id, "Declined",
                                                approved_by=Session.current_user["id"])
                    info(f"Loan {row['loan_no']} declined.")
                self._refresh_approvals()
                self._refresh_loans()
            except Exception as e:
                error(str(e))
            return

        loan = loan_model.get_loan(self.conn, loan_id)
        if not loan:
            return error("Loan not found.")

        from datetime import date

        if rollover:
            # The date entered here - not anything chosen on the request
            # form - becomes the official rollover date.
            fields = [{
                "key": "rollover_date", "label": "Rollover Date", "type": "date",
                "default": date.today().isoformat(),
            }]

            def approve_and_disburse(values):
                try:
                    result = rollover_model.approve_rollover(
                        self.conn, rollover["id"],
                        approved_by=Session.current_user["id"],
                        approval_date=values["rollover_date"],
                    )
                    fee_note = (f" Rollover fee {money(result['rollover_fee_amount'])} charged."
                                if result["rollover_fee_amount"] else "")
                    info(f"Rollover approved - loan {row['loan_no']} disbursed on "
                        f"{result['rollover_date']}.{fee_note}")
                    self._refresh_approvals()
                    self._refresh_loans()
                    self._refresh_repayment_list()
                    self._refresh_statement_list()
                    self._refresh_amortisation_list()
                except Exception as e:
                    error(str(e))

            FormDialog(self, f"Approve Rollover - {row['loan_no']}", fields, approve_and_disburse, height=130)
            return

        fields = []
        # If no disbursement date is set, ask for it
        if not loan["disbursement_date"]:
            fields.append({
                "key": "disbursement_date",
                "label": "Disbursement Date",
                "type": "date",
                "default": date.today().isoformat()
            })
        # Always ask for method
        fields.append({
            "key": "method",
            "label": "Method",
            "type": "combobox",
            "options": ["Cash", "Bank Transfer", "Mobile Money"],
            "default": "Cash"
        })
        fields.append({
            "key": "reference",
            "label": "Reference",
        })

        def approve_and_disburse(values):
            try:
                # Use the date from the loan (if set) or from the form
                disbursement_date = values.get("disbursement_date") or loan["disbursement_date"]
                if not disbursement_date:
                    raise ValueError("Disbursement date is required.")

                loan_model.set_approval_status(self.conn, loan_id, "Approved",
                                            approved_by=Session.current_user["id"])
                disb_model.disburse_loan(
                    self.conn,
                    loan_id=loan_id,
                    amount=loan["principal"],
                    disbursement_date=disbursement_date,
                    method=values["method"],
                    first_due_date=None,
                    reference=(values.get("reference") or "").strip() or None,
                    user_id=Session.current_user["id"],
                )
                info(f"Loan {row['loan_no']} approved and disbursed successfully.")
                self._refresh_approvals()
                self._refresh_loans()
                self._refresh_repayment_list()
                self._refresh_statement_list()
                self._refresh_amortisation_list()
            except Exception as e:
                error(str(e))

        height = 160 if len(fields) == 2 else 130
        FormDialog(self, f"Approve and Disburse {row['loan_no']}", fields, approve_and_disburse, height=height)


    def _edit_loan_row(self, table):
        if not perm_model.has_permission(self.conn, Session.current_user, "Loans", "edit"):
            return error("You do not have permission to edit loans.")
        row = table.selected_row()
        if not row:
            return error("Select a loan first.")
        try:
            loan = loan_model.get_loan(self.conn, int(row["id"]))
            if not loan:
                return error("Loan not found.")
            
            is_disbursed = loan["disbursement_date"] is not None

            # ---- Get current application fee ----
            fee_row = self.conn.execute(
                "SELECT amount FROM fees WHERE loan_id = ? AND fee_type = 'Application'",
                (loan["id"],)
            ).fetchone()
            current_app_fee = fee_row["amount"] if fee_row else 0.0

            # ==========================================
            # CUSTOM EDIT WINDOW (Mimicking New Loan UI)
            # ==========================================
            win = ctk.CTkToplevel(self)
            win.title(f"Edit Loan {loan['loan_no']}")
            win.geometry("750x650")
            win.resizable(False, True)
            win.transient(self.winfo_toplevel())
            win.grab_set()
            win.configure(fg_color=NAVY_DEEP)

            scroll = ctk.CTkScrollableFrame(win, fg_color="transparent")
            scroll.pack(fill="both", expand=True, padx=16, pady=16)

            card = ctk.CTkFrame(scroll, fg_color=("gray95", "gray15"), corner_radius=8)
            card.pack(fill="both", expand=True)

            # ---- Title ----
            toolbar = ctk.CTkFrame(card, fg_color="transparent")
            toolbar.pack(fill="x", pady=(10, 10), padx=10)
            ctk.CTkLabel(toolbar, text=f"Edit Loan Terms - {loan['loan_no']}", font=("Segoe UI", 17, "bold")).pack(side="left")

            # ========== SECTION 1: Dark Amber (Primary Terms) ==========
            sec1 = ctk.CTkFrame(card, fg_color="transparent")
            sec1.pack(fill="x", padx=10, pady=(0, 10))
            ctk.CTkLabel(sec1, text="Primary Loan Terms", font=("Segoe UI", 11, "bold"), text_color=BLUE_LIGHT).pack(anchor="w")
            ctk.CTkFrame(sec1, height=2, fg_color=NAVY_BORDER).pack(fill="x", pady=(2, 3))

            row1 = ctk.CTkFrame(sec1, fg_color="transparent")
            row1.pack(fill="x", pady=2)
            row1.columnconfigure(0, weight=1, pad=4)
            row1.columnconfigure(1, weight=1, pad=4)

            princ_frame = ctk.CTkFrame(row1, fg_color="transparent")
            princ_frame.grid(row=0, column=0, sticky="nsew")
            ctk.CTkLabel(princ_frame, text="PRINCIPAL*", font=("Segoe UI", 9, "bold"), text_color=TEXT_MUTED).pack(anchor="w")
            nl_principal = ctk.CTkEntry(princ_frame, height=26, fg_color="#5C3A1A", text_color="white")
            nl_principal.insert(0, money_edit_str(loan["principal"]))
            nl_principal.pack(anchor="w", fill="x")
            enable_quick_math(nl_principal)

            rate_frame = ctk.CTkFrame(row1, fg_color="transparent")
            rate_frame.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
            ctk.CTkLabel(rate_frame, text="INTEREST RATE (%)*", font=("Segoe UI", 9, "bold"), text_color=TEXT_MUTED).pack(anchor="w")
            nl_rate = ctk.CTkEntry(rate_frame, height=26, fg_color="#5C3A1A", text_color="white")
            nl_rate.insert(0, str(loan["interest_rate"]))
            nl_rate.pack(anchor="w", fill="x")

            row2 = ctk.CTkFrame(sec1, fg_color="transparent")
            row2.pack(fill="x", pady=2)
            row2.columnconfigure(0, weight=1, pad=4)
            row2.columnconfigure(1, weight=1, pad=4)
            row2.columnconfigure(2, weight=1, pad=4)

            method_frame = ctk.CTkFrame(row2, fg_color="transparent")
            method_frame.grid(row=0, column=0, sticky="nsew")
            ctk.CTkLabel(method_frame, text="INTEREST METHOD*", font=("Segoe UI", 9, "bold"), text_color=TEXT_MUTED).pack(anchor="w")
            nl_method = ctk.CTkComboBox(method_frame, values=["flat", "reducing_balance", "interest_only_balloon", "interest_only_then_flat"], height=26, fg_color="#5C3A1A", button_color=NAVY_BORDER, text_color="white")
            nl_method.set(loan["interest_method"])
            nl_method.pack(anchor="w", fill="x")

            freq_frame = ctk.CTkFrame(row2, fg_color="transparent")
            freq_frame.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
            ctk.CTkLabel(freq_frame, text="FREQUENCY", font=("Segoe UI", 9, "bold"), text_color=TEXT_MUTED).pack(anchor="w")
            nl_freq = ctk.CTkComboBox(freq_frame, values=["monthly", "biweekly", "weekly"], height=26, fg_color="#5C3A1A", button_color=NAVY_BORDER, text_color="white")
            nl_freq.set(loan["repayment_frequency"])
            nl_freq.pack(anchor="w", fill="x")

            term_frame = ctk.CTkFrame(row2, fg_color="transparent")
            term_frame.grid(row=0, column=2, sticky="nsew", padx=(8, 0))
            ctk.CTkLabel(term_frame, text="TERM (PERIODS)*", font=("Segoe UI", 9, "bold"), text_color=TEXT_MUTED).pack(anchor="w")
            nl_term = ctk.CTkEntry(term_frame, height=26, fg_color="#5C3A1A", text_color="white")
            nl_term.insert(0, str(loan["term_months"]))
            nl_term.pack(anchor="w", fill="x")

            # ========== SECTION 2: Dark Teal (Phase 2 & Fees) ==========
            sec2 = ctk.CTkFrame(card, fg_color="transparent")
            sec2.pack(fill="x", padx=10, pady=(0, 10))
            ctk.CTkLabel(sec2, text="Phase 2 & Fees", font=("Segoe UI", 11, "bold"), text_color=BLUE_LIGHT).pack(anchor="w")
            ctk.CTkFrame(sec2, height=2, fg_color=NAVY_BORDER).pack(fill="x", pady=(2, 3))

            row3 = ctk.CTkFrame(sec2, fg_color="transparent")
            row3.pack(fill="x", pady=2)
            row3.columnconfigure(0, weight=1, pad=4)
            row3.columnconfigure(1, weight=1, pad=4)

            p2freq_frame = ctk.CTkFrame(row3, fg_color="transparent")
            p2freq_frame.grid(row=0, column=0, sticky="nsew")
            ctk.CTkLabel(p2freq_frame, text="PHASE 2 FREQUENCY", font=("Segoe UI", 9, "bold"), text_color=TEXT_MUTED).pack(anchor="w")
            nl_phase2_freq = ctk.CTkComboBox(p2freq_frame, values=["monthly", "biweekly", "weekly"], height=26, fg_color="#1A5C3A", button_color=NAVY_BORDER, text_color="white")
            nl_phase2_freq.set(loan["phase2_frequency"] or "biweekly")
            nl_phase2_freq.pack(anchor="w", fill="x")

            p2term_frame = ctk.CTkFrame(row3, fg_color="transparent")
            p2term_frame.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
            ctk.CTkLabel(p2term_frame, text="PHASE 2 TERM (PERIODS)", font=("Segoe UI", 9, "bold"), text_color=TEXT_MUTED).pack(anchor="w")
            nl_phase2_term = ctk.CTkEntry(p2term_frame, height=26, fg_color="#1A5C3A", text_color="white")
            if loan["phase2_term_months"]:
                nl_phase2_term.insert(0, str(loan["phase2_term_months"]))
            nl_phase2_term.pack(anchor="w", fill="x")

            row4 = ctk.CTkFrame(sec2, fg_color="transparent")
            row4.pack(fill="x", pady=2)
            row4.columnconfigure(0, weight=1, pad=4)
            row4.columnconfigure(1, weight=1, pad=4)
            
            admin_frame = ctk.CTkFrame(row4, fg_color="transparent")
            admin_frame.grid(row=0, column=0, sticky="nsew")
            ctk.CTkLabel(admin_frame, text="ADMIN FEE", font=("Segoe UI", 9, "bold"), text_color=TEXT_MUTED).pack(anchor="w")
            nl_admin_fee = ctk.CTkEntry(admin_frame, height=26, fg_color="#1A5C3A", text_color="white")
            nl_admin_fee.insert(0, money_edit_str(loan["admin_fee"]))
            nl_admin_fee.pack(anchor="w", fill="x")
            enable_quick_math(nl_admin_fee)

            app_frame = ctk.CTkFrame(row4, fg_color="transparent")
            app_frame.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
            ctk.CTkLabel(app_frame, text="APPLICATION FEE", font=("Segoe UI", 9, "bold"), text_color=TEXT_MUTED).pack(anchor="w")
            nl_app_fee = ctk.CTkEntry(app_frame, height=26, fg_color="#1A5C3A", text_color="white")
            nl_app_fee.insert(0, str(current_app_fee))
            nl_app_fee.pack(anchor="w", fill="x")
            enable_quick_math(nl_app_fee)

            # ========== SECTION 3: Dark Navy (Details & Dates) ==========
            sec3 = ctk.CTkFrame(card, fg_color="transparent")
            sec3.pack(fill="x", padx=10, pady=(0, 10))
            ctk.CTkLabel(sec3, text="Details & Disbursement", font=("Segoe UI", 11, "bold"), text_color=BLUE_LIGHT).pack(anchor="w")
            ctk.CTkFrame(sec3, height=2, fg_color=NAVY_BORDER).pack(fill="x", pady=(2, 3))

            row5 = ctk.CTkFrame(sec3, fg_color="transparent")
            row5.pack(fill="x", pady=2)
            row5.columnconfigure(0, weight=1, pad=4)
            row5.columnconfigure(1, weight=1, pad=4)

            purpose_frame = ctk.CTkFrame(row5, fg_color="transparent")
            purpose_frame.grid(row=0, column=0, sticky="nsew")
            ctk.CTkLabel(purpose_frame, text="PURPOSE", font=("Segoe UI", 9, "bold"), text_color=TEXT_MUTED).pack(anchor="w")
            nl_purpose = ctk.CTkEntry(purpose_frame, height=26, fg_color="#1A3B5C", text_color="white")
            if loan["purpose"]: nl_purpose.insert(0, loan["purpose"])
            nl_purpose.pack(anchor="w", fill="x")

            collat_frame = ctk.CTkFrame(row5, fg_color="transparent")
            collat_frame.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
            ctk.CTkLabel(collat_frame, text="COLLATERAL", font=("Segoe UI", 9, "bold"), text_color=TEXT_MUTED).pack(anchor="w")
            nl_collat = ctk.CTkEntry(collat_frame, height=26, fg_color="#1A3B5C", text_color="white")
            if loan["collateral"]: nl_collat.insert(0, loan["collateral"])
            nl_collat.pack(anchor="w", fill="x")

            nl_due_date = None
            if is_disbursed:
                row6 = ctk.CTkFrame(sec3, fg_color="transparent")
                row6.pack(fill="x", pady=2)
                row6.columnconfigure(0, weight=1, pad=4)

                date_frame = ctk.CTkFrame(row6, fg_color="transparent")
                date_frame.grid(row=0, column=0, sticky="nsew")
                ctk.CTkLabel(date_frame, text="DISBURSEMENT DATE", font=("Segoe UI", 9, "bold"), text_color=TEXT_MUTED).pack(anchor="w")
                nl_due_date = DatePicker(date_frame, width=200, default=loan["disbursement_date"])
                nl_due_date.pack(anchor="w", fill="x")

            # ========== ACTION BUTTONS ==========
            btn_frame = ctk.CTkFrame(card, fg_color="transparent")
            btn_frame.pack(fill="x", padx=10, pady=(12, 10))

            def submit_form():
                values = {
                    "principal": nl_principal.get().strip(),
                    "interest_rate": nl_rate.get().strip(),
                    "interest_method": nl_method.get(),
                    "term_months": nl_term.get().strip(),
                    "repayment_frequency": nl_freq.get(),
                    "phase2_term_months": nl_phase2_term.get().strip(),
                    "phase2_frequency": nl_phase2_freq.get(),
                    "admin_fee": nl_admin_fee.get().strip(),
                    "application_fee": nl_app_fee.get().strip(),
                    "purpose": nl_purpose.get().strip(),
                    "collateral": nl_collat.get().strip(),
                }
                
                if is_disbursed and nl_due_date:
                    values["disbursement_date"] = nl_due_date.get()

                # --- Original Core Submission Logic ---
                try:
                    values["principal"] = parse_money(values["principal"])
                    values["interest_rate"] = float(values["interest_rate"])
                    values["term_months"] = int(values["term_months"])
                    values["admin_fee"] = parse_money(values["admin_fee"] or 0)
                    values["application_fee"] = parse_money(values["application_fee"] or 0)
                    if values["interest_method"] == "interest_only_then_flat":
                        if not str(values.get("phase2_term_months") or "").strip():
                            raise ValueError("Phase 2 Term (periods) is required for interest_only_then_flat.")
                        values["phase2_term_months"] = int(values["phase2_term_months"])
                        values["rate_period"] = "loan_term"
                    else:
                        values.pop("phase2_term_months", None)
                        values.pop("phase2_frequency", None)
                except ValueError as e:
                    if "Phase 2" in str(e):
                        error(str(e))
                        return
                    error("Please enter valid numbers for Principal, Rate, Term, Admin Fee, and Application Fee.")
                    return

                if is_disbursed:
                    if not confirm(
                        "This loan has already been disbursed.\n\n"
                        "Editing a disbursed loan will recalculate the entire amortisation schedule and reapply all repayments. "
                        "This may change the outstanding balance and future payment amounts.\n\n"
                        "The application fee will also be updated along with its journal entry.\n\n"
                        "Are you sure you want to proceed?"
                    ):
                        return
                    loan_model.rebuild_schedule_and_reapply_repayments(self.conn, loan["id"], values)
                    info(f"Loan {loan['loan_no']} updated. Schedule recalculated and repayments reapplied.")
                else:
                    loan_model.update_loan(self.conn, loan["id"], values)
                    info(f"Loan {loan['loan_no']} updated.")

                # ---- Update application fee ----
                if values["application_fee"] != current_app_fee:
                    from ..models import fees as fee_model
                    fee_model.update_application_fee_and_journal(
                        self.conn, loan["id"], values["application_fee"],
                        user_id=Session.current_user["id"]
                    )
                    info(f"Application fee updated to {values['application_fee']} and journal adjusted.")

                self._refresh_loans()
                self._refresh_approvals()
                self._refresh_repayment_list()
                self._refresh_statement_list()
                self._refresh_amortisation_list()
                
                win.destroy()

            ctk.CTkButton(btn_frame, text="Cancel", fg_color="gray40", height=30, width=100,
                          command=win.destroy).pack(side="right", padx=6)
            ctk.CTkButton(btn_frame, text="Save Changes", fg_color="#2D9CDB", font=("Segoe UI", 12, "bold"),
                          height=30, width=120, command=submit_form).pack(side="right")

        except Exception as e:
            error(str(e))

    def _delete_loan_row(self, table):
        if not perm_model.has_permission(self.conn, Session.current_user, "Loans", "delete"):
            return error("You do not have permission to delete loans.")
        row = table.selected_row()
        if not row: return error("Select a loan first.")
        if not confirm(f"Permanently delete loan {row['loan_no']}? This cannot be undone."): return
        try:
            loan_model.delete_loan(self.conn, int(row["id"]))
            info(f"Loan {row['loan_no']} deleted.")
            self._refresh_approvals(); self._refresh_loans()
        except Exception as e: error(str(e))

    # ==========================================
    # TAB 3: NEW LOAN
    # ==========================================
    def _build_new_loan(self, tab):
        # ---- Lookups ----
        clients = client_model.list_clients(self.conn, status="Active")
        self.client_lookup = {f"{c['client_no']} - {c['first_name']} {c['last_name']}": c["id"] for c in clients}
        products = self.conn.execute("SELECT * FROM loan_products WHERE active=1").fetchall()
        self.product_lookup = {p["name"]: p for p in products}

        # Scrollable container
        scroll = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        scroll.pack(fill="both", expand=True)

        # Main card
        card = ctk.CTkFrame(scroll, fg_color=("gray95", "gray15"), corner_radius=8)
        card.pack(padx=10, pady=10, fill="both", expand=True)

        # ---- Title and Bulk Upload toolbar ----
        toolbar = ctk.CTkFrame(card, fg_color="transparent")
        toolbar.pack(fill="x", pady=(4, 6))
        ctk.CTkLabel(toolbar, text="New Loan Application", font=("Segoe UI", 17, "bold")).pack(side="left")

        bulk_buttons = ctk.CTkFrame(toolbar, fg_color="transparent")
        bulk_buttons.pack(side="right")
        ctk.CTkButton(bulk_buttons, text="Download Template", fg_color="gray40", height=26, width=130,
                    command=self._download_loan_template).pack(side="left", padx=(0, 6))
        ctk.CTkButton(bulk_buttons, text="Bulk Upload Loans", fg_color="#27AE60", height=26, width=130,
                    font=("Segoe UI", 11, "bold"), command=self._bulk_upload_loans).pack(side="left")

        # All three sections below share ONE field background color so the
        # form reads as one coherent application instead of three
        # differently-tinted zones. Sections are distinguished by their
        # own bordered card + icon header instead of by field color.
        FIELD_BG = "#132A45"

        def _section_card(title, icon):
            wrap = ctk.CTkFrame(card, fg_color=NAVY_MID, corner_radius=10,
                                 border_width=1, border_color=NAVY_BORDER)
            wrap.pack(fill="x", pady=(0, 10), padx=2)
            inner = ctk.CTkFrame(wrap, fg_color="transparent")
            inner.pack(fill="x", padx=14, pady=(10, 12))
            ctk.CTkLabel(inner, text=f"{icon}  {title}", font=("Segoe UI", 12, "bold"),
                         text_color=BLUE_LIGHT).pack(anchor="w")
            ctk.CTkFrame(inner, height=1, fg_color=NAVY_BORDER).pack(fill="x", pady=(4, 8))
            return inner

        # ========== SECTION 1: Applicant & Product ==========
        sec1 = _section_card("Applicant & Product Setup", "👤")

        row1 = ctk.CTkFrame(sec1, fg_color="transparent")
        row1.pack(fill="x", pady=1)
        row1.columnconfigure(0, weight=1, pad=4)
        row1.columnconfigure(1, weight=1, pad=4)

        client_frame = ctk.CTkFrame(row1, fg_color="transparent")
        client_frame.grid(row=0, column=0, sticky="nsew")
        ctk.CTkLabel(client_frame, text="CLIENT", font=("Segoe UI", 9, "bold"), text_color=TEXT_MUTED).pack(anchor="w")
        self.nl_client = SearchableCombobox(client_frame, values=list(self.client_lookup.keys()), width=300,
                                             command=self._on_client_selected)
        if hasattr(self.nl_client, 'entry'):
            self.nl_client.entry.configure(fg_color=FIELD_BG, text_color="white")
        self.nl_client.pack(anchor="w", fill="x")

        product_frame = ctk.CTkFrame(row1, fg_color="transparent")
        product_frame.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        ctk.CTkLabel(product_frame, text="LOAN PRODUCT", font=("Segoe UI", 9, "bold"), text_color=TEXT_MUTED).pack(anchor="w")
        product_values = ["(none - manual terms)"] + list(self.product_lookup.keys())
        self.nl_product = ctk.CTkComboBox(product_frame, values=product_values, width=200, height=26,
                                        fg_color=FIELD_BG, button_color=NAVY_BORDER, text_color="white",
                                        command=self._apply_product_defaults)
        self.nl_product.pack(anchor="w", fill="x")

        # ========== SECTION 2: Primary Loan Terms ==========
        sec2 = _section_card("Primary Loan Terms", "💰")

        row2 = ctk.CTkFrame(sec2, fg_color="transparent")
        row2.pack(fill="x", pady=1)
        row2.columnconfigure(0, weight=1, pad=4)
        row2.columnconfigure(1, weight=1, pad=4)

        princ_frame = ctk.CTkFrame(row2, fg_color="transparent")
        princ_frame.grid(row=0, column=0, sticky="nsew")
        ctk.CTkLabel(princ_frame, text="PRINCIPAL", font=("Segoe UI", 9, "bold"), text_color=TEXT_MUTED).pack(anchor="w")
        self.nl_principal = ctk.CTkEntry(princ_frame, width=200, height=26, fg_color=FIELD_BG, text_color="white")
        self.nl_principal.pack(anchor="w", fill="x")
        enable_quick_math(self.nl_principal)
        # Runs after enable_quick_math's own FocusOut handler (add="+"), so
        # this sees the already-resolved numeric principal.
        self.nl_principal.bind("<FocusOut>", lambda e: self._recompute_fees(), add="+")

        rate_frame = ctk.CTkFrame(row2, fg_color="transparent")
        rate_frame.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        ctk.CTkLabel(rate_frame, text="INTEREST RATE (%)", font=("Segoe UI", 9, "bold"), text_color=TEXT_MUTED).pack(anchor="w")
        self.nl_rate = ctk.CTkEntry(rate_frame, width=200, height=26, fg_color=FIELD_BG, text_color="white")
        self.nl_rate.pack(anchor="w", fill="x")

        row3 = ctk.CTkFrame(sec2, fg_color="transparent")
        row3.pack(fill="x", pady=1)
        row3.columnconfigure(0, weight=1, pad=4)
        row3.columnconfigure(1, weight=1, pad=4)
        row3.columnconfigure(2, weight=1, pad=4)

        method_frame = ctk.CTkFrame(row3, fg_color="transparent")
        method_frame.grid(row=0, column=0, sticky="nsew")
        ctk.CTkLabel(method_frame, text="INTEREST METHOD", font=("Segoe UI", 9, "bold"), text_color=TEXT_MUTED).pack(anchor="w")
        self.nl_method = ctk.CTkComboBox(method_frame, values=["flat", "reducing_balance", "interest_only_balloon", "interest_only_then_flat"],
                                        width=200, height=26, fg_color=FIELD_BG, button_color=NAVY_BORDER, text_color="white")
        self.nl_method.pack(anchor="w", fill="x")

        freq_frame = ctk.CTkFrame(row3, fg_color="transparent")
        freq_frame.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        ctk.CTkLabel(freq_frame, text="FREQUENCY", font=("Segoe UI", 9, "bold"), text_color=TEXT_MUTED).pack(anchor="w")
        self.nl_freq = ctk.CTkComboBox(freq_frame, values=["monthly", "biweekly", "weekly"], width=200, height=26,
                                    fg_color=FIELD_BG, button_color=NAVY_BORDER, text_color="white")
        self.nl_freq.pack(anchor="w", fill="x")

        term_frame = ctk.CTkFrame(row3, fg_color="transparent")
        term_frame.grid(row=0, column=2, sticky="nsew", padx=(8, 0))
        ctk.CTkLabel(term_frame, text="TERM (PERIODS)", font=("Segoe UI", 9, "bold"), text_color=TEXT_MUTED).pack(anchor="w")
        self.nl_term = ctk.CTkEntry(term_frame, width=200, height=26, fg_color=FIELD_BG, text_color="white")
        self.nl_term.pack(anchor="w", fill="x")

        # ========== SECTION 3: Phase 2 & Fees ==========
        sec3 = _section_card("Phase 2 & Fees", "🧾")

        row4 = ctk.CTkFrame(sec3, fg_color="transparent")
        row4.pack(fill="x", pady=1)
        row4.columnconfigure(0, weight=1, pad=4)
        row4.columnconfigure(1, weight=1, pad=4)

        p2freq_frame = ctk.CTkFrame(row4, fg_color="transparent")
        p2freq_frame.grid(row=0, column=0, sticky="nsew")
        ctk.CTkLabel(p2freq_frame, text="PHASE 2 FREQUENCY", font=("Segoe UI", 9, "bold"), text_color=TEXT_MUTED).pack(anchor="w")
        self.nl_phase2_freq = ctk.CTkComboBox(p2freq_frame, values=["monthly", "biweekly", "weekly"], width=200, height=26,
                                            fg_color=FIELD_BG, button_color=NAVY_BORDER, text_color="white")
        self.nl_phase2_freq.pack(anchor="w", fill="x")

        p2term_frame = ctk.CTkFrame(row4, fg_color="transparent")
        p2term_frame.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        ctk.CTkLabel(p2term_frame, text="PHASE 2 TERM (PERIODS)", font=("Segoe UI", 9, "bold"), text_color=TEXT_MUTED).pack(anchor="w")
        self.nl_phase2_term = ctk.CTkEntry(p2term_frame, width=200, height=26, fg_color=FIELD_BG, text_color="white")
        self.nl_phase2_term.pack(anchor="w", fill="x")

        row5 = ctk.CTkFrame(sec3, fg_color="transparent")
        row5.pack(fill="x", pady=1)
        row5.columnconfigure(0, weight=1, pad=4)
        row5.columnconfigure(1, weight=1, pad=4)
        row5.columnconfigure(2, weight=1, pad=4)

        admin_frame = ctk.CTkFrame(row5, fg_color="transparent")
        admin_frame.grid(row=0, column=0, sticky="nsew")
        ctk.CTkLabel(admin_frame, text="ADMIN FEE", font=("Segoe UI", 9, "bold"), text_color=TEXT_MUTED).pack(anchor="w")
        self.nl_admin_fee = ctk.CTkEntry(admin_frame, width=200, height=26, fg_color=FIELD_BG, text_color="white")
        self.nl_admin_fee.pack(anchor="w", fill="x")
        enable_quick_math(self.nl_admin_fee)

        app_frame = ctk.CTkFrame(row5, fg_color="transparent")
        app_frame.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        ctk.CTkLabel(app_frame, text="APPLICATION FEE", font=("Segoe UI", 9, "bold"), text_color=TEXT_MUTED).pack(anchor="w")
        self.nl_app_fee = ctk.CTkEntry(app_frame, width=200, height=26, fg_color=FIELD_BG, text_color="white")
        self.nl_app_fee.pack(anchor="w", fill="x")
        enable_quick_math(self.nl_app_fee)

        date_frame = ctk.CTkFrame(row5, fg_color="transparent")
        date_frame.grid(row=0, column=2, sticky="nsew", padx=(8, 0))
        ctk.CTkLabel(date_frame, text="DISBURSEMENT DATE (optional)", font=("Segoe UI", 9, "bold"), text_color=TEXT_MUTED).pack(anchor="w")
        self.nl_due_date = DatePicker(date_frame, width=200, default="")
        self.nl_due_date.pack(anchor="w", fill="x")

        # ========== SUBMIT BUTTON ==========
        ctk.CTkButton(
            card,
            text="Submit Application",
            font=("Segoe UI", 12, "bold"),
            fg_color="#2D9CDB",
            height=30,
            command=self._create_loan,
        ).pack(pady=(8, 4))

        # ---- Set initial product default ----
        default_product = "(none - manual terms)"
        for p in self.product_lookup.values():
            if "weekly" in p["name"].lower():
                default_product = p["name"]
                break
        self.nl_product.set(default_product)
        if default_product != "(none - manual terms)":
            self._apply_product_defaults(default_product)
                                    
                
    def _apply_rate_preset(self, label):
        if label not in self.rate_preset_lookup:
            return
        self.nl_rate.delete(0, "end")
        self.nl_rate.insert(0, str(self.rate_preset_lookup[label]))

    def _create_loan(self):
        try:
            client_key = self.nl_client.get()
            if client_key not in self.client_lookup:
                raise ValueError("Select a valid client.")
            prod = self.product_lookup.get(self.nl_product.get())
            method = self.nl_method.get()
            data = {
                "client_id": self.client_lookup[client_key],
                "product_id": prod["id"] if prod else None,
                "principal": parse_money(self.nl_principal.get()),
                "interest_rate": float(self.nl_rate.get()),
                "interest_method": method,
                # interest_only_then_flat prices each phase as a lump
                # percentage of principal over that phase's term (matches
                # "flat" + rate_period='loan_term' semantics) - not a
                # per-month or per-year rate - so force it regardless of
                # the product's own rate_period.
                "rate_period": "loan_term" if method == "interest_only_then_flat"
                               else (prod["rate_period"] if prod else "month"),
                "term_months": int(self.nl_term.get()),
                "repayment_frequency": self.nl_freq.get(),
                "admin_fee": parse_money(self.nl_admin_fee.get() or 0),
                "disbursement_date": self.nl_due_date.get().strip() or None,
            }
            if method == "interest_only_then_flat":
                if not self.nl_phase2_term.get().strip():
                    raise ValueError("Phase 2 Term (Periods) is required for the interest-only-then-flat product.")
                data["phase2_term_months"] = int(self.nl_phase2_term.get())
                data["phase2_frequency"] = self.nl_phase2_freq.get()
            new_loan_id = loan_model.create_loan(self.conn, data, Session.current_user["id"])
            app_fee = parse_money(self.nl_app_fee.get() or 0)
            if app_fee > 0:
                fee_model.charge_fee(
                    self.conn, new_loan_id, "Application", app_fee,
                    description="Application fee charged on loan application",
                    mark_paid=True, user_id=Session.current_user["id"],
                )
            info("Loan submitted and is awaiting approval.")
            self._clear_new_loan_form()
            self._refresh_loans()
            self._refresh_approvals()
        except Exception as e:
            error(str(e))
            
    def _delete_selected_loans(self):
        if not perm_model.has_permission(self.conn, Session.current_user, "Loans", "delete"):
            return error("You do not have permission to delete loans.")
        selected = self.loans_table.selected_rows()
        if not selected:
            return error("Select at least one loan first.")

        # Check if any loan is already disbursed or active
        disallowed = []
        for row in selected:
            loan = loan_model.get_loan(self.conn, int(row["id"]))
            if loan and loan["status"] != "Pending":
                disallowed.append(loan["loan_no"])
        if disallowed:
            return error(
                f"The following loans cannot be deleted (already disbursed/active):\n"
                f"{', '.join(disallowed)}\n\n"
                "Only pending loans can be deleted."
            )

        # Confirm deletion
        if not confirm(
            f"Are you sure you want to permanently delete {len(selected)} loan(s)?\n"
            "This action cannot be undone."
        ):
            return

        success, errors = 0, 0
        for row in selected:
            try:
                loan_model.delete_loan(self.conn, int(row["id"]))
                success += 1
            except Exception as e:
                errors += 1
                error(f"Failed to delete loan {row['loan_no']}: {str(e)}")
        info(f"{success} loan(s) deleted successfully." + (f" {errors} failed." if errors else ""))
        self._refresh_loans()
        self._refresh_approvals()



    def create_loan(conn, data, user_id: int = None):
        """
        Create a new loan record.
        Expected keys: client_id, principal, interest_rate, interest_method,
                    term_months, repayment_frequency, admin_fee, purpose,
                    collateral, disbursement_date (optional).
        Returns the new loan id.
        """
        from datetime import date
        # Allowed fields (including the new one)
        allowed_fields = [
            "client_id", "principal", "interest_rate", "interest_method",
            "term_months", "repayment_frequency", "admin_fee", "purpose",
            "collateral", "disbursement_date"   # <-- added
        ]
        fields = []
        placeholders = []
        values = []
        for key in allowed_fields:
            if key in data and data[key] is not None:
                fields.append(key)
                placeholders.append("?")
                values.append(data[key])
        # Always add application_date and created_by
        fields.append("application_date")
        placeholders.append("?")
        values.append(date.today().isoformat())
        fields.append("created_by")
        placeholders.append("?")
        values.append(user_id)
        # Default status and approval_status
        fields.append("status")
        placeholders.append("?")
        values.append("Pending")
        fields.append("approval_status")
        placeholders.append("?")
        values.append("Pending")
        # Build and execute
        cur = conn.execute(
            f"INSERT INTO loans ({', '.join(fields)}) VALUES ({', '.join(placeholders)})",
            values
        )
        conn.commit()
        return cur.lastrowid


    def _download_loan_template(self):
        _download_csv_template(
            ["client_no", "loan_product", "principal", "interest_rate", "interest_method",
            "term_months", "repayment_frequency", "admin_fee", "application_fee",
            "purpose", "collateral", "disbursement_date"],
            "loans_template.csv",
        )

    def _clear_new_loan_form(self):
        self.nl_client.set("")
        self.nl_product.set("(none - manual terms)")
        self.nl_principal.delete(0, "end")
        self.nl_rate.delete(0, "end")
        # Removed nl_rate_preset handling
        self.nl_method.set("flat")
        self.nl_freq.set("monthly")
        self.nl_term.delete(0, "end")
        self.nl_phase2_freq.set("biweekly")
        self.nl_phase2_term.delete(0, "end")
        self.nl_admin_fee.delete(0, "end")
        self.nl_app_fee.delete(0, "end")
        self.nl_due_date.delete(0, "end")
        
        
    def _download_csv_template(headers, suggested_name):
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV files", "*.csv")],
                                            initialfile=suggested_name)
        if not path:
            return
        try:
            with open(path, "w", newline="") as f:
                csv.writer(f).writerow(headers)
            info(f"Template saved to:\n{path}\n\nFill it in and use the matching Bulk Upload button to import it.")
        except PermissionError:
            error("Cannot write to that location. Please choose a different folder (e.g., Desktop or Documents).")
        except Exception as e:
            error(f"Error saving template: {str(e)}")
        

    def _bulk_upload_loans(self):
        rows = _pick_csv_upload()
        if rows is None:
            return
        success, errors = 0, []
        for i, row in enumerate(rows, start=2):
            try:
                # ---- Client ----
                client_no = (row.get("client_no") or "").strip()
                if not client_no:
                    raise ValueError("client_no is required.")
                client = client_model.get_client_by_no(self.conn, client_no)
                if not client:
                    raise ValueError(f"No client found with client_no '{client_no}'.")

                # ---- Product lookup (case‑insensitive) ----
                product_name = (row.get("loan_product") or "").strip()
                product = None
                if product_name:
                    product = self.conn.execute(
                        "SELECT * FROM loan_products WHERE LOWER(name) = LOWER(?) AND active = 1",
                        (product_name,)
                    ).fetchone()
                    if not product:
                        # Try with trimmed and normalized (just in case)
                        product = self.conn.execute(
                            "SELECT * FROM loan_products WHERE LOWER(TRIM(name)) = LOWER(TRIM(?)) AND active = 1",
                            (product_name,)
                        ).fetchone()
                    if product:
                        print(f"✅ Product found: {product['name']} (ID {product['id']})")
                    else:
                        print(f"⚠️ Product '{product_name}' not found. Using manual defaults.")

                # ---- Start with product defaults or fallback ----
                if product:
                    data = {
                        "client_id": client["id"],
                        "product_id": product["id"],
                        "principal": 0.0,
                        "interest_rate": product["interest_rate"],
                        "interest_method": product["interest_method"],
                        "rate_period": product["rate_period"],
                        "term_months": 0,
                        "repayment_frequency": product["repayment_frequency"],
                        "admin_fee": 0.0,
                        "purpose": None,
                        "collateral": None,
                        "disbursement_date": None,
                    }
                    # If product has admin_fee_pct, we'll apply later after principal is set
                else:
                    data = {
                        "client_id": client["id"],
                        "product_id": None,
                        "principal": 0.0,
                        "interest_rate": 0.0,
                        "interest_method": "flat",
                        "rate_period": "month",
                        "term_months": 0,
                        "repayment_frequency": "monthly",
                        "admin_fee": 0.0,
                        "purpose": None,
                        "collateral": None,
                        "disbursement_date": None,
                    }

                # ---- Override with CSV values ----
                # Principal
                if row.get("principal") and row["principal"].strip():
                    data["principal"] = parse_money(row["principal"])
                if data["principal"] <= 0:
                    raise ValueError("principal must be a positive number.")

                # Interest Rate
                if row.get("interest_rate") and row["interest_rate"].strip():
                    data["interest_rate"] = float(row["interest_rate"])
                elif product and data["interest_rate"] == 0:
                    # Keep product default (already set)
                    pass
                if data["interest_rate"] <= 0:
                    raise ValueError("interest_rate must be a positive number.")

                # Interest Method
                if row.get("interest_method") and row["interest_method"].strip():
                    val = row["interest_method"].strip().lower()
                    if val == "interest_over_tenure":
                        # Retired: it always computed a single lump interest
                        # percentage over the whole term, which is exactly
                        # what 'flat' does with rate_period='loan_term'.
                        # Accepted here for backward compatibility with older
                        # CSV templates, rather than rejecting the row.
                        data["interest_method"] = "flat"
                        data["rate_period"] = "loan_term"
                    else:
                        allowed = ["flat", "reducing_balance", "interest_only_balloon"]
                        if val not in allowed:
                            raise ValueError(f"interest_method must be one of: {', '.join(allowed)}")
                        data["interest_method"] = val
                # else keep product default or fallback

                # Term Months
                if row.get("term_months") and row["term_months"].strip():
                    data["term_months"] = int(row["term_months"])
                elif product and data["term_months"] == 0:
                    # Product doesn't have a term, so we still need a value – must be in CSV
                    raise ValueError("term_months must be provided in CSV (product has no default term).")
                if data["term_months"] <= 0:
                    raise ValueError("term_months must be a positive integer.")

                # Repayment Frequency
                if row.get("repayment_frequency") and row["repayment_frequency"].strip():
                    val = row["repayment_frequency"].strip().lower()
                    allowed_freq = ["monthly", "biweekly", "weekly"]
                    if val not in allowed_freq:
                        raise ValueError(f"repayment_frequency must be one of: {', '.join(allowed_freq)}")
                    data["repayment_frequency"] = val
                # else keep product default or fallback

                # Admin Fee
                if row.get("admin_fee") and row["admin_fee"].strip():
                    data["admin_fee"] = parse_money(row["admin_fee"])
                elif product and product["admin_fee_pct"] and data["principal"] > 0:
                    # Compute from product percentage (principal is already cents,
                    # so this naturally comes out in cents too - just needs rounding)
                    from ..money import round_cents as _round_cents_local
                    data["admin_fee"] = _round_cents_local(data["principal"] * product["admin_fee_pct"] / 100.0)
                    print(f"   Computed admin fee {money(data['admin_fee'])} from {product['admin_fee_pct']}%")

                data["purpose"] = row.get("purpose", "").strip() or None
                data["collateral"] = row.get("collateral", "").strip() or None

                # ---- Disbursement date ----
                if row.get("disbursement_date") and row["disbursement_date"].strip():
                    disp_date = row["disbursement_date"].strip()
                    from datetime import datetime
                    try:
                        datetime.strptime(disp_date, "%Y-%m-%d")
                    except ValueError:
                        raise ValueError("disbursement_date must be in YYYY-MM-DD format.")
                    data["disbursement_date"] = disp_date

                # ---- (Optional) Print final data for debugging ----
                print(f"Row {i} data: {data}")

                # ---- Create loan ----
                new_loan_id = loan_model.create_loan(self.conn, data, Session.current_user["id"])

                # ---- Application fee ----
                app_fee = parse_money(row.get("application_fee") or 0)
                if app_fee > 0:
                    fee_model.charge_fee(
                        self.conn, new_loan_id, "Application", app_fee,
                        description="Application fee (bulk import)", mark_paid=True,
                        user_id=Session.current_user["id"],
                    )
                success += 1
            except Exception as e:
                errors.append(f"Row {i}: {e}")
                print(f"Row {i} error: {e}")

        _show_bulk_result("loan(s) (submitted, still awaiting approval/disbursement)", success, errors)
        self._refresh_loans()
        self._refresh_approvals()


    # ==========================================
    # TAB 4: DISBURSE FUNDS
    # ==========================================
    def _build_disburse(self, tab):
        scroll = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=15, pady=15)
        
        ctk.CTkLabel(scroll, text="Disburse Approved Loan", font=("Segoe UI", 18, "bold")).pack(anchor="w", pady=(0, 5), padx=10)

        toolbar = ctk.CTkFrame(scroll, fg_color="transparent")
        toolbar.pack(fill="x", padx=10, pady=(0, 10))
        ctk.CTkButton(toolbar, text="↻ Refresh Approved Loans", command=self._refresh_disburse_list, width=150, fg_color="gray40").pack(side="right")

        def on_loan_selected(val):
            self._recalc_first_due()

        def on_date_changed(event):
            self._recalc_first_due()

        schema = [
            {
                "title": "Approval Target",
                "color": "#1A3B5C", # Dark Navy
                "rows": [
                    [
                        {"key": "loan", "label": "SELECT LOAN*", "type": "searchable", "options": [], "command": on_loan_selected}
                    ]
                ]
            },
            {
                "title": "Disbursement Specifics",
                "color": "#5C3A1A", # Dark Amber
                "rows": [
                    [
                        {"key": "amount", "label": "AMOUNT*", "type": "money"},
                        {"key": "date", "label": "DISBURSEMENT DATE*", "type": "date", "default": date.today().isoformat(), "command": on_date_changed},
                        {"key": "method", "label": "METHOD*", "type": "combobox", "options": ["Cash", "Bank Transfer", "Mobile Money"]}
                    ]
                ]
            },
            {
                "title": "Scheduling & Reference",
                "color": "#1A5C3A", # Dark Teal
                "rows": [
                    [
                        {"key": "first_due", "label": "FIRST DUE DATE", "state": "disabled"},
                        {"key": "reference", "label": "REFERENCE", "placeholder": "Auto-generated if left blank"}
                    ]
                ]
            }
        ]

        def submit(values):
            try:
                loan = self.disb_lookup.get(values["loan"])
                if not loan: raise ValueError("Select a valid approved loan.")
                disb_model.disburse_loan(
                    self.conn, loan["id"], amount=parse_money(values["amount"]),
                    disbursement_date=values["date"], method=values["method"],
                    first_due_date=values["first_due"],
                    reference=values["reference"].strip() or None,
                    user_id=Session.current_user["id"]
                )
                info("Loan disbursed successfully.")
                
                # Clear form
                self.disb_form.update_fields({k: "" for k in ["loan", "amount", "first_due", "reference"]})
                self.disb_form.update_fields({"date": date.today().isoformat(), "method": "Cash"})
                
                self._refresh_disburse_list()
                self._refresh_loans()
                self._refresh_repayment_list()
                self._refresh_statement_list()
                self._refresh_amortisation_list()
            except Exception as e: error(str(e))

        self.disb_form = SectionedFormFrame(scroll, schema=schema, on_submit=submit, submit_text="Confirm Disbursement")
        self.disb_form.pack(fill="x", expand=False)
        self._refresh_disburse_list()

    def _refresh_disburse_list(self):
        pending = loan_model.list_loans(self.conn, status="Pending", approval_status="Approved")
        self.disb_lookup = {f"{l['loan_no']} - {l['first_name']} {l['last_name']} ({money(l['principal'])})": l for l in pending}
        
        loan_widget = self.disb_form.get_widget("loan")
        if loan_widget:
            loan_widget.set_values(list(self.disb_lookup.keys()))

    def _recalc_first_due(self, _=None):
        vals = self.disb_form.get_values()
        loan = self.disb_lookup.get(vals["loan"])
        if not loan: return
        
        first_due = loan_model.next_due_date(vals["date"] or date.today().isoformat(), loan["repayment_frequency"])
        self.disb_form.update_fields({
            "first_due": first_due,
            "amount": money_edit_str(loan["principal"])
        })

        
    # ==========================================
    # TAB 5: RECORD REPAYMENT
    # ==========================================
    def _build_repayment(self, tab):
        scroll = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=15, pady=15)

        ctk.CTkLabel(scroll, text="Record Repayment", font=("Segoe UI", 18, "bold")).pack(anchor="w", pady=(0, 5), padx=10)

        # Bulk upload buttons toolbar
        bulk_bar = ctk.CTkFrame(scroll, fg_color=("gray88", "gray18"), corner_radius=6)
        bulk_bar.pack(fill="x", padx=10, pady=(0, 10), ipadx=10, ipady=4)

        ctk.CTkLabel(bulk_bar, text="Bulk Upload:", font=("Segoe UI", 12, "bold"),
                    text_color=TEXT_MUTED).pack(side="left", padx=(0, 10))
        ctk.CTkButton(bulk_bar, text="Download Template", fg_color="gray40",
                    height=30, command=self._download_repayment_template).pack(side="left", padx=(0, 6))
        ctk.CTkButton(bulk_bar, text="Bulk Upload Repayments", fg_color="#27AE60",
                    height=30, font=("Segoe UI", 13, "bold"),
                    command=self._bulk_upload_repayments).pack(side="left")

        ctk.CTkButton(bulk_bar, text="↻ Refresh Active Loans", fg_color="gray40",
                    height=30, command=self._refresh_repayment_list).pack(side="right", padx=6)

        schema = [
            {
                "title": "Select Loan",
                "color": "#1A3B5C",  # Dark Navy
                "rows": [
                    [
                        {"key": "loan", "label": "ACTIVE LOAN*", "type": "searchable", "options": []}
                    ]
                ]
            },
            {
                "title": "Payment Details",
                "color": "#5C3A1A",  # Dark Amber
                "rows": [
                    [
                        {"key": "amount", "label": "AMOUNT*", "type": "money"},
                        {"key": "payment_date", "label": "DATE*", "type": "date", "default": date.today().isoformat()},
                        {"key": "method", "label": "METHOD*", "type": "combobox", "options": ["Cash", "Bank Transfer", "Mobile Money"]}
                    ]
                ]
            },
            {
                "title": "Reference",
                "color": "#1A5C3A",  # Dark Teal
                "rows": [
                    [
                        {"key": "reference", "label": "REFERENCE", "placeholder": "Optional reference code"}
                    ]
                ]
            }
        ]

        def submit(values):
            try:
                loan_id = self.rpy_lookup.get(values["loan"])
                if not loan_id: 
                    raise ValueError("Select a valid active loan.")
                
                amount_str = values["amount"].strip()
                if not amount_str:
                    raise ValueError("Amount is required.")
                
                repay_model.record_repayment(
                    self.conn, loan_id, amount=parse_money(amount_str),
                    payment_date=values["payment_date"], method=values["method"],
                    reference=values.get("reference").strip() or None,
                    user_id=Session.current_user["id"]
                )
                info("Repayment recorded successfully.")
                
                # Clear inputs - deliberately leave "payment_date" untouched so it
                # keeps whatever date the user last picked. Handy when posting a
                # batch of repayments for the same day: pick the date once, then
                # just change the loan/amount for each subsequent payment.
                self.rpy_form.update_fields({
                    "loan": "", 
                    "amount": "", 
                    "reference": "",
                    "method": "Cash",
                })
                
                self._refresh_repayment_list()
                self._refresh_repayment_history()
                self._refresh_loans()
                self._refresh_statement_list()
                self._refresh_amortisation_list()
            except Exception as e: 
                error(str(e))

        self.rpy_form = SectionedFormFrame(scroll, schema=schema, on_submit=submit, submit_text="Post Repayment")
        self.rpy_form.pack(fill="x", expand=False, pady=(0, 15))

        # ----- History toolbar & table -----
        hist_frame = ctk.CTkFrame(scroll, fg_color="transparent")
        hist_frame.pack(fill="x", padx=10, pady=(10, 6))
        ctk.CTkLabel(hist_frame, text="Repayment History", font=("Segoe UI", 15, "bold")).pack(side="left")
        ctk.CTkButton(hist_frame, text="✎ Edit Selected", width=100, command=self._edit_repayment).pack(side="right", padx=4)
        ctk.CTkButton(hist_frame, text="✖ Delete Selected", fg_color="#EB5757", hover_color="#C0392B",
                    width=100, command=self._delete_repayment).pack(side="right", padx=4)

        self.rpy_history_table = DataTable(scroll, columns=[
            ("loan_no", "Loan #"), ("client_name", "Client"), ("payment_date", "Date"),
            ("amount", "Amount"), ("method", "Method"), ("reference", "Reference"),
        ], height=14, title="Repayment History")
        self.rpy_history_table.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # Initial data loads
        self._refresh_repayment_list()
        self._refresh_repayment_history()
        
    def _refresh_repayment_history(self):
        rows = repay_model.list_repayments(self.conn)
        self.rpy_history_table.set_rows([{
            "id": r["id"], "loan_no": r["loan_no"], "client_name": f"{r['first_name']} {r['last_name']}",
            "payment_date": r["payment_date"], "amount": money(r["amount"]),
            "method": r["method"], "reference": r["reference"] or "",
        } for r in rows])

    def _edit_repayment(self):
        if not perm_model.has_permission(self.conn, Session.current_user, "Loans", "edit"):
            error("You do not have permission to edit repayments.")
            return
        row = self.rpy_history_table.selected_row()
        if not row:
            return error("Select a repayment from the history list below first.")
        default_amount = "".join(c for c in row["amount"] if c.isdigit() or c in ".-")
        fields = [
            {"key": "amount", "label": "Amount*", "type": "money", "default": default_amount},
            {"key": "payment_date", "label": "Date", "type": "date", "default": row["payment_date"]},
            {"key": "method", "label": "Method", "type": "combobox",
             "options": ["Cash", "Bank Transfer", "Mobile Money"], "default": row["method"]},
            {"key": "reference", "label": "Reference", "default": row["reference"]},
        ]

        def submit(values):
            repay_model.update_repayment(
                self.conn, int(row["id"]), amount=parse_money(values["amount"]),
                payment_date=values["payment_date"], method=values["method"],
                reference=values.get("reference") or None, user_id=Session.current_user["id"],
            )
            info("Repayment updated - the loan's schedule and statement have been recalculated.")
            self._refresh_repayment_history(); self._refresh_repayment_list(); self._refresh_loans()
            self._refresh_statement_list(); self._refresh_amortisation_list()

        FormDialog(self, f"Edit Repayment - {row['loan_no']}", fields, submit)

    def _delete_repayment(self):
        if not perm_model.has_permission(self.conn, Session.current_user, "Loans", "delete"):
            error("You do not have permission to delete repayments.")
            return
        row = self.rpy_history_table.selected_row()
        if not row:
            return error("Select a repayment from the history list below first.")
        if not confirm(f"Delete this {row['amount']} repayment on loan {row['loan_no']}?\n\n"
                        f"This reverses it from the loan's schedule/statement and cannot be undone."):
            return
        try:
            repay_model.delete_repayment(self.conn, int(row["id"]), user_id=Session.current_user["id"])
            info("Repayment deleted - the loan's schedule and statement have been recalculated.")
            self._refresh_repayment_history(); self._refresh_repayment_list(); self._refresh_loans()
            self._refresh_statement_list(); self._refresh_amortisation_list()
        except Exception as e: error(str(e))

    def _download_repayment_template(self):
        _download_csv_template(
            ["loan_no", "amount", "payment_date", "method", "reference", "notes"],
            "repayments_template.csv",
        )

    def _bulk_upload_repayments(self):
        rows = _pick_csv_upload()
        if rows is None:
            return
        success, errors = 0, []
        for i, row in enumerate(rows, start=2):
            try:
                loan_no = (row.get("loan_no") or "").strip()
                if not loan_no:
                    raise ValueError("loan_no is required.")
                loan = loan_model.get_loan_by_no(self.conn, loan_no)
                if not loan:
                    raise ValueError(f"No loan found with loan_no '{loan_no}'.")
                amount = parse_money(row["amount"])
                repay_model.record_repayment(
                    self.conn, loan["id"], amount=amount,
                    payment_date=(row.get("payment_date") or "").strip() or None,
                    method=(row.get("method") or "").strip() or "Cash",
                    reference=(row.get("reference") or "").strip() or None,
                    notes=(row.get("notes") or "").strip() or None,
                    user_id=Session.current_user["id"],
                )
                success += 1
            except Exception as e:
                errors.append(f"Row {i}: {e}")
        _show_bulk_result("repayment(s)", success, errors)
        self._refresh_repayment_list()
        self._refresh_repayment_history()
        self._refresh_loans()
        self._refresh_statement_list()
        self._refresh_amortisation_list()
            
    def _refresh_repayment_list(self):
        active = loan_model.list_loans(self.conn, status="Active", only_with_balance=True)
        self.rpy_lookup = {}
        for l in active:
            bal = loan_model.outstanding_balance(self.conn, l["id"])
            self.rpy_lookup[f"{l['loan_no']} - {l['first_name']} {l['last_name']} (Bal: {money(bal['total'])})"] = l["id"]
        
        loan_widget = self.rpy_form.get_widget("loan")
        if loan_widget:
            loan_widget.set_values(list(self.rpy_lookup.keys()))

    def _do_repayment(self):
        try:
            loan_id = self.rpy_lookup.get(self.rpy_loan.get())
            if not loan_id: raise ValueError("Select a valid active loan.")
            repay_model.record_repayment(
                self.conn, loan_id, amount=parse_money(self.rpy_amount.get()),
                payment_date=self.rpy_date.get(), method=self.rpy_method.get(),
                reference=self.rpy_reference.get().strip() or None,
                user_id=Session.current_user["id"]
            )
            info("Repayment recorded.")
            self._clear_repayment_form()
            self._refresh_repayment_list(); self._refresh_repayment_history(); self._refresh_loans()
            self._refresh_statement_list(); self._refresh_amortisation_list()
        except Exception as e: error(str(e))

    def _clear_repayment_form(self):
        self.rpy_loan.set("")
        self.rpy_amount.delete(0, "end")
        self.rpy_date.delete(0, "end"); self.rpy_date.insert(0, date.today().isoformat())
        self.rpy_method.set("Cash")
        self.rpy_reference.delete(0, "end")

    # ==========================================
    # TAB 6 & 7: FULL-WIDTH TABLES (Statements & Schedules)
    # ==========================================
    def _build_statement(self, tab):
        bar = self._create_control_bar(tab)
        ctk.CTkLabel(bar, text="Select Loan:", font=("Segoe UI", 12, "bold")).pack(side="left", padx=(10, 5))
        self.stmt_loan = SearchableCombobox(bar, values=[], width=320)
        self.stmt_loan.pack(side="left", padx=5)
        ctk.CTkButton(bar, text="Load Statement", fg_color="#2D9CDB", command=self._load_statement).pack(side="left", padx=10)
        ctk.CTkButton(bar, text="Charge Penalty", fg_color="#EB5757", hover_color="#C0392B", command=self._charge_penalty).pack(side="left", padx=5)
        ctk.CTkButton(bar, text="Edit Penalty", fg_color="#F2994A", hover_color="#C67F1E", command=self._edit_penalty).pack(side="left", padx=5)

        self.stmt_summary_frame = ctk.CTkFrame(tab, fg_color="transparent")
        self.stmt_summary_frame.pack(fill="x", padx=20, pady=(10, 5))
        
        self.stmt_lbl_total_owed = ctk.CTkLabel(self.stmt_summary_frame, text="Total Owed: --", font=("Segoe UI", 16, "bold"), text_color="#1F6AA5")
        self.stmt_lbl_total_owed.pack(side="left", padx=(0, 30))
        
        self.stmt_lbl_next_due = ctk.CTkLabel(self.stmt_summary_frame, text="Next Due: --", font=("Segoe UI", 14, "bold"), text_color="#F2994A")
        self.stmt_lbl_next_due.pack(side="left", padx=(0, 30))
        
        self.stmt_lbl_arrears = ctk.CTkLabel(self.stmt_summary_frame, text="Arrears: --", font=("Segoe UI", 14, "bold"), text_color="#EB5757")
        self.stmt_lbl_arrears.pack(side="left")

        self.stmt_table = DataTable(tab, columns=[
            ("date", "Date"), 
            ("description", "Transaction Description"),
            ("principal_charge", "Principal"), 
            ("interest_charge", "Interest"), 
            ("fee_charge", "Fees/Penalties"),
            ("payment", "Payment Received"), 
            ("balance", "Running Balance")
        ], title="Loan Statement", show_summary=False)
        self.stmt_table.pack(fill="both", expand=True)
        self._refresh_statement_list()


    def _refresh_statement_list(self):
        all_loans = loan_model.list_loans(self.conn)
        self.stmt_lookup = {f"{l['loan_no']} - {l['first_name']} {l['last_name']}": l["id"] for l in all_loans}
        self.stmt_loan.set_values(list(self.stmt_lookup.keys()))

    def _loan_pdf_meta_lines(self, loan_id, bal_dict=None, next_inst=None, arrears_amt=0, next_due_text=None):
        loan = loan_model.get_loan(self.conn, loan_id)
        client = client_model.get_client(self.conn, loan["client_id"]) if loan else None
        if not loan: return []
        
        national_id = (client["national_id"] if client else None) or "-"
        lines = [
            f"BORROWER DETAILS",
            f"Name: {loan['first_name']} {loan['last_name']}  (Client #: {client['client_no'] if client else '-'})",
            f"National ID: {national_id}    Phone: {loan['phone'] or '-'}    Location: {loan['location'] or '-'}",
            f"--------------------------------------------------------------------------------",
            f"ACCOUNT OVERVIEW",
            f"Loan #: {loan['loan_no']}    Status: {loan['status'].upper()}",
            f"Principal: {money(loan['principal'])}    Interest: {loan['interest_rate']}% ({loan['interest_method'].replace('_', ' ').title()})",
            f"Disbursed: {loan['disbursement_date'] or '-'}    Maturity: {loan['maturity_date'] or '-'}"
        ]
        
        if bal_dict:
            lines.append(f"--------------------------------------------------------------------------------")
            lines.append(f"EXECUTIVE SUMMARY")
            lines.append(f"Total Outstanding Balance: {money(bal_dict['total'])}")
            if arrears_amt > 0:
                lines.append(f"CURRENT ARREARS: {money(arrears_amt)} (IMMEDIATELY DUE)")
            # Reuse the exact same "missed installments + next installment"
            # text shown on-screen, so the PDF statement matches what the
            # user sees in the app instead of only ever showing a single
            # upcoming installment.
            if next_due_text:
                lines.append(next_due_text)
            elif next_inst:
                next_due_amt = round(
                    (next_inst['principal_due'] - next_inst['principal_paid']) +
                    (next_inst['interest_due'] - next_inst['interest_paid']),
                    2
                )
                lines.append(f"Next Installment Due: {money(next_due_amt)} on {next_inst['due_date']}")
            elif bal_dict['total'] > 0:
                lines.append(f"Past Maturity ({loan['maturity_date'] or '-'}) - Amount Owed: {money(bal_dict['total'])}")
            lines.append(f"Principal Remaining: {money(bal_dict['principal'])}    Interest/Fees Accrued: {money(bal_dict['interest'] + bal_dict['penalty'])}")
            
        lines.append(f"--------------------------------------------------------------------------------")
        lines.append(f"REMITTANCE INSTRUCTIONS: Please ensure all payments quote Loan # {loan['loan_no']} as the reference.")
        lines.append(f"--------------------------------------------------------------------------------")
        return lines
    

    def _load_statement(self):
        try:
            loan_id = self.stmt_lookup.get(self.stmt_loan.get())
            if not loan_id: raise ValueError("Select a valid loan.")

            # If this loan is part of a rollover chain, every "current state"
            # figure below (balance, next due, arrears) needs to reflect the
            # ACTIVE loan at the end of the chain - not whichever loan in the
            # history happened to be searched for. A rolled-over loan is
            # force-closed to a zero balance at rollover time, so anchoring
            # the summary on it would misleadingly show "Fully Paid" instead
            # of the real, current obligation on the loan it became.
            chain = rollover_model.get_rollover_chain(self.conn, loan_id)
            loan_id = chain[-1]

            loan = loan_model.get_loan(self.conn, loan_id)
            data = repay_model.loan_statement_ledger(self.conn, loan_id)
            bal = loan_model.outstanding_balance(self.conn, loan_id)
            schedule = loan_model.get_amortisation_schedule(self.conn, loan_id)
            
            # The next installment is the earliest one that isn't fully Paid -
            # not literally status=="Pending". An installment can be "Overdue"
            # (after apply_overdue_penalties) or "PartiallyPaid" (a partial
            # payment was made, e.g. on an interest_only_balloon loan) and
            # still be the next thing owed. Filtering on "Pending" alone made
            # the statement wrongly report "Fully Paid" as soon as the next
            # due installment moved to either of those other statuses, even
            # though the loan still had a real balance.
            next_inst = next((s for s in schedule if s["status"] != "Paid"), None)
            # An installment counts as missed/in-arrears as soon as its due
            # date has passed and it isn't fully Paid - regardless of whether
            # its stored status says "Overdue" (penalty already applied),
            # "Pending" (penalty not yet applied), or "PartiallyPaid" (some
            # payment came in but not enough to clear it). Checking only for
            # "Overdue"/"Pending" - as before - silently dropped overdue
            # PartiallyPaid installments out of arrears entirely.
            today_str = date.today().isoformat()
            overdue_inst = [s for s in schedule if s["status"] != "Paid" and s["due_date"] < today_str]

            def _inst_amount_due(s):
                return round(
                    (s.get("principal_due", 0) - s.get("principal_paid", 0)) +
                    (s.get("interest_due", 0) - s.get("interest_paid", 0)) +
                    (s.get("penalty_charged", s.get("penalty_due", 0)) - s.get("penalty_paid", 0)),
                    2
                )

            arrears_amt = sum(_inst_amount_due(s) for s in overdue_inst)

            self.stmt_lbl_total_owed.configure(text=f"Total Owed: {money(bal['total'])}")
            if overdue_inst:
                # List every missed installment (date + amount still owed on
                # it) rather than just the single earliest one, so it's clear
                # exactly which payments were missed.
                missed_str = ", ".join(
                    f"{money(_inst_amount_due(s))} ({s['due_date']})" for s in overdue_inst
                )
                # Alongside the missed installments, also surface the next
                # upcoming installment that isn't yet overdue (if any), so
                # the statement shows both what's already late and what's
                # coming next - matching the official statement layout.
                next_upcoming = next(
                    (s for s in schedule if s["status"] != "Paid" and s["due_date"] >= today_str),
                    None,
                )
                next_due_suffix = ""
                if next_upcoming:
                    next_upcoming_amt = round(
                        (next_upcoming['principal_due'] - next_upcoming['principal_paid']) +
                        (next_upcoming['interest_due'] - next_upcoming['interest_paid']),
                        2
                    )
                    next_due_suffix = (
                        f"  |  Next Installment: {money(next_upcoming_amt)} due {next_upcoming['due_date']}"
                    )
                next_due_text = f"Next Due: {len(overdue_inst)} missed - {missed_str}{next_due_suffix}"
            elif next_inst:
                next_due_amt = round(
                    (next_inst['principal_due'] - next_inst['principal_paid']) +
                    (next_inst['interest_due'] - next_inst['interest_paid']),
                    2
                )
                next_due_text = f"Next Due: {money(next_due_amt)} on {next_inst['due_date']}"
            elif bal['total'] > 0:
                # No schedule row left unpaid, but a balance still remains
                # (e.g. a fee/penalty added after the last installment, or a
                # rounding remainder) - past maturity, so surface the
                # maturity date rather than the misleading "Fully Paid".
                next_due_text = f"Past Maturity ({loan['maturity_date'] or '-'}) - Amount Owed: {money(bal['total'])}"
            else:
                next_due_text = "Next Due: None (Fully Paid)"

            self.stmt_lbl_next_due.configure(text=next_due_text)
            self.stmt_lbl_arrears.configure(text=f"Arrears: {money(arrears_amt)}")

            processed_rows = []

            for idx, lid in enumerate(chain):
                is_current = (lid == loan_id)
                sec_loan = loan if is_current else loan_model.get_loan(self.conn, lid)
                sec_schedule = schedule if is_current else loan_model.get_amortisation_schedule(self.conn, lid)
                sec_data = data if is_current else repay_model.loan_statement_ledger(self.conn, lid)

                running_balance = 0
                disb_date = sec_loan["disbursement_date"] or date.today().isoformat()

                if len(chain) > 1:
                    processed_rows.append({
                        "date": disb_date, "description": f"=== Loan {sec_loan['loan_no']} ===",
                        "principal_charge": "-", "interest_charge": "-", "fee_charge": "-",
                        "payment": "-", "balance": "-",
                    })

                # 1. Inject Upfront Principal Disbursement
                running_balance += sec_loan["principal"]
                processed_rows.append({
                    "date": disb_date,
                    "description": "Loan Disbursement",
                    "principal_charge": money(sec_loan["principal"]),
                    "interest_charge": "-",
                    "fee_charge": "-",
                    "payment": "-",
                    "balance": money(running_balance)
                })

                # 2. Inject Upfront Capitalized Interest
                # Recomputed live from the schedule every time it's viewed, not
                # frozen at disbursement - for interest_only_balloon loans, early
                # curtailment genuinely lowers total interest owed below the
                # original estimate, and the running balance below needs to
                # reflect that or it will permanently overstate the true
                # remaining debt.
                total_interest = sum(s["interest_due"] for s in sec_schedule)
                running_balance += total_interest
                processed_rows.append({
                    "date": disb_date,
                    "description": "Total Interest Capitalized",
                    "principal_charge": "-",
                    "interest_charge": money(total_interest),
                    "fee_charge": "-",
                    "payment": "-",
                    "balance": money(running_balance)
                })

                # 3. Process Payments and Penalties from Ledger (ignoring backend interest/disbursement accruals)
                for r in sec_data["rows"]:
                    desc = r["description"].lower()

                    # Skip normal disbursements or standard interest charges since we capitalized them upfront
                    if "disbursement" in desc or ("interest" in desc and "penalty" not in desc):
                        continue

                    p_charge = i_charge = f_charge = "-"
                    payment_val = "-"
                    include_row = False

                    if r["charge"] and ("penalty" in desc or "fee" in desc):
                        f_charge = money(r["charge"])
                        running_balance += int(r["charge"])
                        include_row = True

                    if r["payment"]:
                        payment_val = money(r["payment"])
                        running_balance -= int(r["payment"])
                        include_row = True

                    if include_row:
                        processed_rows.append({
                            "date": r["date"],
                            "description": r["description"],
                            "principal_charge": p_charge,
                            "interest_charge": i_charge,
                            "fee_charge": f_charge,
                            "payment": payment_val,
                            "balance": money(running_balance)
                        })

                # Rollover transition marker between this loan and the next one
                # in the chain - the remaining balance shown just above wasn't
                # paid off in cash, it was carried forward into the new loan
                # below (which starts its own section fresh, with its own
                # principal and interest structure - see the rollover
                # discussion for why the two sections aren't blended into one
                # running total).
                if idx < len(chain) - 1:
                    next_lid = chain[idx + 1]
                    rollover_row = self.conn.execute(
                        "SELECT * FROM rollovers WHERE original_loan_id = ? AND new_loan_id = ?",
                        (lid, next_lid)
                    ).fetchone()
                    next_loan = loan_model.get_loan(self.conn, next_lid)
                    if rollover_row and next_loan:
                        processed_rows.append({
                            "date": rollover_row["rollover_date"],
                            "description": (
                                f"--- Rolled over into {next_loan['loan_no']} - "
                                f"balance of {money(rollover_row['outstanding_balance'])} carried forward ---"
                            ),
                            "principal_charge": "-", "interest_charge": "-", "fee_charge": "-",
                            "payment": "-", "balance": "-",
                        })

            self.stmt_table.set_rows(processed_rows)
            title_suffix = " (Consolidated - Includes Rollover History)" if len(chain) > 1 else ""
            self.stmt_table.pdf_title = f"Official Loan Statement - {loan['loan_no']}{title_suffix}"
            self.stmt_table.set_pdf_meta(self._loan_pdf_meta_lines(loan_id, bal, next_inst, arrears_amt, next_due_text))
        except Exception as e: 
            error(str(e))
        
    def _charge_penalty(self):
        loan_id = self.stmt_lookup.get(self.stmt_loan.get())
        if not loan_id:
            return error("Select a loan first (use the search box above).")
        loan_label = self.stmt_loan.get()

        fields = [
            {"key": "amount", "label": "Penalty Amount*", "type": "money", "default": ""},
            {"key": "reason", "label": "Reason", "default": ""},
        ]

        def submit(values):
            amount = parse_money(values["amount"])
            fee_model.charge_manual_penalty(
                self.conn, loan_id, amount, reason=values.get("reason") or None,
                user_id=Session.current_user["id"],
            )
            info(f"Penalty of {money(amount)} charged to {loan_label}.")
            self._load_statement()
            self._refresh_amortisation_list()

        FormDialog(self, f"Charge Penalty - {loan_label}", fields, submit)

    def _edit_penalty(self):
        loan_id = self.stmt_lookup.get(self.stmt_loan.get())
        if not loan_id:
            return error("Select a loan first (use the search box above).")
        loan_label = self.stmt_loan.get()

        installments = fee_model.list_penalized_installments(self.conn, loan_id)
        if not installments:
            return error(f"No penalties currently charged on {loan_label}.")

        inst_lookup = {
            f"Installment {i['installment_no']} - Due {i['due_date']} - "
            f"Current Penalty {money(i['penalty_charged'])}": i
            for i in installments
        }
        fields = [
            {"key": "installment", "label": "Installment*", "type": "combobox",
             "options": list(inst_lookup.keys())},
            {"key": "new_amount", "label": "New Penalty Amount*", "type": "money", "default": ""},
        ]

        def submit(values):
            inst = inst_lookup[values["installment"]]
            new_amount = parse_money(values["new_amount"])
            fee_model.edit_penalty(
                self.conn, inst["id"], new_amount, user_id=Session.current_user["id"],
            )
            info(f"Penalty on installment {inst['installment_no']} updated to {money(new_amount)}.")
            self._load_statement()
            self._refresh_amortisation_list()

        FormDialog(self, f"Edit Penalty - {loan_label}", fields, submit)

    def _build_amortisation_schedule(self, tab):
        bar = self._create_control_bar(tab)
        ctk.CTkLabel(bar, text="Select Loan:", font=("Segoe UI", 12, "bold")).pack(side="left", padx=(10, 5))
        self.sched_loan = SearchableCombobox(bar, values=[], width=320)
        self.sched_loan.pack(side="left", padx=5)
        ctk.CTkButton(bar, text="Load Schedule", fg_color="#2D9CDB", command=self._load_schedule).pack(side="left", padx=10)

        # NEW: Compact Summary Card (Flattened to 2 rows to save vertical space)
        self.sched_summary_frame = ctk.CTkFrame(tab, fg_color=NAVY_CARD, corner_radius=8, border_width=1, border_color=NAVY_BORDER)
        
        # Configure 10 columns (5 pairs of label + value)
        for i in range(10):
            self.sched_summary_frame.columnconfigure(i, weight=1 if i % 2 != 0 else 0)

        self.lbl_sum_title = ctk.CTkLabel(self.sched_summary_frame, text="", font=("Segoe UI", 14, "bold"), text_color=BLUE_LIGHT)
        self.lbl_sum_title.grid(row=0, column=0, columnspan=10, sticky="w", padx=10, pady=(5, 0))

        self.summary_labels = {}
        
        # 2-row layout to drastically reduce height
        labels_layout = [
            ("Loan Amount", 1, 0), ("Rate (Monthly)", 1, 2), ("Method", 1, 4), ("Term (Periods)", 1, 6), ("Payment", 1, 8),
            ("Client", 2, 0), ("Contact", 2, 2), ("Location", 2, 4), ("Disbursed", 2, 6), ("Status", 2, 8)
        ]

        for text, r, c in labels_layout:
            ctk.CTkLabel(self.sched_summary_frame, text=text, font=("Segoe UI", 11), text_color=TEXT_MUTED).grid(row=r, column=c, sticky="w", padx=(10, 2), pady=2)
            val_lbl = ctk.CTkLabel(self.sched_summary_frame, text="--", font=("Segoe UI", 12, "bold"))
            val_lbl.grid(row=r, column=c+1, sticky="w", padx=(0, 10), pady=2)
            self.summary_labels[text] = val_lbl

        # Reordered columns and renamed "Month" to "Installment"
        self.sched_table = DataTable(tab, columns=[
            ("installment", "Installment"),
            ("due_date", "Due Date"),
            ("total_due", "Payment"),
            ("principal", "Principal"),
            ("interest", "Interest"),
            ("end_balance", "Balance"),
            ("status", "Status")
        ], title="Amortisation Schedule", show_summary=False)
        
        self.sched_table.pack(fill="both", expand=True, padx=20, pady=(10, 20))
        self._refresh_amortisation_list()

    def _refresh_amortisation_list(self):
        active_loans = loan_model.list_loans(self.conn, status="Active", only_with_balance=True)
        self.sched_lookup = {f"{l['loan_no']} - {l['first_name']} {l['last_name']}": l["id"] for l in active_loans}
        self.sched_loan.set_values(list(self.sched_lookup.keys()))

    def _load_schedule(self):
        try:
            loan_id = self.sched_lookup.get(self.sched_loan.get())
            if not loan_id: raise ValueError("Select a valid loan.")
            
            schedule = loan_model.get_amortisation_schedule(self.conn, loan_id)
            loan = loan_model.get_loan(self.conn, loan_id)
            
            # Calculate capitalized upfront totals
            total_principal = sum(s["principal_due"] for s in schedule)
            total_interest = sum(s["interest_due"] for s in schedule)
            running_balance = total_principal + total_interest
            
            self.sched_summary_frame.pack(fill="x", padx=20, pady=(10, 0), before=self.sched_table)
            self.lbl_sum_title.configure(text=f"LOAN SUMMARY: {loan['loan_no']}")
            
            standard_payment = schedule[0]["principal_due"] + schedule[0]["interest_due"] if schedule else 0

            self.summary_labels["Loan Amount"].configure(text=money(running_balance))
            self.summary_labels["Rate (Monthly)"].configure(text=f"{loan['interest_rate']}%")
            self.summary_labels["Method"].configure(text=loan["interest_method"].replace("_", " ").title())
            self.summary_labels["Term (Periods)"].configure(text=str(loan["term_months"]))
            self.summary_labels["Payment"].configure(text=money(standard_payment))
            
            self.summary_labels["Client"].configure(text=f"{loan['first_name']} {loan['last_name']}")
            self.summary_labels["Contact"].configure(text=loan["phone"] or "-")
            self.summary_labels["Location"].configure(text=loan["location"] or "-")
            self.summary_labels["Disbursed"].configure(text=loan["disbursement_date"] or "-")
            self.summary_labels["Status"].configure(text=loan["status"])

            processed_rows = []
            
            # Row 0: Initial balance before payments
            processed_rows.append({
                "installment": "-",
                "due_date": "-",
                "total_due": "-",
                "principal": "-",
                "interest": "-",
                "end_balance": money(running_balance),
                "status": "-"
            })
            
            for i, s in enumerate(schedule):
                # Theoretical scheduled payment due
                installment_total = s["principal_due"] + s["interest_due"]
                
                # Decline balance by the scheduled installment amount
                ending_balance = running_balance - installment_total
                
                # Prevent a residual negative cent from showing on the last row
                if ending_balance < 0:
                    ending_balance = 0
                
                processed_rows.append({
                    "installment": str(i + 1),
                    "due_date": s["due_date"],
                    "total_due": money(installment_total),
                    "principal": money(s["principal_due"]),
                    "interest": money(s["interest_due"]),
                    "end_balance": money(ending_balance),
                    "status": s["status"].title()
                })
                
                running_balance = ending_balance
                
            self.sched_table.set_rows(processed_rows)
            
            # Incorporate the loan summary directly into the PDF metadata block
            self.sched_table.pdf_title = f"Amortisation Schedule - {loan['loan_no']}"
            
            meta_lines = [
                f"LOAN SUMMARY: {loan['loan_no']}",
                f"Client: {loan['first_name']} {loan['last_name']}    Contact: {loan['phone'] or '-'}    Location: {loan['location'] or '-'}",
                f"Loan Amount: {money(total_principal + total_interest)}    Rate (Monthly): {loan['interest_rate']}%    Method: {loan['interest_method'].replace('_', ' ').title()}",
                f"Term (Periods): {loan['term_months']}    Payment: {money(standard_payment)}    Status: {loan['status']}",
                f"Disbursed: {loan['disbursement_date'] or '-'}    Maturity: {loan['maturity_date'] or '-'}",
                f"--------------------------------------------------------------------------------"
            ]
            
            self.sched_table.set_pdf_meta(meta_lines)
            
        except Exception as e:
            error(str(e))

    def _apply_product_defaults(self, name):
        if name not in self.product_lookup:
            return
        p = self.product_lookup[name]
        self.nl_rate.delete(0, "end")
        self.nl_rate.insert(0, str(p["interest_rate"]))
        self.nl_method.set(p["interest_method"])
        self.nl_freq.set(p["repayment_frequency"])
        if hasattr(self, "_toggle_phase2_fields"):
            self._toggle_phase2_fields()
        self._recompute_fees()

    def _on_client_selected(self, client_key=None):
        self._recompute_fees()

    def _recompute_fees(self):
        """
        Auto-fills the Admin Fee, and - for a brand-new client only (one
        with no prior loans at all, see loans.is_new_client()) - the
        Application Fee, from the selected loan product's percentages, as
        principal * pct / 100. Called whenever the client, product, or
        principal changes, in whichever order they're filled in, so
        neither fee is left stale no matter the order fields are entered.
        Both fields stay plain editable entries, so any auto-filled value
        can still be overridden by hand before submitting.
        """
        prod = self.product_lookup.get(self.nl_product.get())
        if not prod:
            return
        try:
            principal = float(self.nl_principal.get())
        except (ValueError, TypeError):
            return

        admin_pct = prod["admin_fee_pct"] or 0
        if admin_pct:
            admin_fee = principal * admin_pct / 100.0
            self.nl_admin_fee.delete(0, "end")
            self.nl_admin_fee.insert(0, f"{admin_fee:.2f}")

        app_pct = prod["application_fee_pct"] or 0
        if app_pct:
            client_id = self.client_lookup.get(self.nl_client.get())
            if client_id is not None and loan_model.is_new_client(self.conn, client_id):
                app_fee = principal * app_pct / 100.0
                self.nl_app_fee.delete(0, "end")
                self.nl_app_fee.insert(0, f"{app_fee:.2f}")


    def _approve_selected_loans(self):
        if not perm_model.has_permission(self.conn, Session.current_user, "Loans", "approve"):
            return error("You do not have permission to approve loans.")
        selected = self.approvals_table.selected_rows()
        if not selected:
            return error("Select at least one loan to approve.")

        # Verify all are pending approval
        invalid = []
        for row in selected:
            loan = loan_model.get_loan(self.conn, int(row["id"]))
            if not loan or loan["approval_status"] != "Pending":
                invalid.append(row["loan_no"])
        if invalid:
            return error(f"The following loans are not pending approval:\n{', '.join(invalid)}")

        rollover_flags = [bool(self._pending_rollover_for_loan(int(row["id"]))) for row in selected]
        if any(rollover_flags) and not all(rollover_flags):
            return error("Rollover requests and new loan applications need different approval details - "
                        "please approve them in separate batches.")
        is_rollover_batch = all(rollover_flags)
        if is_rollover_batch and not perm_model.has_permission(self.conn, Session.current_user, "Rollovers", "approve"):
            return error("You do not have permission to approve rollovers.")

        from datetime import date
        if is_rollover_batch:
            fields = [{"key": "rollover_date", "label": "Rollover Date", "type": "date",
                    "default": date.today().isoformat()}]
        else:
            fields = [
                {"key": "disbursement_date", "label": "Disbursement Date", "type": "date",
                "default": date.today().isoformat()},
                {"key": "method", "label": "Method", "type": "combobox",
                "options": ["Cash", "Bank Transfer", "Mobile Money"], "default": "Cash"},
                {"key": "reference", "label": "Reference (optional, applied to all)"},
            ]

        def process(values):
            success, errors = 0, 0
            if is_rollover_batch:
                batch_date = values["rollover_date"]
                for row in selected:
                    try:
                        rollover = self._pending_rollover_for_loan(int(row["id"]))
                        rollover_model.approve_rollover(
                            self.conn, rollover["id"],
                            approved_by=Session.current_user["id"],
                            approval_date=batch_date,
                        )
                        success += 1
                    except Exception as e:
                        errors += 1
                        error(f"Failed to approve rollover for loan {row['loan_no']}: {str(e)}")
                info(f"{success} rollover(s) approved and completed on {batch_date}."
                    + (f" {errors} failed." if errors else ""))
            else:
                batch_date = values["disbursement_date"]
                method = values["method"]
                batch_reference = (values.get("reference") or "").strip() or None
                for row in selected:
                    try:
                        loan_id = int(row["id"])
                        loan = loan_model.get_loan(self.conn, loan_id)
                        if not loan:
                            raise ValueError("Loan not found")
                        disp_date = loan["disbursement_date"] or batch_date
                        if not disp_date:
                            raise ValueError("No disbursement date available")

                        loan_model.set_approval_status(self.conn, loan_id, "Approved",
                                                    approved_by=Session.current_user["id"])
                        disb_model.disburse_loan(
                            self.conn,
                            loan_id=loan_id,
                            amount=loan["principal"],
                            disbursement_date=disp_date,
                            method=method,
                            first_due_date=None,
                            reference=batch_reference,
                            user_id=Session.current_user["id"],
                        )
                        success += 1
                    except Exception as e:
                        errors += 1
                        error(f"Failed to approve loan {row['loan_no']}: {str(e)}")

                info(f"{success} loan(s) approved and disbursed successfully." + (f" {errors} failed." if errors else ""))

            self._refresh_approvals()
            self._refresh_loans()
            self._refresh_repayment_list()
            self._refresh_statement_list()
            self._refresh_amortisation_list()

        FormDialog(self, "Approve Selected Rollovers" if is_rollover_batch else "Approve Selected Loans",
                fields, process, height=130 if is_rollover_batch else 160)



    def _decline_selected_loans(self):
        if not perm_model.has_permission(self.conn, Session.current_user, "Loans", "approve"):
            return error("You do not have permission to decline loans.")
        selected = self.approvals_table.selected_rows()
        if not selected:
            return error("Select at least one loan to decline.")

        has_rollover = any(self._pending_rollover_for_loan(int(row["id"])) for row in selected)
        if has_rollover and not perm_model.has_permission(self.conn, Session.current_user, "Rollovers", "approve"):
            return error("You do not have permission to decline rollovers - deselect them and try again, "
                        "or ask someone with Rollovers approval rights.")

        if not confirm(f"Decline {len(selected)} loan(s)/rollover request(s)?"):
            return

        success, errors = 0, 0
        for row in selected:
            try:
                loan_id = int(row["id"])
                rollover = self._pending_rollover_for_loan(loan_id)
                if rollover:
                    rollover_model.reject_rollover(self.conn, rollover["id"],
                                                    rejected_by=Session.current_user["id"])
                else:
                    loan_model.set_approval_status(self.conn, loan_id, "Declined",
                                                approved_by=Session.current_user["id"])
                success += 1
            except Exception as e:
                errors += 1
                error(f"Failed to decline loan {row['loan_no']}: {str(e)}")
        info(f"{success} declined." + (f" {errors} failed." if errors else ""))
        self._refresh_approvals()
        self._refresh_loans()

    def _toggle_phase2_fields(self, event=None):
        if hasattr(self, 'phase2_frame'):
            if self.nl_method.get() == "interest_only_then_flat":
                self.phase2_frame.pack(fill="x", pady=(0, 15))
            else:
                self.phase2_frame.pack_forget()
        


# =====================================================================
# ROLLOVERS
# =====================================================================
class RolloversView(BaseView):
    def __init__(self, master, conn, app):
        super().__init__(master, conn, app)
        self.header("Rolled Over Loans")
        bar = self.toolbar()
        ctk.CTkButton(bar, text="+ New Rollover", command=self._new_rollover).pack(side="left")
        ctk.CTkButton(bar, text="↩ Reverse Selected", fg_color="#EB5757", hover_color="#C0392B",
                      command=self._reverse_rollover).pack(side="left", padx=6)

        self.table = DataTable(self, columns=[
            ("original_loan_no", "Original Loan"), ("new_loan_no", "New Loan"),
            ("client", "Client"), ("rollover_date", "Date"), ("outstanding_balance", "Balance Rolled"),
            ("reason", "Reason"),
        ])
        self.table.pack(fill="both", expand=True)
        self.refresh()

    def refresh(self):
        rows = rollover_model.list_rollovers(self.conn)
        self.table.set_rows([{
            "original_loan_no": r["original_loan_no"], "new_loan_no": r["new_loan_no"],
            "client": f"{r['first_name']} {r['last_name']}", "rollover_date": r["rollover_date"],
            "outstanding_balance": money(r["outstanding_balance"]), "reason": r["reason"] or "",
        } for r in rows])

    def _new_rollover(self):
        active_loans = loan_model.list_loans(self.conn, status="Active", only_with_balance=True)
        lookup = {f"{l['loan_no']} - {l['first_name']} {l['last_name']}": l for l in active_loans}
        if not lookup:
            error("No active loans available to roll over.")
            return

        state = {"loan": None}

        # Defined locally to be bound to the specific field inside the schema
        def on_loan_selected(value):
            loan = lookup.get(value)
            state["loan"] = loan
            if not loan:
                return
            
            bal = loan_model.outstanding_balance(self.conn, loan["id"])
            
            # Access dynamic widgets to update their states based on selection
            principal_widget = form_dialog.get_widget("principal")
            freq_widget = form_dialog.get_widget("repayment_frequency")
            
            if principal_widget:
                principal_widget.configure(state="normal")
                principal_widget.delete(0, "end")
                principal_widget.insert(0, money_edit_str(bal['total']))
                principal_widget.configure(state="disabled")
                
            if freq_widget:
                freq_widget.set(loan["repayment_frequency"])

        schema = [
            {
                "title": "Target Loan & Balance",
                "color": "#1A3B5C", # Dark Navy
                "rows": [
                    [
                        {"key": "active_loan", "label": "ACTIVE LOAN*", "type": "searchable", 
                         "options": list(lookup.keys()), "command": on_loan_selected}
                    ]
                ]
            },
            {
                "title": "New Loan Terms",
                "color": "#5C3A1A", # Dark Amber
                "rows": [
                    [
                        {"key": "principal", "label": "NEW LOAN PRINCIPAL", "state": "disabled", 
                         "placeholder": "Auto-filled from outstanding balance"},
                        {"key": "interest_rate", "label": "NEW INTEREST RATE (%)*"}
                    ],
                    [
                        {"key": "interest_method", "label": "INTEREST METHOD*", "type": "combobox", 
                         "options": ["flat", "reducing_balance", "interest_only_balloon"]},
                        {"key": "repayment_frequency", "label": "REPAYMENT FREQUENCY*", "type": "combobox", 
                         "options": ["monthly", "biweekly", "weekly"]},
                        {"key": "term_months", "label": "NEW TERM (PERIODS)*"}
                    ]
                ]
            },
            {
                "title": "Fees & Justification",
                "color": "#1A5C3A", # Dark Teal
                "rows": [
                    [
                        {"key": "rollover_fee", "label": "ROLLOVER FEE", "type": "money", "placeholder": "0.00 - charged once approved"}
                    ],
                    [
                        {"key": "reason", "label": "REASON", "type": "textarea"}
                    ]
                ]
            }
        ]

        def submit(values):
            try:
                loan = state["loan"]
                if not loan:
                    raise ValueError("Select a valid active loan.")
                
                fee_text = values["rollover_fee"]
                rollover_fee = parse_money(fee_text) if fee_text else 0
                if rollover_fee < 0:
                    raise ValueError("Rollover fee cannot be negative.")
                
                new_loan_data = {
                    "interest_rate": float(values["interest_rate"]),
                    "interest_method": values["interest_method"],
                    "term_months": int(values["term_months"]),
                    "repayment_frequency": values["repayment_frequency"],
                    "officer_id": Session.current_user["id"],
                    "admin_fee": 0,
                }
                
                result = rollover_model.request_rollover(
                    self.conn, loan["id"], new_loan_data,
                    reason=values["reason"],
                    requested_by=Session.current_user["id"],
                    rollover_fee=rollover_fee,
                )
                
                info(f"Rollover request submitted for loan {loan['loan_no']} (rolled balance {money(result['rolled_balance'])}).")
                form_dialog.destroy()
                self.refresh()
            except Exception as e:
                error(str(e))

        form_dialog = SectionedFormDialog(self, "New Rollover Request", schema, submit)

    def _reverse_rollover(self):
        """Reverse a rollover: delete the new loan, restore the original."""
        if not perm_model.has_permission(self.conn, Session.current_user, "Rollovers", "approve"):
            error("You do not have permission to reverse rollovers.")
            return

        row = self.table.selected_row()
        if not row:
            error("Select a rollover record first.")
            return

        original_loan_no = row["original_loan_no"]
        new_loan_no = row["new_loan_no"]

        # Fetch the rollover ID from the database
        rollover = self.conn.execute(
            "SELECT id FROM rollovers "
            "WHERE original_loan_id = (SELECT id FROM loans WHERE loan_no = ?) "
            "AND new_loan_id = (SELECT id FROM loans WHERE loan_no = ?)",
            (original_loan_no, new_loan_no)
        ).fetchone()
        if not rollover:
            error("Rollover record not found.")
            return

        if not confirm(
            f"Reverse the rollover of loan {original_loan_no} into {new_loan_no}?\n\n"
            "This will delete the new loan and all its records, and restore the original loan to Active.\n"
            "The original loan's repayment schedule will be rebuilt and all repayments made before the rollover will be reapplied.\n\n"
            "This action cannot be undone."
        ):
            return

        try:
            from ..models import rollovers as rollover_model
            result = rollover_model.reverse_rollover(self.conn, rollover["id"], user_id=Session.current_user["id"])
            info(result["message"])
            self.refresh()
        except Exception as e:
            error(str(e))

# =====================================================================
# BAD DEBTS
# =====================================================================
# =====================================================================
# BAD DEBTS
# =====================================================================
class BadDebtsView(BaseView):
    def __init__(self, master, conn, app):
        super().__init__(master, conn, app)
        self.header("Bad Debts & Recoveries")
        self.tabs = ctk.CTkTabview(self)
        self.tabs.pack(fill="both", expand=True)
        self.tabs.add("Bad Debts")
        self.tabs.add("Recoveries")
        self._build_bad_debts(self.tabs.tab("Bad Debts"))
        self._build_recoveries(self.tabs.tab("Recoveries"))

    def _build_bad_debts(self, tab):
        bar = ctk.CTkFrame(tab, fg_color="transparent")
        bar.pack(fill="x", pady=6)
        ctk.CTkButton(bar, text="Write Off a Loan", command=self._write_off).pack(side="left")
        ctk.CTkButton(bar, text="Refresh", command=self._refresh_bad_debts).pack(side="left", padx=6)
        
        # Bulk Upload Buttons for Bad Debts
        ctk.CTkButton(bar, text="Download Template", fg_color="gray40", command=self._download_bd_template).pack(side="left", padx=(15, 6))
        ctk.CTkButton(bar, text="Bulk Upload Write-offs", fg_color="#27AE60", command=self._bulk_upload_bd).pack(side="left")

        self.bd_table = DataTable(tab, columns=[
            ("loan_no", "Loan #"), 
            ("client_name", "Client"), 
            ("date_written_off", "Date"),
            ("principal_written_off", "Principal"), 
            ("interest_written_off", "Interest"),
            ("amount_written_off", "Total Written Off"), 
            ("total_recovered", "Recovered"), 
            ("status", "Status"),
        ])
        self.bd_table.pack(fill="both", expand=True)
        self._refresh_bad_debts()

    def _refresh_bad_debts(self):
        rows = bd_model.list_bad_debts(self.conn)
        self.bd_table.set_rows([{
            "loan_no": r["loan_no"], 
            "client_name": f"{r['first_name']} {r['last_name']}",
            "date_written_off": r["date_written_off"], 
            # Convert sqlite3.Row to a dict first so we can safely use .get(),
            # and add 'or 0' in case the database returns None instead of 0
            "principal_written_off": money(dict(r).get("principal_written_off") or 0),
            "interest_written_off": money(dict(r).get("interest_written_off") or 0),
            "amount_written_off": money(r["amount_written_off"]),
            "total_recovered": money(r["total_recovered"]), 
            "status": r["status"],
        } for r in rows])
        
    def _write_off(self):
        if not perm_model.has_permission(self.conn, Session.current_user, "Bad Debts", "approve"):
            error("You do not have permission to write off loans.")
            return
        active_loans = loan_model.list_loans(self.conn, status="Active", only_with_balance=True)
        lookup = {f"{l['loan_no']} - {l['first_name']} {l['last_name']}": l["id"] for l in active_loans}
        if not lookup:
            error("No active loans available to write off.")
            return
        fields = [
            {"key": "loan", "label": "Active Loan*", "type": "searchable", "options": list(lookup.keys())},
            {"key": "date_written_off", "label": "Date Written Off", "type": "date", "default": date.today().isoformat()},
            {"key": "reason", "label": "Reason", "type": "textarea"},
        ]

        def submit(values):
            if values["loan"] not in lookup:
                raise ValueError("Select a valid active loan.")
            if not confirm("This will write off the full outstanding balance of the selected loan. Continue?"):
                return
            bd_model.write_off_loan(
                self.conn, 
                lookup[values["loan"]], 
                date_written_off=values["date_written_off"],
                reason=values["reason"],
                approved_by=Session.current_user["id"]
            )
            info("Loan written off as bad debt.")
            self._refresh_bad_debts()

        FormDialog(self, "Write Off Loan", fields, submit)

    def _download_bd_template(self):
        _download_csv_template(
            ["loan_no", "date_written_off", "reason"],
            "bad_debts_template.csv",
        )

    def _bulk_upload_bd(self):
        if not perm_model.has_permission(self.conn, Session.current_user, "Bad Debts", "approve"):
            return error("You do not have permission to write off loans.")
        
        rows = _pick_csv_upload()
        if rows is None:
            return
            
        success, errors = 0, []
        active_loans = loan_model.list_loans(self.conn, status="Active", only_with_balance=True)
        lookup = {l["loan_no"]: l["id"] for l in active_loans}

        for i, row in enumerate(rows, start=2):
            try:
                loan_no = (row.get("loan_no") or "").strip()
                if not loan_no:
                    raise ValueError("loan_no is required.")
                    
                loan_id = lookup.get(loan_no)
                if not loan_id:
                    raise ValueError(f"No active loan found with loan_no '{loan_no}', or it has a zero balance.")

                reason = (row.get("reason") or "").strip()
                date_written_off = (row.get("date_written_off") or "").strip() or date.today().isoformat()

                bd_model.write_off_loan(
                    self.conn, 
                    loan_id, 
                    date_written_off=date_written_off,
                    reason=reason,
                    approved_by=Session.current_user["id"]
                )
                success += 1
            except Exception as e:
                errors.append(f"Row {i}: {e}")
                
        _show_bulk_result("loan(s) written off", success, errors)
        self._refresh_bad_debts()

    def _build_recoveries(self, tab):
        bar = ctk.CTkFrame(tab, fg_color="transparent")
        bar.pack(fill="x", pady=6)
        ctk.CTkButton(bar, text="Record Recovery", command=self._record_recovery).pack(side="left")
        ctk.CTkButton(bar, text="Refresh", command=self._refresh_recoveries).pack(side="left", padx=6)
        
        # Bulk Upload Buttons for Recoveries
        ctk.CTkButton(bar, text="Download Template", fg_color="gray40", command=self._download_rec_template).pack(side="left", padx=(15, 6))
        ctk.CTkButton(bar, text="Bulk Upload Recoveries", fg_color="#27AE60", command=self._bulk_upload_rec).pack(side="left")

        self.rec_table = DataTable(tab, columns=[
            ("loan_no", "Loan #"), ("recovery_date", "Date"), ("amount", "Amount"),
            ("method", "Method"), ("reference", "Reference"),
        ])
        self.rec_table.pack(fill="both", expand=True)
        self._refresh_recoveries()

    def _refresh_recoveries(self):
        rows = bd_model.list_recoveries(self.conn)
        self.rec_table.set_rows([{
            "loan_no": r["loan_no"], "recovery_date": r["recovery_date"], "amount": money(r["amount"]),
            "method": r["method"], "reference": r["reference"] or "",
        } for r in rows])

    def _record_recovery(self):
        bad_debts = bd_model.list_bad_debts(self.conn)
        open_debts = [b for b in bad_debts if b["status"] != "FullyRecovered"]
        lookup = {f"{b['loan_no']} - {b['first_name']} {b['last_name']} (Owed {money(b['amount_written_off'] - b['total_recovered'])})": b["id"]
                  for b in open_debts}
        if not lookup:
            error("No outstanding bad debts to recover.")
            return
            
        fields = [
            {"key": "bad_debt", "label": "Bad Debt*", "type": "searchable", "options": list(lookup.keys())},
            {"key": "amount", "label": "Amount Recovered*", "type": "money"},
            # Added the DatePicker field here defaulting to today
            {"key": "recovery_date", "label": "Recovery Date", "type": "date", "default": date.today().isoformat()},
            {"key": "method", "label": "Method", "type": "combobox",
             "options": ["Cash", "Bank Transfer", "Mobile Money", "Cheque"]},
            {"key": "reference", "label": "Reference"},
        ]

        def submit(values):
            if values["bad_debt"] not in lookup:
                raise ValueError("Select a valid bad debt record.")
            bd_model.record_recovery(
                self.conn, lookup[values["bad_debt"]], amount=parse_money(values["amount"]),
                recovery_date=values["recovery_date"], # Pass the extracted date to the model
                method=values["method"], reference=values["reference"],
                user_id=Session.current_user["id"],
            )
            info("Recovery recorded.")
            self._refresh_recoveries()
            self._refresh_bad_debts()

        FormDialog(self, "Record Bad Debt Recovery", fields, submit)
        
            
    def _download_rec_template(self):
        _download_csv_template(
            ["loan_no", "recovery_date", "amount", "method", "reference"],
            "bad_debts_recovery_template.csv",
        )

    def _bulk_upload_rec(self):
        rows = _pick_csv_upload()
        if rows is None:
            return
            
        success, errors = 0, []
        bad_debts = bd_model.list_bad_debts(self.conn)
        open_debts = {b["loan_no"]: b for b in bad_debts if b["status"] != "FullyRecovered"}

        for i, row in enumerate(rows, start=2):
            try:
                loan_no = (row.get("loan_no") or "").strip()
                if not loan_no:
                    raise ValueError("loan_no is required.")
                    
                bd_record = open_debts.get(loan_no)
                if not bd_record:
                    raise ValueError(f"No outstanding bad debt found for loan_no '{loan_no}'.")

                amount_str = str(row.get("amount", "")).strip()
                if not amount_str:
                    raise ValueError("amount is required.")
                amount = parse_money(amount_str)
                
                # Extract the recovery date if provided in the CSV
                recovery_date = (row.get("recovery_date") or "").strip() or None

                method = (row.get("method") or "").strip() or "Cash"
                reference = (row.get("reference") or "").strip()

                bd_model.record_recovery(
                    self.conn, bd_record["id"], amount=amount,
                    recovery_date=recovery_date, # Pass the date to the backend
                    method=method, reference=reference,
                    user_id=Session.current_user["id"]
                )
                success += 1
            except Exception as e:
                errors.append(f"Row {i}: {e}")
                
        _show_bulk_result("recovery(ies) recorded", success, errors)
        self._refresh_recoveries()
        self._refresh_bad_debts()

# =====================================================================
# EXPENSES
# =====================================================================
class ExpensesView(BaseView):
    def __init__(self, master, conn, app):
        super().__init__(master, conn, app)
        self.header("Expenses")
        bar = self.toolbar()
        ctk.CTkButton(bar, text="+ Record Expense", command=self._new_expense).pack(side="left")
        ctk.CTkButton(bar, text="+ New Category", command=self._new_category).pack(side="left", padx=6)

        self.table = DataTable(self, columns=[
            ("expense_date", "Date"), ("category_name", "Category"), ("amount", "Amount"),
            ("paid_to", "Paid To"), ("description", "Description"),
        ])
        self.table.pack(fill="both", expand=True)
        self.refresh()

    def refresh(self):
        rows = expense_model.list_expenses(self.conn)
        self.table.set_rows([{
            "expense_date": e["expense_date"], "category_name": e["category_name"],
            "amount": money(e["amount"]), "paid_to": e["paid_to"] or "", "description": e["description"] or "",
        } for e in rows])

    def _new_category(self):
        fields = [{"key": "name", "label": "Category Name*"}, {"key": "description", "label": "Description"}]

        def submit(values):
            if not values["name"]:
                raise ValueError("Category name is required.")
            expense_model.create_category(self.conn, values["name"], values.get("description"))
            info("Category created.")

        FormDialog(self, "New Expense Category", fields, submit)

    def _new_expense(self):
        categories = expense_model.list_categories(self.conn)
        lookup = {c["name"]: c["id"] for c in categories}
        if not lookup:
            error("Create an expense category first.")
            return
        fields = [
            {"key": "category", "label": "Category*", "type": "combobox", "options": list(lookup.keys())},
            {"key": "amount", "label": "Amount*", "type": "money"},
            {"key": "expense_date", "label": "Date", "type": "date", "default": date.today().isoformat()},
            {"key": "paid_to", "label": "Paid To"},
            {"key": "reference", "label": "Reference"},
            {"key": "description", "label": "Description", "type": "textarea"},
        ]

        def submit(values):
            expense_model.record_expense(
                self.conn, lookup[values["category"]], amount=parse_money(values["amount"]),
                expense_date=values["expense_date"] or None, paid_to=values["paid_to"],
                description=values["description"], reference=values["reference"],
                user_id=Session.current_user["id"],
            )
            info("Expense recorded.")
            self.refresh()

        FormDialog(self, "Record Expense", fields, submit)


# =====================================================================
# REPORTS
# =====================================================================


# Assuming BaseView, DataTable, money, error, and report_model are imported/available

class ReportsView(BaseView):
    def __init__(self, master, conn, app):
        super().__init__(master, conn, app)
        self.header("Reports")
        
        self.container = ctk.CTkFrame(self, fg_color="transparent")
        self.container.pack(fill="both", expand=True, padx=10, pady=10)

        # Draggable divider between the reports sidebar and the report
        # content frame, so the sidebar can be made wider/narrower to taste.
        self.split = resizable_split(self.container, orient="horizontal", bg=NAVY_DEEP)
        self.split.pack(fill="both", expand=True)

        # tk.PanedWindow can only manage direct child widgets, and
        # CTkScrollableFrame is internally a canvas + inner frame rather
        # than a single widget - so it can't be added to the pane
        # directly. Give it a plain CTkFrame host to live in instead,
        # the same pattern used for the main sidebar's nav_scroll.
        sidebar_host = ctk.CTkFrame(self.split, corner_radius=8, fg_color="transparent")
        self.sidebar = ctk.CTkScrollableFrame(sidebar_host, corner_radius=8)
        self.sidebar.pack(fill="both", expand=True)

        self.content_frame = ctk.CTkFrame(self.split, corner_radius=8, fg_color=("gray95", "gray15"))

        self.split.add(sidebar_host, width=220, minsize=180)
        self.split.add(self.content_frame, minsize=400, stretch="always")
        
        self.report_pages = {
            "Fund Position Report": self._build_fund_position,
            "Arrears Report": self._build_arrears,
            "Past Maturity Report": self._build_past_maturity,
            "Interest Received": self._build_interest_received,
            "Interest Due": self._build_interest_due,
            "Admin Fees": self._build_admin_fees,
            "Application Fees": self._build_application_fees,
            "Clients Due Per Day": self._build_clients_due_per_day,
            "Expected Collections": self._build_expected_collections,
            "Bad Debts Report": self._build_bad_debts_report,
            "Bad Debts Recovery Report": self._build_bad_debts_recovery_report,
            "Disbursement Report": self._build_disbursement_report,
            "Repayment Report": self._build_repayment_report,
            "Loan Statements Report": self._build_loan_statements_report,
            "Rollover Report": self._build_rollover_report,
            "Rollover Fee Report": self._build_rollover_fee_report,
            "Location Summary Report": self._build_location_summary,
        }
        
        self._build_sidebar()
        self.current_btn = None
        self._show_report("Arrears Report")

    def _build_sidebar(self):
        ctk.CTkLabel(self.sidebar, text="Available Reports", font=("Segoe UI", 16, "bold")).pack(pady=(10, 15), anchor="w", padx=10)
        self.nav_buttons = {}
        for rep_name in self.report_pages.keys():
            btn = ctk.CTkButton(
                self.sidebar, 
                text=rep_name, 
                anchor="w", 
                fg_color="transparent",
                text_color=("gray10", "gray90"),
                hover_color=("gray80", "gray30"),
                command=lambda n=rep_name: self._show_report(n)
            )
            btn.pack(fill="x", pady=2, padx=5)
            self.nav_buttons[rep_name] = btn

    def _show_report(self, report_name):
        if self.current_btn:
            self.current_btn.configure(fg_color="transparent")
        self.current_btn = self.nav_buttons[report_name]
        self.current_btn.configure(fg_color=("gray75", "gray25"))

        for widget in self.content_frame.winfo_children():
            widget.destroy()

        header = ctk.CTkLabel(self.content_frame, text=report_name, font=("Segoe UI", 22, "bold"))
        header.pack(anchor="w", padx=20, pady=(20, 10))

        builder_func = self.report_pages[report_name]
        builder_func(self.content_frame)

        for widget in self.content_frame.winfo_children():
            if isinstance(widget, DataTable):
                widget.pdf_title = report_name

    def _create_control_bar(self, parent):
        bar = ctk.CTkFrame(parent, fg_color=("gray85", "gray20"), corner_radius=8)
        bar.pack(fill="x", padx=20, pady=(0, 15))
        return bar

    # ----- Individual report builders (all with DatePicker) -----

    def _build_arrears(self, parent):
        bar = self._create_control_bar(parent)
        ctk.CTkButton(bar, text="Generate Report", command=self._load_arrears).pack(side="left", padx=15, pady=15)
        table = DataTable(parent, columns=[
            ("loan_no", "Loan #"), ("client_name", "Client"), ("phone", "Phone"), ("location", "Location"),
            ("aging_bucket", "Aging Bucket"), ("max_days_overdue", "Days Overdue"),
            ("amount_overdue", "Overdue Amount"), ("outstanding_balance", "Total Outstanding"),
        ], show_summary=True)
        table.pack(fill="both", expand=True, padx=20, pady=(0, 20))
        self.arrears_table = table
        self._load_arrears()

    def _load_arrears(self):
        rows = report_model.arrears_report(self.conn)
        for r in rows:
            r["amount_overdue"] = money(r["amount_overdue"])
            r["outstanding_balance"] = money(r["outstanding_balance"])
        self.arrears_table.set_rows(rows)

    
    def _build_past_maturity(self, parent):
        bar = self._create_control_bar(parent)
        ctk.CTkButton(bar, text="Generate Report", command=self._load_past_maturity).pack(side="left", padx=15, pady=15)
        table = DataTable(parent, columns=[
            ("loan_no", "Loan ID"), ("client", "Client"), ("maturity_date", "Maturity Date"),
            ("ageing_days", "Ageing (Days)"), ("location", "Location"), ("balance", "Balance"), ("contact", "Contact"),
        ], show_summary=True)
        table.pack(fill="both", expand=True, padx=20, pady=(0, 20))
        self.past_maturity_table = table
        self._load_past_maturity()

    def _load_past_maturity(self):
        rows = report_model.past_maturity_report(self.conn)
        for r in rows:
            r["balance"] = money(r["balance"])
        self.past_maturity_table.set_rows(rows)

    def _build_interest_received(self, parent):
        bar = self._create_control_bar(parent)
        input_frame = ctk.CTkFrame(bar, fg_color="transparent")
        input_frame.pack(side="left", padx=15, pady=15)
        ctk.CTkLabel(input_frame, text="From:").pack(side="left", padx=(0, 5))
        self.int_recv_from = DatePicker(input_frame, width=140, default="")
        self.int_recv_from.pack(side="left", padx=(0, 15))
        ctk.CTkLabel(input_frame, text="To:").pack(side="left", padx=(0, 5))
        self.int_recv_to = DatePicker(input_frame, width=140, default="")
        self.int_recv_to.pack(side="left", padx=(0, 15))
        ctk.CTkButton(input_frame, text="Generate", command=self._load_interest_received).pack(side="left")
        self.int_recv_total = ctk.CTkLabel(bar, text="Total: --", font=("Segoe UI", 16, "bold"), text_color="#1F6AA5")
        self.int_recv_total.pack(side="right", padx=20)
        table = DataTable(parent, columns=[
            ("date", "Date"), ("loan_no", "Loan #"), ("client", "Client"),
            ("location", "Location"), ("amount", "Amount"),
        ], show_summary=True)
        table.pack(fill="both", expand=True, padx=20, pady=(0, 20))
        self.interest_received_table = table

    def _load_interest_received(self):
        from_date = self.int_recv_from.get() or None
        to_date = self.int_recv_to.get() or None
        data = report_model.interest_received_report(self.conn, date_from=from_date, date_to=to_date)
        self.int_recv_total.configure(text=f"Total: {money(data['total'])}  ({data['count']} txns)")
        self.interest_received_table.set_rows([{
            "date": r["date"], "loan_no": r["loan_no"], "client": r["client"],
            "location": r["location"], "amount": money(r["amount"]),
        } for r in data["rows"]])

    def _build_interest_due(self, parent):
        bar = self._create_control_bar(parent)
        ctk.CTkButton(bar, text="Generate Report", command=self._load_interest_due).pack(side="left", padx=15, pady=15)
        self.int_due_total = ctk.CTkLabel(bar, text="Total: --", font=("Segoe UI", 16, "bold"), text_color="#1F6AA5")
        self.int_due_total.pack(side="right", padx=20)
        table = DataTable(parent, columns=[
            ("loan_no", "Loan #"), ("client", "Client"), ("location", "Location"), ("amount", "Amount"),
        ], show_summary=True)
        table.pack(fill="both", expand=True, padx=20, pady=(0, 20))
        self.interest_due_table = table

    def _load_interest_due(self):
        data = report_model.interest_due_report(self.conn)
        self.int_due_total.configure(text=f"Total: {money(data['total'])}  ({data['count']} loans)")
        self.interest_due_table.set_rows([{
            "loan_no": r["loan_no"], "client": r["client"],
            "location": r["location"], "amount": money(r["amount"]),
        } for r in data["rows"]])

    def _build_admin_fees(self, parent):
        bar = self._create_control_bar(parent)
        input_frame = ctk.CTkFrame(bar, fg_color="transparent")
        input_frame.pack(side="left", padx=15, pady=15)
        ctk.CTkLabel(input_frame, text="From:").pack(side="left", padx=(0, 5))
        self.admin_fee_from = DatePicker(input_frame, width=140, default="")
        self.admin_fee_from.pack(side="left", padx=(0, 15))
        ctk.CTkLabel(input_frame, text="To:").pack(side="left", padx=(0, 5))
        self.admin_fee_to = DatePicker(input_frame, width=140, default="")
        self.admin_fee_to.pack(side="left", padx=(0, 15))
        ctk.CTkButton(input_frame, text="Generate", command=self._load_admin_fees).pack(side="left")
        self.admin_fee_total = ctk.CTkLabel(bar, text="Total: --", font=("Segoe UI", 16, "bold"), text_color="#1F6AA5")
        self.admin_fee_total.pack(side="right", padx=20)
        table = DataTable(parent, columns=[
            ("date", "Date"), ("loan_no", "Loan ID"), ("client", "Client"),
            ("location", "Location"), ("amount", "Amount"),
        ], show_summary=True)
        table.pack(fill="both", expand=True, padx=20, pady=(0, 20))
        self.admin_fees_table = table

    def _load_admin_fees(self):
        from_date = self.admin_fee_from.get() or None
        to_date = self.admin_fee_to.get() or None
        data = report_model.admin_fees_report(self.conn, date_from=from_date, date_to=to_date)
        self.admin_fee_total.configure(text=f"Total: {money(data['total'])}  ({data['count']} fees)")
        self.admin_fees_table.set_rows([{
            "date": r["date"], "loan_no": r["loan_no"], "client": r["client"],
            "location": r["location"], "amount": money(r["amount"]),
        } for r in data["rows"]])

    def _build_application_fees(self, parent):
        bar = self._create_control_bar(parent)
        input_frame = ctk.CTkFrame(bar, fg_color="transparent")
        input_frame.pack(side="left", padx=15, pady=15)
        ctk.CTkLabel(input_frame, text="From:").pack(side="left", padx=(0, 5))
        self.app_fee_from = DatePicker(input_frame, width=140, default="")
        self.app_fee_from.pack(side="left", padx=(0, 15))
        ctk.CTkLabel(input_frame, text="To:").pack(side="left", padx=(0, 5))
        self.app_fee_to = DatePicker(input_frame, width=140, default="")
        self.app_fee_to.pack(side="left", padx=(0, 15))
        ctk.CTkButton(input_frame, text="Generate", command=self._load_application_fees).pack(side="left")
        self.app_fee_total = ctk.CTkLabel(bar, text="Total: --", font=("Segoe UI", 16, "bold"), text_color="#1F6AA5")
        self.app_fee_total.pack(side="right", padx=20)
        table = DataTable(parent, columns=[
            ("date", "Date"), ("loan_no", "Loan ID"), ("client", "Client"),
            ("location", "Location"), ("amount", "Amount"), ("status", "Status"),
        ], show_summary=True)
        table.pack(fill="both", expand=True, padx=20, pady=(0, 20))
        self.application_fees_table = table

    def _load_application_fees(self):
        from_date = self.app_fee_from.get() or None
        to_date = self.app_fee_to.get() or None
        data = report_model.application_fees_report(self.conn, date_from=from_date, date_to=to_date)
        self.app_fee_total.configure(text=f"Total: {money(data['total'])}  ({data['count']} fees)")
        self.application_fees_table.set_rows([{
            "date": r["date"], "loan_no": r["loan_no"], "client": r["client"],
            "location": r["location"], "amount": money(r["amount"]), "status": r["status"],
        } for r in data["rows"]])

    def _build_clients_due_per_day(self, parent):
        bar = self._create_control_bar(parent)
        input_frame = ctk.CTkFrame(bar, fg_color="transparent")
        input_frame.pack(side="left", padx=15, pady=15)
        ctk.CTkLabel(input_frame, text="Due Date:").pack(side="left", padx=(0, 5))
        self.due_day_entry = DatePicker(input_frame, width=140, default=date.today().isoformat())
        self.due_day_entry.pack(side="left", padx=(0, 15))
        ctk.CTkButton(input_frame, text="Generate", command=self._load_clients_due_per_day).pack(side="left")
        self.due_day_total = ctk.CTkLabel(bar, text="Total: --", font=("Segoe UI", 16, "bold"), text_color="#1F6AA5")
        self.due_day_total.pack(side="right", padx=20)
        table = DataTable(parent, columns=[
            ("date", "Date"), ("loan_no", "Loan ID"), ("client", "Client"),
            ("location", "Location"), ("amount", "Amount"), ("installment_no", "Inst #"), ("contact", "Contact"),
        ], show_summary=True)
        table.pack(fill="both", expand=True, padx=20, pady=(0, 20))
        self.clients_due_table = table

    def _load_clients_due_per_day(self):
        due_date = self.due_day_entry.get()
        if not due_date:
            error("Please select a due date.")
            return
        try:
            data = report_model.clients_due_per_day_report(self.conn, due_date)
            self.due_day_total.configure(text=f"Total: {money(data['total'])}  ({data['count']} installments)")
            self.clients_due_table.set_rows([{
                "date": r["date"], "loan_no": r["loan_no"], "client": r["client"],
                "location": r["location"], "amount": money(r["amount"]),
                "installment_no": r["installment_no"], "contact": r["contact"],
            } for r in data["rows"]])
        except Exception as e:
            error(f"Error: {str(e)}")

    def _build_expected_collections(self, parent):
        bar = self._create_control_bar(parent)
        input_frame = ctk.CTkFrame(bar, fg_color="transparent")
        input_frame.pack(side="left", padx=15, pady=15)
        ctk.CTkLabel(input_frame, text="As Of Date:").pack(side="left", padx=(0, 5))
        self.exp_coll_date = DatePicker(input_frame, width=140, default=date.today().isoformat())
        self.exp_coll_date.pack(side="left", padx=(0, 15))
        ctk.CTkButton(input_frame, text="Generate", command=self._load_expected_collections).pack(side="left")
        self.exp_coll_total = ctk.CTkLabel(bar, text="Total: --", font=("Segoe UI", 16, "bold"), text_color="#1F6AA5")
        self.exp_coll_total.pack(side="right", padx=20)
        table = DataTable(parent, columns=[
            ("oldest_due_date", "Oldest Due Date"), ("loan_no", "Loan #"), ("client", "Client"),
            ("location", "Location"), ("contact", "Contact"),
            ("installments_due", "Installments Due"), ("amount", "Amount Due"),
        ], show_summary=True)
        table.pack(fill="both", expand=True, padx=20, pady=(0, 20))
        self.exp_coll_table = table
        self._load_expected_collections()

    def _load_expected_collections(self):
        as_of_date = self.exp_coll_date.get().strip() or date.today().isoformat()
        try:
            data = report_model.expected_collections_report(self.conn, as_of_date)
            self.exp_coll_total.configure(text=f"Total: {money(data['total'])}  ({data['count']} loans)")
            self.exp_coll_table.set_rows([{
                "oldest_due_date": r["oldest_due_date"], "loan_no": r["loan_no"], "client": r["client"],
                "location": r["location"], "contact": r["contact"],
                "installments_due": r["installments_due"], "amount": money(r["amount"]),
            } for r in data["rows"]])
        except Exception as e:
            error(f"Error: {str(e)}")

    def _build_bad_debts_report(self, parent):
        bar = self._create_control_bar(parent)
        ctk.CTkButton(bar, text="Generate Report", command=self._load_bad_debts_report).pack(side="left", padx=15, pady=15)
        table = DataTable(parent, columns=[
            ("loan_no", "Loan #"), ("client_name", "Client"), ("location", "Location"),
            ("contact", "Contact"),
            ("date_written_off", "Written Off"),
            ("amount_written_off", "Amount"), ("total_recovered", "Recovered"),
            ("balance", "Balance"), ("status", "Status"),
        ], show_summary=True)
        table.pack(fill="both", expand=True, padx=20, pady=(0, 20))
        self.bad_debts_report_table = table
        self._load_bad_debts_report()

    def _load_bad_debts_report(self):
        rows = report_model.bad_debts_report(self.conn)
        self.bad_debts_report_table.set_rows([{
            "loan_no": r["loan_no"], "client_name": f"{r['first_name']} {r['last_name']}",
            "location": r["location"] or "",
            "contact": r["contact"] or "",
            "date_written_off": r["date_written_off"], "amount_written_off": money(r["amount_written_off"]),
            "total_recovered": money(r["total_recovered"]),
            "balance": money(r["amount_written_off"] - r["total_recovered"]),
            "status": r["status"],
        } for r in rows])

    def _build_disbursement_report(self, parent):
        bar = self._create_control_bar(parent)
        input_frame = ctk.CTkFrame(bar, fg_color="transparent")
        input_frame.pack(side="left", padx=15, pady=15)
        ctk.CTkLabel(input_frame, text="From:").pack(side="left", padx=(0, 5))
        self.disb_rep_from = DatePicker(input_frame, width=140, default="")
        self.disb_rep_from.pack(side="left", padx=(0, 15))
        ctk.CTkLabel(input_frame, text="To:").pack(side="left", padx=(0, 5))
        self.disb_rep_to = DatePicker(input_frame, width=140, default="")
        self.disb_rep_to.pack(side="left", padx=(0, 15))
        ctk.CTkButton(input_frame, text="Generate", command=self._load_disbursement_report).pack(side="left")
        self.disb_rep_total_label = ctk.CTkLabel(bar, text="Total: --", font=("Segoe UI", 16, "bold"), text_color="#1F6AA5")
        self.disb_rep_total_label.pack(side="right", padx=20)

        # Updated columns – added the new fields
        table = DataTable(parent, columns=[
            ("disbursement_date", "Date"),
            ("loan_no", "Loan #"),
            ("client_name", "Client"),
            ("location", "Location"),
            ("amount", "Amount"),
            ("method", "Method"),
            ("reference", "Reference"),
            ("maturity_date", "Maturity Date"),
            ("repayment_frequency", "Frequency"),
            ("interest_method", "Interest Method"),
            ("term_months", "Tenure (months)"),
        ], show_summary=True)
        table.pack(fill="both", expand=True, padx=20, pady=(0, 20))
        self.disb_report_table = table
        self._load_disbursement_report()

    def _load_disbursement_report(self):
        from_date = self.disb_rep_from.get().strip() or None
        to_date = self.disb_rep_to.get().strip() or None
        result = report_model.disbursement_report(self.conn, date_from=from_date, date_to=to_date)
        label = f"Cash Disbursed: {money(result['total_disbursed'])}  ({result['count']} disbs)"
        if result.get("rollover_count"):
            label += f"   |   Rollovers: {money(result['rollover_total'])}  ({result['rollover_count']})"
        self.disb_rep_total_label.configure(text=label)
        self.disb_report_table.set_rows([{
            "disbursement_date": r["disbursement_date"],
            "loan_no": r["loan_no"],
            "client_name": r["client_name"],
            "location": r["location"],
            "amount": money(r["amount"]),
            "method": r["method"],
            "reference": r["reference"],
            "maturity_date": r["maturity_date"],
            "repayment_frequency": r["repayment_frequency"],
            "interest_method": r["interest_method"],
            "term_months": r["term_months"],
        } for r in result["rows"]])

    def _build_repayment_report(self, parent):
        bar = self._create_control_bar(parent)
        input_frame = ctk.CTkFrame(bar, fg_color="transparent")
        input_frame.pack(side="left", padx=15, pady=15)
        ctk.CTkLabel(input_frame, text="From:").pack(side="left", padx=(0, 5))
        self.rpy_rep_from = DatePicker(input_frame, width=140, default="")
        self.rpy_rep_from.pack(side="left", padx=(0, 15))
        ctk.CTkLabel(input_frame, text="To:").pack(side="left", padx=(0, 5))
        self.rpy_rep_to = DatePicker(input_frame, width=140, default="")
        self.rpy_rep_to.pack(side="left", padx=(0, 15))
        ctk.CTkButton(input_frame, text="Generate", command=self._load_repayment_report).pack(side="left")
        self.rpy_rep_total_label = ctk.CTkLabel(bar, text="Total: --", font=("Segoe UI", 16, "bold"), text_color="#1F6AA5")
        self.rpy_rep_total_label.pack(side="right", padx=20)
        table = DataTable(parent, columns=[
            ("date", "Date"), ("loan_no", "Loan #"), ("client", "Client"), ("location", "Location"),
            ("amount", "Amount"), ("reference", "Reference"),
        ], show_summary=True)
        table.pack(fill="both", expand=True, padx=20, pady=(0, 20))
        self.rpy_report_table = table

    def _load_repayment_report(self):
        from_date = self.rpy_rep_from.get() or None
        to_date = self.rpy_rep_to.get() or None
        result = report_model.repayment_report(self.conn, date_from=from_date, date_to=to_date)
        self.rpy_rep_total_label.configure(text=f"Total: {money(result['total'])}  ({result['count']} repays)")
        self.rpy_report_table.set_rows([{
            "date": r["date"], "loan_no": r["loan_no"], "client": r["client"],
            "location": r["location"], "amount": money(r["amount"]),
            "reference": r["reference"] or "",
        } for r in result["rows"]])

    def _build_loan_statements_report(self, parent):
        bar = self._create_control_bar(parent)
        ctk.CTkButton(bar, text="Generate Report", command=self._load_loan_statements_report).pack(side="left", padx=15, pady=15)
        table = DataTable(parent, columns=[
            ("loan_no", "Loan #"), ("client_name", "Client"), ("location", "Location"),
            ("phone", "Phone"), ("principal", "Principal"), ("interest", "Interest"),
            ("amount_received", "Amount Received"), ("outstanding_balance", "Balance"),
            ("status", "Status"),
        ], show_summary=True)
        table.pack(fill="both", expand=True, padx=20, pady=(0, 20))
        self.loan_statements_table = table
        self._load_loan_statements_report()

    def _load_loan_statements_report(self):
        rows = report_model.loan_statements_report(self.conn)
        self.loan_statements_table.set_rows([{
            "loan_no": r["loan_no"], "client_name": r["client_name"], "location": r["location"],
            "phone": r["phone"], "principal": money(r["principal"]), "interest": money(r["interest"]),
            "amount_received": money(r["amount_received"]),
            "outstanding_balance": money(r["outstanding_balance"]), "status": r["status"],
        } for r in rows])

    def _build_rollover_report(self, parent):
        bar = self._create_control_bar(parent)
        ctk.CTkButton(bar, text="Generate Report", command=self._load_rollover_report).pack(side="left", padx=15, pady=15)
        table = DataTable(parent, columns=[
            ("client_name", "Client"), ("location", "Location"), ("phone", "Phone"),
            ("original_loan_no", "Original Loan"), ("new_loan_no", "New Loan"), ("principal", "Principal"),
            ("interest", "Interest"), ("amount_received", "Received"),
            ("outstanding_balance", "Balance Rolled"), ("rollover_date", "Date"),
        ], show_summary=True)
        table.pack(fill="both", expand=True, padx=20, pady=(0, 20))
        self.rollover_report_table = table
        self._load_rollover_report()

    def _load_rollover_report(self):
        rows = report_model.rollover_report(self.conn)
        self.rollover_report_table.set_rows([{
            "client_name": r["client_name"], "location": r["location"], "phone": r["phone"],
            "original_loan_no": r["original_loan_no"], "new_loan_no": r["new_loan_no"],
            "principal": money(r["principal"]), "interest": money(r["interest"]),
            "amount_received": money(r["amount_received"]),
            "outstanding_balance": money(r["outstanding_balance"]), "rollover_date": r["rollover_date"],
        } for r in rows])

    # ----- NEW: Rollover Fee Report builders -----
    def _build_rollover_fee_report(self, parent):
        bar = self._create_control_bar(parent)
        input_frame = ctk.CTkFrame(bar, fg_color="transparent")
        input_frame.pack(side="left", padx=15, pady=15)
        ctk.CTkLabel(input_frame, text="From:").pack(side="left", padx=(0, 5))
        self.rf_from = DatePicker(input_frame, width=140, default="")
        self.rf_from.pack(side="left", padx=(0, 15))
        ctk.CTkLabel(input_frame, text="To:").pack(side="left", padx=(0, 5))
        self.rf_to = DatePicker(input_frame, width=140, default="")
        self.rf_to.pack(side="left", padx=(0, 15))
        ctk.CTkButton(input_frame, text="Generate", command=self._load_rollover_fee_report).pack(side="left")
        self.rf_total = ctk.CTkLabel(bar, text="Total: --", font=("Segoe UI", 16, "bold"), text_color="#1F6AA5")
        self.rf_total.pack(side="right", padx=20)
        table = DataTable(parent, columns=[
            ("date", "Date"), ("loan_no", "Loan #"), ("client", "Client"),
            ("location", "Location"), ("amount", "Amount"), ("status", "Status"),
            ("description", "Description"),
        ], show_summary=True)
        table.pack(fill="both", expand=True, padx=20, pady=(0, 20))
        self.rollover_fee_table = table

    def _load_rollover_fee_report(self):
        from_date = self.rf_from.get().strip() or None
        to_date = self.rf_to.get().strip() or None
        data = report_model.rollover_fee_report(self.conn, date_from=from_date, date_to=to_date)
        self.rf_total.configure(text=f"Total: {money(data['total'])}  ({data['count']} fees)")
        self.rollover_fee_table.set_rows([{
            "date": r["date"], "loan_no": r["loan_no"], "client": r["client"],
            "location": r["location"], "amount": money(r["amount"]),
            "status": r["status"], "description": r["description"],
        } for r in data["rows"]])# =====================================================================
# 
    def _build_bad_debts_recovery_report(self, parent):
        bar = self._create_control_bar(parent)
        input_frame = ctk.CTkFrame(bar, fg_color="transparent")
        input_frame.pack(side="left", padx=15, pady=15)
        
        ctk.CTkLabel(input_frame, text="From:").pack(side="left", padx=(0, 5))
        self.bdr_rep_from = DatePicker(input_frame, width=140, default="")
        self.bdr_rep_from.pack(side="left", padx=(0, 15))
        
        ctk.CTkLabel(input_frame, text="To:").pack(side="left", padx=(0, 5))
        self.bdr_rep_to = DatePicker(input_frame, width=140, default="")
        self.bdr_rep_to.pack(side="left", padx=(0, 15))
        
        ctk.CTkButton(input_frame, text="Generate", command=self._load_bad_debts_recovery_report).pack(side="left")
        
        self.bdr_rep_total = ctk.CTkLabel(bar, text="Total: --", font=("Segoe UI", 16, "bold"), text_color="#1F6AA5")
        self.bdr_rep_total.pack(side="right", padx=20)
        
        table = DataTable(parent, columns=[
            ("recovery_date", "Recovery Date"), 
            ("loan_no", "Loan #"), 
            ("client", "Client"),
            ("location", "Location"), 
            ("amount_recovered", "Amount Recovered"), 
            ("reference", "Reference"), 
            ("date_written_off", "Date Written Off"), 
            ("amount_written_off", "Amount Written Off"),
        ], show_summary=True)
        table.pack(fill="both", expand=True, padx=20, pady=(0, 20))
        self.bad_debts_recovery_table = table
        self._load_bad_debts_recovery_report()

    def _load_bad_debts_recovery_report(self):
        from_date = self.bdr_rep_from.get().strip() or None
        to_date = self.bdr_rep_to.get().strip() or None
        
        data = report_model.bad_debts_recovery_report(self.conn, date_from=from_date, date_to=to_date)
        
        self.bdr_rep_total.configure(text=f"Total: {money(data['total'])}  ({data['count']} recoveries)")
        
        # Format currency before passing to the table
        for r in data["rows"]:
            r["amount_recovered"] = money(r["amount_recovered"])
            r["amount_written_off"] = money(r["amount_written_off"])
            
        self.bad_debts_recovery_table.set_rows(data["rows"])

    # ----- Location Summary Report (Disbursements / Collections / Bad Debt
    # Recovery / Expenses, pivoted by location vs. day/week/month) -----

    def _build_location_summary(self, parent):
        bar = self._create_control_bar(parent)
        input_frame = ctk.CTkFrame(bar, fg_color="transparent")
        input_frame.pack(side="left", padx=15, pady=15)

        ctk.CTkLabel(input_frame, text="Group by:").pack(side="left", padx=(0, 5))
        self.locsum_period = ctk.CTkOptionMenu(input_frame, values=["Daily", "Weekly", "Monthly"], width=110)
        self.locsum_period.set("Monthly")
        self.locsum_period.pack(side="left", padx=(0, 15))

        ctk.CTkLabel(input_frame, text="From:").pack(side="left", padx=(0, 5))
        self.locsum_from = DatePicker(input_frame, width=140, default="")
        self.locsum_from.pack(side="left", padx=(0, 15))

        ctk.CTkLabel(input_frame, text="To:").pack(side="left", padx=(0, 5))
        self.locsum_to = DatePicker(input_frame, width=140, default="")
        self.locsum_to.pack(side="left", padx=(0, 15))

        ctk.CTkButton(input_frame, text="Generate", command=self._load_location_summary).pack(side="left")

        # Scrollable area holding one section (label + table) per metric.
        # The tables are rebuilt on every Generate click because the set of
        # period columns (days/weeks/months) changes with the date range.
        self.locsum_results = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        self.locsum_results.pack(fill="both", expand=True, padx=20, pady=(0, 20))

        self._load_location_summary()

    def _locsum_add_section(self, title, pivot, note=None):
        ctk.CTkLabel(self.locsum_results, text=title, font=("Segoe UI", 16, "bold")).pack(
            anchor="w", pady=(15, 2)
        )
        if note:
            ctk.CTkLabel(self.locsum_results, text=note, font=("Segoe UI", 11), text_color=TEXT_MUTED).pack(
                anchor="w", pady=(0, 5)
            )

        columns = pivot["columns"]
        table = DataTable(self.locsum_results, columns=columns)
        table.pack(fill="x", expand=False, pady=(0, 5))

        display_rows = []
        for r in pivot["rows"]:
            row = dict(r)
            for key, _label in columns:
                if key != "location" and key in row:
                    row[key] = money(row[key])
            display_rows.append(row)

        # Append the TOTAL row last so it always shows at the bottom of the table.
        totals = dict(pivot["totals_row"])
        for key, _label in columns:
            if key != "location" and key in totals:
                totals[key] = money(totals[key])
        display_rows.append(totals)

        table.set_rows(display_rows)

    def _load_location_summary(self):
        for widget in self.locsum_results.winfo_children():
            widget.destroy()

        period = self.locsum_period.get().lower()
        from_date = self.locsum_from.get().strip() or None
        to_date = self.locsum_to.get().strip() or None

        data = report_model.location_activity_summary(
            self.conn, period=period, date_from=from_date, date_to=to_date
        )

        self._locsum_add_section("Disbursements", data["disbursements"])
        self._locsum_add_section("Loan Collections", data["loan_collections"])
        self._locsum_add_section("Bad Debts Recovery", data["bad_debt_recovery"])
    def _build_fund_position(self, parent):
        bar = self._create_control_bar(parent)
        input_frame = ctk.CTkFrame(bar, fg_color="transparent")
        input_frame.pack(side="left", padx=15, pady=15)

        ctk.CTkLabel(input_frame, text="As Of Date:").pack(side="left", padx=(0, 5))
        self.fp_date = DatePicker(input_frame, width=140, default=date.today().isoformat())
        self.fp_date.pack(side="left", padx=(0, 15))

        ctk.CTkButton(input_frame, text="Generate", command=self._load_fund_position).pack(side="left")

        # Table setup for layout consistency
        self.fp_table = DataTable(parent, columns=[
            ("metric", "Fund Metric"),
            ("amount", "Amount"),
        ], title="Fund Position Summary", height=14, show_summary=False)
        self.fp_table.pack(fill="both", expand=True, padx=20, pady=(0, 20))

        self._load_fund_position()

    def _load_fund_position(self):
        as_of = self.fp_date.get().strip() or date.today().isoformat()
        try:
            data = report_model.fund_position_report(self.conn, as_of)

            # Structure the data for the DataTable
            rows = [
                {"metric": "Cash & Bank Balance (Liquid)", "amount": money(data["cash_balance"])},
                {"metric": "Outstanding Loan Principal (Deployed)", "amount": money(data["loan_balance"])},
                {"metric": "───────────────────────────────", "amount": "─────────"},
                {"metric": "Current Active Fund Capital", "amount": money(data["current_fund_capital"])},
                {"metric": "Add: Expected Interest (Receivable)", "amount": money(data["interest_receivable"])},
                {"metric": "───────────────────────────────", "amount": "─────────"},
                {"metric": "Projected Fund Value", "amount": money(data["projected_fund_value"])},
                {"metric": "", "amount": ""},
                {"metric": "Net Available Liquidity (Today)", "amount": money(data["available_liquidity"])},
                {"metric": "", "amount": ""},
                {"metric": "Pending Loan Applications (Awaiting Approval)", "amount": money(data["pending_disbursements"])},
                {"metric": "Net Liquidity After Committed Pipeline", "amount": money(data["liquidity_after_pipeline"])},
            ]
            self.fp_table.set_rows(rows)

            # Set PDF Export metadata
            self.fp_table.pdf_title = f"Fund Position Report (As of {as_of})"

        except Exception as e:
            error(str(e))
# 
# FINANCIAL STATEMENTS
# =====================================================================
class FinancialsView(BaseView):
    TAB_INCOME = "📈  Income Statement"
    TAB_INCOME_LOC = "🗺️  Income Statement by Location"
    TAB_BALANCE = "🏦  Balance Sheet"
    TAB_CASHFLOW = "💵  Cash Flow Statement"
    TAB_TRIAL = "⚖️  Trial Balance"
    TAB_CLOSE = "🔒  Close Period"

    def __init__(self, master, conn, app):
        super().__init__(master, conn, app)
        self.header("Financial Statements")
        self.tabs = styled_tabview(self)
        self.tabs.pack(fill="both", expand=True)
        for t in [self.TAB_INCOME, self.TAB_INCOME_LOC, self.TAB_BALANCE, self.TAB_CASHFLOW, self.TAB_TRIAL, self.TAB_CLOSE]:
            self.tabs.add(t)
        self._build_income_statement(self.tabs.tab(self.TAB_INCOME))
        self._build_income_statement_by_location(self.tabs.tab(self.TAB_INCOME_LOC))
        self._build_balance_sheet(self.tabs.tab(self.TAB_BALANCE))
        self._build_cash_flow_statement(self.tabs.tab(self.TAB_CASHFLOW))
        self._build_trial_balance(self.tabs.tab(self.TAB_TRIAL))
        self._build_close_period(self.tabs.tab(self.TAB_CLOSE))

    def _filter_bar(self, tab):
        """A consistently-styled card to hold date filters + a Generate
        button, used at the top of every statement tab."""
        bar = ctk.CTkFrame(tab, fg_color=NAVY_CARD, corner_radius=10,
                            border_width=1, border_color=NAVY_BORDER)
        bar.pack(fill="x", padx=20, pady=(20, 12), ipady=10)
        return bar

    def _filter_label(self, parent, text):
        ctk.CTkLabel(parent, text=text, font=("Segoe UI", 12), text_color=TEXT_MUTED).pack(side="left", padx=(14, 6))

    def _build_income_statement(self, tab):
        bar = self._filter_bar(tab)
        self._filter_label(bar, "From")
        self.is_from = DatePicker(bar, width=140, default=date.today().isoformat())
        self.is_from.pack(side="left")
        self._filter_label(bar, "To")
        self.is_to = DatePicker(bar, width=140, default=date.today().isoformat())
        self.is_to.pack(side="left")
        primary_button(bar, "Generate", self._load_income_statement, icon="▶", width=130, height=32).pack(side="left", padx=(14, 0))

        table = DataTable(tab, columns=[("line", "Account"), ("amount", "Amount")], height=16,
                           title="Income Statement")
        table.pack(fill="both", expand=True, padx=20, pady=(0, 20))
        self.is_table = table
        self._load_income_statement()

    def _load_income_statement(self):
        stmt = fin_model.income_statement(
            self.conn, date_from=self.is_from.get().strip() or None, date_to=self.is_to.get().strip() or None)
        rows = [{"line": "── INCOME ──", "amount": ""}]
        rows += [{"line": f"  {l['code']} {l['name']}", "amount": money(l["amount"])} for l in stmt["income"]]
        rows.append({"line": "Total Income", "amount": money(stmt["total_income"])})
        rows.append({"line": "── EXPENSES ──", "amount": ""})
        rows += [{"line": f"  {l['code']} {l['name']}", "amount": money(l["amount"])} for l in stmt["expenses"]]
        rows.append({"line": "Total Expenses", "amount": money(stmt["total_expenses"])})
        rows.append({"line": "NET INCOME", "amount": money(stmt["net_income"])})
        self.is_table.set_rows(rows)

    def _build_income_statement_by_location(self, tab):
        bar = self._filter_bar(tab)
        self._filter_label(bar, "From")
        self.isl_from = DatePicker(bar, width=140, default=date.today().isoformat())
        self.isl_from.pack(side="left")
        self._filter_label(bar, "To")
        self.isl_to = DatePicker(bar, width=140, default=date.today().isoformat())
        self.isl_to.pack(side="left")
        primary_button(bar, "Generate", self._load_income_statement_by_location, icon="▶", width=130, height=32).pack(side="left", padx=(14, 0))

        note = ctk.CTkLabel(
            tab, text="💡  Interest/fee/bad-debt figures come from client location. Manual journal entries "
                      "count only where tagged with a location on posting; untagged manual entries and "
                      "operating expenses (no location on file) fall under 'Unallocated'.",
            font=("Segoe UI", 11), text_color=TEXT_MUTED, anchor="w", wraplength=900, justify="left")
        note.pack(fill="x", padx=20, pady=(0, 4))

        self.isl_reconcile_label = ctk.CTkLabel(
            tab, text="", font=("Segoe UI", 11, "bold"), anchor="w", wraplength=900, justify="left")
        self.isl_reconcile_label.pack(fill="x", padx=20, pady=(0, 8))

        # Columns are built fresh each Generate, since they depend on which
        # locations actually have activity in the chosen period.
        self.isl_table = DataTable(tab, columns=[("metric", "Account"), ("consolidated", "Consolidated")],
                                    height=18, title="Income Statement by Location")
        self.isl_table.pack(fill="both", expand=True, padx=20, pady=(0, 20))
        self._load_income_statement_by_location()

    def _load_income_statement_by_location(self):
        table = fin_model.income_statement_location_table(
            self.conn, date_from=self.isl_from.get().strip() or None, date_to=self.isl_to.get().strip() or None)

        recon = table["reconciliation"]
        if recon["matches"]:
            self.isl_reconcile_label.configure(
                text="✓ Reconciled - matches the ledger-based Income Statement for this period.",
                text_color="#27AE60")
        else:
            parts = []
            if abs(recon["income_diff"]) >= 0.01:
                parts.append(f"income off by {money(recon['income_diff'])}")
            if abs(recon["expense_diff"]) >= 0.01:
                parts.append(f"expenses off by {money(recon['expense_diff'])}")
            self.isl_reconcile_label.configure(
                text=(f"⚠ Does not reconcile with the ledger-based Income Statement - " + ", ".join(parts) +
                      f" (ledger net income {money(recon['ledger_net_income'])} vs "
                      f"{money(recon['location_net_income'])} here). Some activity may be falling through "
                      f"a join (e.g. a loan/client record) - worth investigating before relying on this report."),
                text_color="#EB5757")

        # Rebuild the table's columns each time - the set of locations with
        # activity can change from one period to the next, but Consolidated
        # always stays last.
        display_columns = [(key, label if key != "consolidated" else "Consolidated") for key, label in table["columns"]]
        self.isl_table.rebuild_columns(display_columns) if hasattr(self.isl_table, "rebuild_columns") else None

        formatted_rows = []
        for row in table["rows"]:
            fr = {"metric": row.get("metric", "")}
            for key, _ in table["columns"]:
                if key == "metric":
                    continue
                fr[key] = money(row[key]) if key in row else ""
            formatted_rows.append(fr)

        if hasattr(self.isl_table, "rebuild_columns"):
            self.isl_table.set_rows(formatted_rows)
        else:
            # Fallback if DataTable has no dynamic-column support: rebuild
            # the widget itself with the right columns for this period.
            parent = self.isl_table.master
            self.isl_table.destroy()
            self.isl_table = DataTable(parent, columns=display_columns, height=18,
                                        title="Income Statement by Location")
            self.isl_table.pack(fill="both", expand=True, padx=20, pady=(0, 20))
            self.isl_table.set_rows(formatted_rows)

        self.isl_table.pdf_title = f"Income Statement by Location ({table['period']['from']} to {table['period']['to']})"

    def _build_balance_sheet(self, tab):
        bar = self._filter_bar(tab)
        self._filter_label(bar, "As of")
        self.bs_asof = DatePicker(bar, width=140, default=date.today().isoformat())
        self.bs_asof.pack(side="left")
        primary_button(bar, "Generate", self._load_balance_sheet, icon="▶", width=130, height=32).pack(side="left", padx=(14, 0))

        table = DataTable(tab, columns=[("line", "Account"), ("amount", "Amount")], height=16,
                           title="Balance Sheet")
        table.pack(fill="both", expand=True, padx=20, pady=(0, 20))
        self.bs_table = table
        self._load_balance_sheet()

    def _load_balance_sheet(self):
        bs = fin_model.balance_sheet(self.conn, as_of_date=self.bs_asof.get().strip() or None)
        rows = [{"line": "── ASSETS ──", "amount": ""}]
        rows += [{"line": f"  {a['code']} {a['name']}", "amount": money(a["debit"] - a["credit"])} for a in bs["assets"]]
        rows.append({"line": "Total Assets", "amount": money(bs["total_assets"])})
        rows.append({"line": "── LIABILITIES ──", "amount": ""})
        rows += [{"line": f"  {a['code']} {a['name']}", "amount": money(a["credit"] - a["debit"])} for a in bs["liabilities"]]
        rows.append({"line": "Total Liabilities", "amount": money(bs["total_liabilities"])})
        rows.append({"line": "── EQUITY ──", "amount": ""})
        rows += [{"line": f"  {a['code']} {a['name']}", "amount": money(a["credit"] - a["debit"])} for a in bs["equity"]]
        rows.append({"line": "  Profit/Loss (current period)", "amount": money(bs["profit_loss_current"])})
        rows.append({"line": "Total Equity", "amount": money(bs["total_equity"])})
        rows.append({"line": "Total Liabilities + Equity", "amount": money(bs["total_liabilities_and_equity"])})
        rows.append({"line": "Balanced?", "amount": "YES" if bs["balanced"] else "NO - CHECK ENTRIES"})
        self.bs_table.set_rows(rows)

    def _build_trial_balance(self, tab):
        bar = self._filter_bar(tab)
        self._filter_label(bar, "As of")
        self.tb_asof = DatePicker(bar, width=140, default=date.today().isoformat())
        self.tb_asof.pack(side="left")
        primary_button(bar, "Generate", self._load_trial_balance, icon="▶", width=130, height=32).pack(side="left", padx=(14, 0))

        status_card = ctk.CTkFrame(tab, fg_color=NAVY_CARD, corner_radius=10,
                                    border_width=1, border_color=NAVY_BORDER)
        status_card.pack(fill="x", padx=20, pady=(0, 12), ipady=8)
        self.tb_totals_label = ctk.CTkLabel(status_card, text="", font=("Segoe UI", 13, "bold"), anchor="w")
        self.tb_totals_label.pack(anchor="w", padx=14)

        table = DataTable(tab, columns=[
            ("code", "Code"), ("name", "Account"), ("type", "Type"), ("debit", "Debit"), ("credit", "Credit"),
        ], height=16, title="Trial Balance")
        table.pack(fill="both", expand=True, padx=20, pady=(0, 20))
        self.tb_table = table
        self._load_trial_balance()

    def _load_trial_balance(self):
        tb = fin_model.full_trial_balance(self.conn, as_of_date=self.tb_asof.get().strip() or None)
        balanced = tb['total_debit'] == tb['total_credit']
        self.tb_totals_label.configure(
            text=f"Total Debit {money(tb['total_debit'])}    •    Total Credit {money(tb['total_credit'])}    "
                 f"{'✓ BALANCED' if balanced else '✕ NOT BALANCED'}",
            text_color=(SUCCESS if balanced else DANGER))
        self.tb_table.set_rows([{
            "code": r["code"], "name": r["name"], "type": r["type"],
            "debit": money(r["debit"]) if r["debit"] else "", "credit": money(r["credit"]) if r["credit"] else "",
        } for r in tb["rows"]])

    def _build_close_period(self, tab):
        bar = self._filter_bar(tab)
        self._filter_label(bar, "From")
        self.cp_from = DatePicker(bar, width=140, default=date.today().isoformat())
        self.cp_from.pack(side="left")
        self._filter_label(bar, "To")
        self.cp_to = DatePicker(bar, width=140, default=date.today().isoformat())
        self.cp_to.pack(side="left")
        outline_button(bar, "Preview", self._preview_close_period, icon="👁", width=120, height=32).pack(side="left", padx=(14, 6))
        self.cp_post_btn = danger_button(bar, "Post Closing Entry", self._post_close_period,
                                          icon="🔒", width=190, height=32, state="disabled")
        self.cp_post_btn.pack(side="left")

        summary_card = ctk.CTkFrame(tab, fg_color=NAVY_CARD, corner_radius=10,
                                     border_width=1, border_color=NAVY_BORDER)
        summary_card.pack(fill="x", padx=20, pady=(0, 12), ipady=10)
        self.cp_summary_label = ctk.CTkLabel(
            summary_card, text="Pick a period and click Preview to see what would be closed to the Profit and Loss Account.",
            font=("Segoe UI", 12, "bold"), text_color=TEXT_PRIMARY, wraplength=700, justify="left")
        self.cp_summary_label.pack(anchor="w", padx=14)

        table = DataTable(tab, columns=[("line", "Account"), ("amount", "Amount")], height=16,
                           title="Closing Preview")
        table.pack(fill="both", expand=True, padx=20, pady=(0, 20))
        self.cp_table = table
        # Tracks exactly which (from, to) range the current preview - and
        # therefore the enabled Post button - corresponds to, so editing the
        # date fields after previewing can't post a range that was never
        # actually previewed.
        self._cp_last_range = None

    def _existing_closes_in_range(self, date_from, date_to):
        return self.conn.execute(
            "SELECT entry_date, reference FROM journal_entries WHERE source_type = 'period_close' "
            "AND entry_date >= ? AND entry_date <= ? ORDER BY entry_date",
            (date_from, date_to)
        ).fetchall()

    def _preview_close_period(self):
        self.cp_post_btn.configure(state="disabled")
        self._cp_last_range = None
        try:
            date_from = self.cp_from.get().strip()
            date_to = self.cp_to.get().strip()
            if not date_from or not date_to:
                raise ValueError("Enter both a From and To date.")
            if date_from > date_to:
                raise ValueError("'From' date must be on or before 'To' date.")

            stmt = fin_model.income_statement(self.conn, date_from=date_from, date_to=date_to)

            rows = [{"line": "── INCOME TO BE CLOSED ──", "amount": ""}]
            rows += [{"line": f"  {l['code']} {l['name']}", "amount": money(l["amount"])} for l in stmt["income"]]
            rows.append({"line": "Total Income", "amount": money(stmt["total_income"])})
            rows.append({"line": "── EXPENSES TO BE CLOSED ──", "amount": ""})
            rows += [{"line": f"  {l['code']} {l['name']}", "amount": money(l["amount"])} for l in stmt["expenses"]]
            rows.append({"line": "Total Expenses", "amount": money(stmt["total_expenses"])})
            rows.append({"line": "NET TO PROFIT & LOSS ACCOUNT", "amount": money(stmt["net_income"])})
            self.cp_table.set_rows(rows)

            existing = self._existing_closes_in_range(date_from, date_to)
            warning = ""
            if existing:
                dates = ", ".join(r["entry_date"] for r in existing)
                warning = (
                    f"\n\n⚠ This range already contains {len(existing)} prior closing entry(ies) "
                    f"dated: {dates}. Closing again will re-close the SAME activity a second time - "
                    f"make sure that's really what you intend before posting."
                )

            if not stmt["income"] and not stmt["expenses"]:
                self.cp_summary_label.configure(
                    text=f"No income or expense activity between {date_from} and {date_to} - nothing to close.{warning}")
                return

            self.cp_summary_label.configure(
                text=f"Net {'profit' if stmt['net_income'] >= 0 else 'loss'} of {money(abs(stmt['net_income']))} "
                     f"for {date_from} to {date_to} will be posted to the Profit and Loss Account.{warning}")
            self.cp_post_btn.configure(state="normal")
            self._cp_last_range = (date_from, date_to)
        except Exception as e:
            error(str(e))

    def _post_close_period(self):
        date_from = self.cp_from.get().strip()
        date_to = self.cp_to.get().strip()
        if self._cp_last_range != (date_from, date_to):
            return error("Dates changed since the last preview - click Preview again before posting.")

        existing = self._existing_closes_in_range(date_from, date_to)
        warning = ""
        if existing:
            dates = ", ".join(r["entry_date"] for r in existing)
            warning = f"\n\nWARNING: this range already has closing entries dated {dates} - this will close it again."

        if not confirm(
            f"Post the closing entry for {date_from} to {date_to}?\n\n"
            f"This posts a real journal entry moving all Income/Expense activity for this period into "
            f"the Profit and Loss Account. It isn't undone from this screen - only by a manual reversing "
            f"journal via Advanced Journal Entry.{warning}\n\nContinue?"
        ):
            return
        try:
            result = fin_model.close_period_to_profit_and_loss(
                self.conn, date_from=date_from, date_to=date_to, user_id=Session.current_user["id"]
            )
            info(
                f"Closing entry posted (Journal #{result['journal_id']}). "
                f"Net {'profit' if result['net_income'] >= 0 else 'loss'} of {money(abs(result['net_income']))} "
                f"moved to the Profit and Loss Account."
            )
            self.cp_post_btn.configure(state="disabled")
            self._cp_last_range = None
            self._preview_close_period()
        except Exception as e:
            error(str(e))

    def _build_cash_flow_statement(self, tab):
        bar = self._filter_bar(tab)
        
        self._filter_label(bar, "From")
        
        # Calculate the first day of the current month
        first_of_month = date.today().replace(day=1).isoformat()
        
        # 1. Create the 'From' DatePicker
        self.cf_from = DatePicker(bar, width=140, default=first_of_month)
        # 2. Pack the widget to make it visible on the screen
        self.cf_from.pack(side="left", padx=(5, 10)) 
        
        self._filter_label(bar, "To")
        
        # 1. Create the 'To' DatePicker
        self.cf_to = DatePicker(bar, width=140, default=date.today().isoformat())
        # 2. Pack the widget to make it visible on the screen
        self.cf_to.pack(side="left", padx=(5, 10))
        
        primary_button(bar, "Generate", self._load_cash_flow_statement, icon="▶", width=130, height=32).pack(side="left", padx=(14, 0))
        # ... rest of the function remains unchanged
        
        table = DataTable(tab, columns=[("line", "Description"), ("amount", "Amount")], height=20,
                           title="Cash Flow Statement")
        table.pack(fill="both", expand=True, padx=20, pady=(0, 20))
        self.cf_table = table
        self._load_cash_flow_statement()

    def _load_cash_flow_statement(self):
        stmt = fin_model.cash_flow_statement(
            self.conn, date_from=self.cf_from.get().strip() or None, date_to=self.cf_to.get().strip() or None)

        rows = []
        
        # Inflows Section
        rows.append({"line": "INFLOWS", "amount": ""})
        for l in stmt["inflows"]:
            rows.append({"line": l["description"], "amount": money(l["amount"])})
        rows.append({"line": "Total Inflows", "amount": money(stmt["total_inflows"])})

        # Outflows Section
        rows.append({"line": "OUTFLOWS", "amount": ""})
        for l in stmt["outflows"]:
            rows.append({"line": l["description"], "amount": money(l["amount"])})
        rows.append({"line": "TOTAL OUTFLOWS", "amount": money(stmt["total_outflows"])})

        # Summary Section
        rows.append({"line": "", "amount": ""})
        rows.append({"line": "NET CASH MOVEMENT", "amount": money(stmt["net_change_in_cash"])})
        rows.append({"line": "Opening balance", "amount": money(stmt["opening_cash"])})
        rows.append({"line": "Closing balance", "amount": money(stmt["closing_cash"])})

        self.cf_table.set_rows(rows)
        self.cf_table.pdf_title = f"Cash Flow Statement ({stmt['period']['from']} to {stmt['period']['to']})"


# =====================================================================
# USERS (admin only)
# =====================================================================
class UsersView(BaseView):
    def __init__(self, master, conn, app):
        super().__init__(master, conn, app)
        self.header("System Users")
        bar = self.toolbar()
        ctk.CTkButton(bar, text="+ New User", command=self._new_user).pack(side="left")
        ctk.CTkButton(bar, text="Deactivate Selected", command=self._deactivate).pack(side="left", padx=6)
        ctk.CTkButton(bar, text="Reset Password", command=self._reset_password).pack(side="left")
        ctk.CTkButton(bar, text="Edit Permissions", command=self._edit_permissions).pack(side="left", padx=6)
        ctk.CTkButton(bar, text="Set Security Question", command=self._set_security_question).pack(side="left")

        self.table = DataTable(self, columns=[
            ("username", "Username"), ("full_name", "Full Name"), ("role", "Role"),
            ("active", "Active"), ("security_q", "Security Question Set"), ("last_login", "Last Login"),
        ])
        self.table.pack(fill="both", expand=True)
        self.refresh()

    def refresh(self):
        rows = self.conn.execute("SELECT * FROM users ORDER BY id").fetchall()
        self.table.set_rows([{
            "id": u["id"], "username": u["username"], "full_name": u["full_name"], "role": u["role"],
            "active": "Yes" if u["active"] else "No",
            "security_q": "Yes" if u["security_question"] else "No",
            "last_login": u["last_login"] or "-",
        } for u in rows])

    def _new_user(self):
        fields = [
            {"key": "username", "label": "Username*"},
            {"key": "full_name", "label": "Full Name*"},
            {"key": "password", "label": "Password*"},
            {"key": "role", "label": "Role*", "type": "combobox",
             "options": ["admin", "manager", "loan_officer", "teller", "viewer"]},
            {"key": "security_question", "label": "Security Question"},
            {"key": "security_answer", "label": "Security Answer"},
        ]

        def submit(values):
            if not values["username"] or not values["password"]:
                raise ValueError("Username and password are required.")
            pwd_hash, salt = hash_password(values["password"])
            cur = self.conn.execute(
                "INSERT INTO users (username, password_hash, salt, full_name, role) VALUES (?,?,?,?,?)",
                (values["username"], pwd_hash, salt, values["full_name"], values["role"]),
            )
            self.conn.commit()
            if values.get("security_question") and values.get("security_answer"):
                set_security_question(self.conn, cur.lastrowid, values["security_question"], values["security_answer"])
            self.refresh()
            info("User created.")

        FormDialog(self, "New User", fields, submit)

    def _deactivate(self):
        row = self.table.selected_row()
        if not row:
            error("Select a user first.")
            return
        self.conn.execute("UPDATE users SET active = 0 WHERE username = ?", (row["username"],))
        self.conn.commit()
        self.refresh()

    def _reset_password(self):
        row = self.table.selected_row()
        if not row:
            error("Select a user first.")
            return

        def submit(values):
            pwd_hash, salt = hash_password(values["password"])
            self.conn.execute("UPDATE users SET password_hash=?, salt=? WHERE username=?",
                               (pwd_hash, salt, row["username"]))
            self.conn.commit()
            info("Password reset.")

        FormDialog(self, f"Reset Password - {row['username']}", [{"key": "password", "label": "New Password*"}], submit)

    def _set_security_question(self):
        row = self.table.selected_row()
        if not row:
            error("Select a user first.")
            return

        def submit(values):
            if not values["security_question"] or not values["security_answer"]:
                raise ValueError("Both a question and an answer are required.")
            set_security_question(self.conn, int(row["id"]), values["security_question"], values["security_answer"])
            self.refresh()
            info("Security question set. The user can now use 'Forgot Password?' on the login screen.")

        FormDialog(self, f"Set Security Question - {row['username']}", [
            {"key": "security_question", "label": "Question*"},
            {"key": "security_answer", "label": "Answer*"},
        ], submit)

    def _edit_permissions(self):
        row = self.table.selected_row()
        if not row:
            error("Select a user first.")
            return
        if row["role"] == "admin":
            info("Admins always have full access to every module - nothing to configure.")
            return

        user_id = int(row["id"])
        current = perm_model.get_permissions(self.conn, user_id)

        win = ctk.CTkToplevel(win_master := self)
        win.title(f"Edit Permissions - {row['username']}")
        win.geometry("560x420")
        win.configure(fg_color=NAVY_DEEP)
        win.transient(win_master)
        win.grab_set()

        ctk.CTkLabel(win, text=f"Module access for {row['full_name']}",
                     font=("Segoe UI", 14, "bold"), text_color=BLUE_LIGHT).pack(pady=(16, 4))
        ctk.CTkLabel(win, text="View controls sidebar visibility. Edit/Delete/Approve gate specific actions "
                               "within a module - unused ones (e.g. Approve on Clients) simply have no effect.",
                     font=("Segoe UI", 10), text_color=TEXT_MUTED, wraplength=500).pack(pady=(0, 10))

        grid = ctk.CTkFrame(win, fg_color=NAVY_MID, corner_radius=10)
        grid.pack(fill="both", expand=True, padx=16, pady=(0, 10))

        headers = ["Module"] + [a.title() for a in perm_model.ACTIONS]
        for col, h in enumerate(headers):
            ctk.CTkLabel(grid, text=h, font=("Segoe UI", 11, "bold"), text_color=BLUE_LIGHT).grid(
                row=0, column=col, padx=12, pady=(12, 8), sticky="w" if col == 0 else "n")

        check_vars = {}
        for r, module in enumerate(perm_model.MODULES, start=1):
            ctk.CTkLabel(grid, text=module, font=("Segoe UI", 12), text_color=TEXT_PRIMARY).grid(
                row=r, column=0, padx=12, pady=6, sticky="w")
            check_vars[module] = {}
            for col, action in enumerate(perm_model.ACTIONS, start=1):
                var = ctk.BooleanVar(value=current.get(module, {}).get(action, False))
                ctk.CTkCheckBox(grid, text="", variable=var, width=20).grid(row=r, column=col, padx=12, pady=6)
                check_vars[module][action] = var

        def save():
            data = {m: {a: v.get() for a, v in actions.items()} for m, actions in check_vars.items()}
            perm_model.set_permissions(self.conn, user_id, data)
            win.destroy()
            info("Permissions updated.")

        btn_row = ctk.CTkFrame(win, fg_color="transparent")
        btn_row.pack(side="bottom", fill="x", padx=14, pady=14)
        ctk.CTkButton(btn_row, text="Cancel", fg_color=NAVY_BORDER, hover_color=TEXT_DIM,
                      command=win.destroy).pack(side="right", padx=4)
        ctk.CTkButton(btn_row, text="Save", fg_color=BLUE_ACCENT, hover_color=BLUE_HOVER,
                      command=save).pack(side="right", padx=4)


class SettingsView(BaseView):
    def __init__(self, master, conn, app):
        super().__init__(master, conn, app)
        self.header("Settings")

        self.tabs = ctk.CTkTabview(self)
        self.tabs.pack(fill="both", expand=True, padx=15, pady=(0, 15))

        for tab in ["Company Profile", "Client Locations", "Loan Products", "Interest Rate Presets"]:
            self.tabs.add(tab)

        self._build_company_profile(self.tabs.tab("Company Profile"))

        self._build_locations(self.tabs.tab("Client Locations"))
        self._build_loan_products(self.tabs.tab("Loan Products"))
        self._build_rate_presets(self.tabs.tab("Interest Rate Presets"))

    # ==========================================
    # CLIENT LOCATIONS
    # ==========================================
    def _build_locations(self, tab):
        bar = ctk.CTkFrame(tab, fg_color="transparent")
        bar.pack(fill="x", padx=15, pady=15)
        ctk.CTkButton(bar, text="+ Add Location", command=self._new_location).pack(side="left")
        ctk.CTkButton(bar, text="Edit Selected", command=self._edit_location).pack(side="left", padx=6)
        ctk.CTkButton(bar, text="Deactivate Selected", command=lambda: self._set_location_active(False)).pack(side="left")
        ctk.CTkButton(bar, text="Reactivate Selected", command=lambda: self._set_location_active(True)).pack(side="left", padx=6)
        ctk.CTkButton(bar, text="Delete Selected", fg_color="#B71C1C", hover_color="#C62828",
                      command=self._delete_location).pack(side="left")

        self.loc_table = DataTable(tab, columns=[
            ("name", "Location"), ("active", "Active"),
        ])
        self.loc_table.pack(fill="both", expand=True, padx=15, pady=(0, 15))
        self._refresh_locations()

    def _refresh_locations(self):
        rows = settings_model.list_locations(self.conn)
        self.loc_table.set_rows([{
            "id": r["id"], "name": r["name"], "active": "Yes" if r["active"] else "No",
        } for r in rows])

    def _new_location(self):
        def submit(values):
            settings_model.create_location(self.conn, values["name"])
            self._refresh_locations()
            info("Location added.")

        FormDialog(self, "New Location", [{"key": "name", "label": "Location Name*"}], submit)

    def _edit_location(self):
        row = self.loc_table.selected_row()
        if not row:
            error("Select a location first.")
            return

        def submit(values):
            settings_model.update_location(self.conn, int(row["id"]), name=values["name"])
            self._refresh_locations()
            info("Location updated.")

        FormDialog(self, "Edit Location", [{"key": "name", "label": "Location Name*", "default": row["name"]}], submit)

    def _set_location_active(self, active: bool):
        row = self.loc_table.selected_row()
        if not row:
            error("Select a location first.")
            return
        settings_model.update_location(self.conn, int(row["id"]), active=active)
        self._refresh_locations()

    def _delete_location(self):
        row = self.loc_table.selected_row()
        if not row:
            error("Select a location first.")
            return
        if not confirm(f"Delete location '{row['name']}'? This only removes it from the picklist - "
                       f"any clients already using it keep their existing value."):
            return
        settings_model.delete_location(self.conn, int(row["id"]))
        self._refresh_locations()

    def _build_company_profile(self, tab):
        scroll = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=15, pady=15)
        
        ctk.CTkLabel(scroll, text="Company Registration Details", font=("Segoe UI", 18, "bold")).pack(anchor="w", pady=(0, 10), padx=10)

        schema = [
            {
                "title": "Corporate Identity",
                "color": "#1A3B5C", # Dark Navy
                "rows": [
                    [
                        {"key": "name", "label": "REGISTERED COMPANY NAME*"},
                        {"key": "reg_number", "label": "COMPANY REGISTRATION NUMBER"}
                    ]
                ]
            },
            {
                "title": "Contact Information",
                "color": "#5C3A1A", # Dark Amber
                "rows": [
                    [
                        {"key": "phone", "label": "CONTACT NUMBER"},
                        {"key": "email", "label": "EMAIL ADDRESS"}
                    ],
                    [
                        {"key": "address", "label": "PHYSICAL ADDRESS"} 
                    ]
                ]
            },
            {
                "title": "Statutory & Tax",
                "color": "#1A5C3A", # Dark Teal
                "rows": [
                    [
                        {"key": "tax_number", "label": "ZIMRA BP/TIN NUMBER"}
                    ]
                ]
            }
        ]

        def submit(values):
            try:
                if not values["name"]:
                    raise ValueError("Registered Company Name is required.")
                settings_model.save_company_details(self.conn, values)
                info("Company profile updated successfully. This will now reflect on all generated documents.")
                self._refresh_company_profile()
            except Exception as e:
                error(str(e))

        self.comp_form = SectionedFormFrame(scroll, schema=schema, on_submit=submit, submit_text="Save Details")
        self.comp_form.pack(fill="x", expand=False)
        self._refresh_company_profile()

    def _refresh_company_profile(self):
        details = settings_model.get_company_details(self.conn)
        self.comp_form.update_fields(details)
        
   
    # ==========================================
    # LOAN PRODUCTS
    # ==========================================
    def _build_loan_products(self, tab):
        bar = ctk.CTkFrame(tab, fg_color="transparent")
        bar.pack(fill="x", padx=15, pady=15)
        ctk.CTkButton(bar, text="+ Add Product", command=self._new_product).pack(side="left")
        ctk.CTkButton(bar, text="Edit Selected", command=self._edit_product).pack(side="left", padx=6)
        ctk.CTkButton(bar, text="Deactivate Selected", command=lambda: self._set_product_active(False)).pack(side="left")
        ctk.CTkButton(bar, text="Reactivate Selected", command=lambda: self._set_product_active(True)).pack(side="left", padx=6)

        self.prod_table = DataTable(tab, columns=[
            ("name", "Name"), ("interest_method", "Interest Method"), ("interest_rate", "Rate (%)"),
            ("rate_period", "Rate Period"), ("admin_fee_pct", "Admin Fee (%)"),
            ("application_fee_pct", "New Client App. Fee (%)"), ("penalty_pct", "Penalty (%)"),
            ("grace_period_days", "Grace Days"), ("repayment_frequency", "Frequency"), ("active", "Active"),
        ])
        self.prod_table.pack(fill="both", expand=True, padx=15, pady=(0, 15))
        self._refresh_products()

    def _refresh_products(self):
        rows = settings_model.list_loan_products(self.conn)
        self.prod_table.set_rows([{
            "id": r["id"], "name": r["name"], "interest_method": r["interest_method"],
            "interest_rate": r["interest_rate"], "rate_period": r["rate_period"],
            "admin_fee_pct": r["admin_fee_pct"], "application_fee_pct": r["application_fee_pct"],
            "penalty_pct": r["penalty_pct"],
            "grace_period_days": r["grace_period_days"], "repayment_frequency": r["repayment_frequency"],
            "active": "Yes" if r["active"] else "No",
        } for r in rows])

    @staticmethod
    def _product_fields(product=None):
        p = product
        return [
            {"key": "name", "label": "Product Name*", "default": p["name"] if p else ""},
            {"key": "interest_method", "label": "Interest Method*", "type": "combobox",
             "options": ["flat", "reducing_balance", "interest_only_balloon"],
             "default": p["interest_method"] if p else "flat"},
            {"key": "interest_rate", "label": "Interest Rate (%)*",
             "default": p["interest_rate"] if p else ""},
            {"key": "rate_period", "label": "Rate Period*", "type": "combobox",
             "options": ["month", "year", "loan_term"], "default": p["rate_period"] if p else "month"},
            {"key": "admin_fee_pct", "label": "Admin Fee (%)", "default": p["admin_fee_pct"] if p else "0"},
            {"key": "application_fee_pct", "label": "New Client Application Fee (%)",
             "default": p["application_fee_pct"] if p else "0"},
            {"key": "penalty_pct", "label": "Penalty (%)", "default": p["penalty_pct"] if p else "0"},
            {"key": "grace_period_days", "label": "Grace Period (Days)",
             "default": p["grace_period_days"] if p else "0"},
            {"key": "repayment_frequency", "label": "Repayment Frequency*", "type": "combobox",
             "options": ["weekly", "biweekly", "monthly"],
             "default": p["repayment_frequency"] if p else "monthly"},
            {"key": "term_unit_label", "label": "Term Unit Label (e.g. 'months', 'weeks')",
             "default": p["term_unit_label"] if p else "months"},
        ]

    def _new_product(self):
        fields = self._product_fields()

        def submit(values):
            if not values["name"].strip():
                raise ValueError("Product name is required.")
            values["interest_rate"] = float(values["interest_rate"])
            values["admin_fee_pct"] = float(values.get("admin_fee_pct") or 0)
            values["application_fee_pct"] = float(values.get("application_fee_pct") or 0)
            values["penalty_pct"] = float(values.get("penalty_pct") or 0)
            values["grace_period_days"] = int(values.get("grace_period_days") or 0)
            settings_model.create_loan_product(self.conn, values)
            self._refresh_products()
            info("Loan product created.")

        FormDialog(self, "New Loan Product", fields, submit)

    def _edit_product(self):
        row = self.prod_table.selected_row()
        if not row:
            error("Select a loan product first.")
            return
        product = settings_model.get_loan_product(self.conn, int(row["id"]))
        fields = self._product_fields(product)

        def submit(values):
            if not values["name"].strip():
                raise ValueError("Product name is required.")
            values["interest_rate"] = float(values["interest_rate"])
            values["admin_fee_pct"] = float(values.get("admin_fee_pct") or 0)
            values["application_fee_pct"] = float(values.get("application_fee_pct") or 0)
            values["penalty_pct"] = float(values.get("penalty_pct") or 0)
            values["grace_period_days"] = int(values.get("grace_period_days") or 0)
            settings_model.update_loan_product(self.conn, product["id"], values)
            self._refresh_products()
            info("Loan product updated.")
            info("Note: this only affects new loans created from this product going "
                 "forward - existing loans keep the rate/terms they were disbursed with.")

        FormDialog(self, f"Edit {product['name']}", fields, submit)

    def _set_product_active(self, active: bool):
        row = self.prod_table.selected_row()
        if not row:
            error("Select a loan product first.")
            return
        settings_model.set_loan_product_active(self.conn, int(row["id"]), active)
        self._refresh_products()

    # ==========================================
    # INTEREST RATE PRESETS
    # ==========================================
    def _build_rate_presets(self, tab):
        bar = ctk.CTkFrame(tab, fg_color="transparent")
        bar.pack(fill="x", padx=15, pady=15)
        ctk.CTkButton(bar, text="+ Add Preset", command=self._new_rate_preset).pack(side="left")
        ctk.CTkButton(bar, text="Edit Selected", command=self._edit_rate_preset).pack(side="left", padx=6)
        ctk.CTkButton(bar, text="Deactivate Selected", command=lambda: self._set_rate_preset_active(False)).pack(side="left")
        ctk.CTkButton(bar, text="Reactivate Selected", command=lambda: self._set_rate_preset_active(True)).pack(side="left", padx=6)
        ctk.CTkButton(bar, text="Delete Selected", fg_color="#B71C1C", hover_color="#C62828",
                      command=self._delete_rate_preset).pack(side="left")

        self.rate_preset_table = DataTable(tab, columns=[
            ("label", "Label"), ("rate", "Rate (%)"), ("active", "Active"),
        ])
        self.rate_preset_table.pack(fill="both", expand=True, padx=15, pady=(0, 15))
        self._refresh_rate_presets()

    def _refresh_rate_presets(self):
        rows = settings_model.list_rate_presets(self.conn)
        self.rate_preset_table.set_rows([{
            "id": r["id"], "label": r["label"], "rate": r["rate"],
            "active": "Yes" if r["active"] else "No",
        } for r in rows])

    def _new_rate_preset(self):
        def submit(values):
            settings_model.create_rate_preset(self.conn, values["label"], float(values["rate"]))
            self._refresh_rate_presets()
            info("Interest rate preset added.")

        FormDialog(self, "New Interest Rate Preset", [
            {"key": "label", "label": "Label* (e.g. 'Standard Weekly')"},
            {"key": "rate", "label": "Rate (%)*"},
        ], submit)

    def _edit_rate_preset(self):
        row = self.rate_preset_table.selected_row()
        if not row:
            error("Select a preset first.")
            return

        def submit(values):
            settings_model.update_rate_preset(self.conn, int(row["id"]),
                                               label=values["label"], rate=float(values["rate"]))
            self._refresh_rate_presets()
            info("Interest rate preset updated.")

        FormDialog(self, "Edit Interest Rate Preset", [
            {"key": "label", "label": "Label*", "default": row["label"]},
            {"key": "rate", "label": "Rate (%)*", "default": row["rate"]},
        ], submit)

    def _set_rate_preset_active(self, active: bool):
        row = self.rate_preset_table.selected_row()
        if not row:
            error("Select a preset first.")
            return
        settings_model.update_rate_preset(self.conn, int(row["id"]), active=active)
        self._refresh_rate_presets()

    def _delete_rate_preset(self):
        row = self.rate_preset_table.selected_row()
        if not row:
            error("Select a preset first.")
            return
        if not confirm(f"Delete preset '{row['label']}'? This only removes it from the picklist - "
                       f"any loans already using that rate are unaffected."):
            return
        settings_model.delete_rate_preset(self.conn, int(row["id"]))
        self._refresh_rate_presets()


class ChartOfAccountsView(BaseView):
    """
    Lets an admin define new General Ledger accounts beyond the default set,
    choosing which category (Asset, Liability, Equity, Income, or Expense)
    each rolls up under. Core accounts the accounting engine posts to
    directly (Cash, Loans Receivable, Interest Income, etc.) are marked
    Protected and can be renamed but not have their code changed or be
    deleted - everything else is fully editable.
    """
    def __init__(self, master, conn, app):
        super().__init__(master, conn, app)
        self.header("Chart of Accounts")
        bar = self.toolbar()
        primary_button(bar, "New Account", self._new_account, icon="+", width=140, height=32).pack(side="left", padx=(14, 0))
        secondary_button(bar, "Edit Selected", self._edit_account, icon="✎", width=140, height=32).pack(side="left", padx=6)
        danger_button(bar, "Delete Selected", self._delete_account, icon="🗑", width=150, height=32).pack(side="left")
        ctk.CTkLabel(bar, text="  🔒  Protected accounts are used directly by the accounting engine - "
                               "their code can't change and they can't be deleted.",
                     text_color=TEXT_MUTED, font=("Segoe UI", 11)).pack(side="left", padx=(10, 0))

        self.table = DataTable(self, columns=[
            ("code", "Code"), ("name", "Account Name"), ("type", "Category"),
            ("balance", "Balance"), ("control", "Control A/C"), ("protected", "Protected"),
        ], title="Chart of Accounts")
        self.table.pack(fill="both", expand=True)
        self.refresh()

    def refresh(self):
        rows = coa_model.list_accounts(self.conn)
        self.table.set_rows([{
            "id": r["id"], "code": r["code"], "name": r["name"], "type": r["type"],
            "balance": money(accounting.account_balance(self.conn, r["code"])),
            "control": "Yes" if r["is_control"] else "No",
            "protected": "Yes" if r["code"] in coa_model.PROTECTED_CODES else "",
        } for r in rows])

    def _new_account(self):
        fields = [
            {"key": "code", "label": "Code*", "default": ""},
            {"key": "name", "label": "Account Name*", "default": ""},
            {"key": "type", "label": "Category*", "type": "combobox", "options": coa_model.ACCOUNT_TYPES},
            {"key": "is_control", "label": "Control Account?", "type": "combobox", "options": ["No", "Yes"]},
        ]

        def submit(values):
            coa_model.create_account(
                self.conn, values["code"], values["name"], values["type"],
                is_control=(values["is_control"] == "Yes"),
            )
            info(f"Account {values['code']} - {values['name']} created.")
            self.refresh()

        FormDialog(self, "New General Ledger Account", fields, submit)

    def _edit_account(self):
        if not perm_model.has_permission(self.conn, Session.current_user, "Accounting", "edit"):
            error("You do not have permission to edit ledger accounts.")
            return
        row = self.table.selected_row()
        if not row:
            return error("Select an account first.")
        protected = row["code"] in coa_model.PROTECTED_CODES
        fields = [
            {"key": "code", "label": "Code*" + (" (protected - fixed)" if protected else ""), "default": row["code"]},
            {"key": "name", "label": "Account Name*", "default": row["name"]},
            {"key": "type", "label": "Category*", "type": "combobox",
             "options": coa_model.ACCOUNT_TYPES, "default": row["type"]},
            {"key": "is_control", "label": "Control Account?", "type": "combobox",
             "options": ["No", "Yes"], "default": row["control"]},
        ]

        def submit(values):
            coa_model.update_account(
                self.conn, int(row["id"]), code=values["code"], name=values["name"],
                type_=values["type"], is_control=(values["is_control"] == "Yes"),
            )
            info("Account updated.")
            self.refresh()

        FormDialog(self, f"Edit Account - {row['code']}", fields, submit)

    def _delete_account(self):
        if not perm_model.has_permission(self.conn, Session.current_user, "Accounting", "delete"):
            error("You do not have permission to delete ledger accounts.")
            return
        row = self.table.selected_row()
        if not row:
            return error("Select an account first.")
        if not confirm(f"Delete account '{row['code']} - {row['name']}'? This cannot be undone."):
            return
        try:
            coa_model.delete_account(self.conn, int(row["id"]))
            info("Account deleted.")
            self.refresh()
        except Exception as e:
            error(str(e))


class AccountingView(BaseView):
    """
    General ledger posting module. "Quick Posting" covers the common case -
    pick any account (expense, equity, liability, other income, asset, or
    anything else in the Chart of Accounts), say whether it went up or down,
    and it's posted against Cash automatically. "Advanced Journal Entry"
    supports a full multi-line manual entry for anything more complex.
    "Recent Postings" lists what's been posted through this module for review.
    """
    # Tab labels carry a small icon purely for visual identity; the
    # underlying CTkTabview keys (used by .tab()/.get()) are these exact
    # strings, so every lookup below must use the same icon+name combo.
    TAB_QUICK = "🧮  Quick Posting"
    TAB_JOURNAL = "📓  Advanced Journal Entry"
    TAB_BUDGETS = "🎯  Budgets"
    TAB_FINANCIALS = "📈  Financial Statements"
    TAB_COA = "🗂️  Chart of Accounts"
    TAB_RECENT = "🕑  Recent Postings"

    def __init__(self, master, conn, app):
        super().__init__(master, conn, app)
        self.header("Accounting")
        ctk.CTkLabel(self, text="Post transactions, manage journal entries, budgets and financial statements.",
                     font=("Segoe UI", 12), text_color=TEXT_MUTED, anchor="w").pack(fill="x", pady=(0, 14))

        self.tabs = styled_tabview(self, command=self._on_tab_change)
        self.tabs.pack(fill="both", expand=True)

        is_admin = Session.current_user and Session.current_user.get("role") == "admin"
        tab_names = [self.TAB_QUICK, self.TAB_JOURNAL, self.TAB_BUDGETS, self.TAB_FINANCIALS]
        if is_admin:
            tab_names.append(self.TAB_COA)
        tab_names.append(self.TAB_RECENT)
        for t in tab_names:
            self.tabs.add(t)

        self._build_quick_posting(self.tabs.tab(self.TAB_QUICK))
        self._build_journal_entry(self.tabs.tab(self.TAB_JOURNAL))
        self._build_budgets(self.tabs.tab(self.TAB_BUDGETS))
        self._build_recent_postings(self.tabs.tab(self.TAB_RECENT))

        FinancialsView(self.tabs.tab(self.TAB_FINANCIALS), self.conn, self.app).pack(fill="both", expand=True)
        if is_admin:
            ChartOfAccountsView(self.tabs.tab(self.TAB_COA), self.conn, self.app).pack(fill="both", expand=True)

    def _account_choices(self):
        accounts = coa_model.list_accounts(self.conn)
        return {f"{a['code']} - {a['name']} ({a['type']})": a["code"] for a in accounts}

    def _on_tab_change(self):
        """Automatically refresh account lists when navigating back to posting tabs."""
        current_tab = self.tabs.get()
        if current_tab in (self.TAB_QUICK, self.TAB_JOURNAL, self.TAB_BUDGETS):
            self._refresh_account_dropdowns()
        if current_tab == self.TAB_BUDGETS:
            self._refresh_budgets_list()

    def _refresh_account_dropdowns(self):
        """Fetches the latest accounts and updates all comboboxes."""
        accounts = self._account_choices()
        acc_list = list(accounts.keys())
        
        if hasattr(self, 'qp_account'):
            self.qp_account.set_values(acc_list)
        if hasattr(self, 'qp_offset'):
            self.qp_offset.set_values(acc_list)
            
        if hasattr(self, 'je_sheet'):
            try:
                self.je_sheet.create_dropdown(r="all", c=self.JE_COL_ACCOUNT, values=acc_list, state="normal")
            except Exception:
                pass

    # ------------------------------------------------------------------
    # TAB 1: QUICK POSTING
    # ------------------------------------------------------------------
    def _build_quick_posting(self, tab):
        scroll = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=20, pady=20)

        accounts = self._account_choices()
        label_font = ("Segoe UI", 12)

        card1 = ctk.CTkFrame(scroll, fg_color=NAVY_CARD, corner_radius=12,
                              border_width=1, border_color=NAVY_BORDER)
        card1.pack(fill="x", pady=(0, 16), ipadx=22, ipady=20)
        card_header(card1, "What are you posting?", icon="🧮",
                    subtitle="Pick the account this affects and whether it's going up or down.").grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 16))

        ctk.CTkLabel(card1, text="Account*", width=140, anchor="w", font=label_font, text_color=TEXT_MUTED).grid(row=1, column=0, sticky="w", pady=8)
        self.qp_account = SearchableCombobox(card1, values=list(accounts.keys()), width=340)
        self.qp_account.grid(row=1, column=1, sticky="w")
        secondary_button(card1, "New Expense Category", self._quick_new_expense_category,
                          icon="+", width=190, height=32).grid(row=1, column=2, sticky="w", padx=(10, 0))

        ctk.CTkLabel(card1, text="Direction*", width=140, anchor="w", font=label_font, text_color=TEXT_MUTED).grid(row=2, column=0, sticky="w", pady=8)
        self.qp_direction = ctk.CTkComboBox(card1, values=["Increase", "Decrease"], width=200,
                                             fg_color=NAVY_MID, button_color=BLUE_ACCENT, button_hover_color=BLUE_HOVER)
        self.qp_direction.grid(row=2, column=1, sticky="w")
        ctk.CTkLabel(card1, text="Increase = an expense/asset went up, or income/equity/liability came in",
                     text_color=TEXT_DIM, font=("Segoe UI", 10)).grid(row=2, column=2, sticky="w", padx=(10, 0))

        ctk.CTkLabel(card1, text="Amount*", width=140, anchor="w", font=label_font, text_color=TEXT_MUTED).grid(row=3, column=0, sticky="w", pady=8)
        self.qp_amount = ctk.CTkEntry(card1, width=200, placeholder_text=f"{CUR}0.00")
        self.qp_amount.grid(row=3, column=1, sticky="w")
        enable_quick_math(self.qp_amount)

        ctk.CTkLabel(card1, text="Date", width=140, anchor="w", font=label_font, text_color=TEXT_MUTED).grid(row=4, column=0, sticky="w", pady=8)
        self.qp_date = DatePicker(card1, width=200, default=date.today().isoformat())
        self.qp_date.grid(row=4, column=1, sticky="w")

        card2 = ctk.CTkFrame(scroll, fg_color=NAVY_CARD, corner_radius=12,
                              border_width=1, border_color=NAVY_BORDER)
        card2.pack(fill="x", ipadx=22, ipady=20)
        card_header(card2, "Offset & Details", icon="🔁",
                    subtitle="The other side of the entry, plus who it was paid to or received from.").grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 16))

        ctk.CTkLabel(card2, text="Offset Account", width=140, anchor="w", font=label_font, text_color=TEXT_MUTED).grid(row=1, column=0, sticky="w", pady=8)
        self.qp_offset = SearchableCombobox(card2, values=list(accounts.keys()), width=340)
        cash_label = next((k for k, v in accounts.items() if v == "1000"), "")
        if cash_label:
            self.qp_offset.set(cash_label)
        self.qp_offset.grid(row=1, column=1, sticky="w")
        ctk.CTkLabel(card2, text="the other side of the entry - defaults to Cash and Bank",
                     text_color=TEXT_DIM, font=("Segoe UI", 10)).grid(row=2, column=1, sticky="w")

        ctk.CTkLabel(card2, text="Description*", width=140, anchor="w", font=label_font, text_color=TEXT_MUTED).grid(row=3, column=0, sticky="w", pady=8)
        self.qp_description = ctk.CTkEntry(card2, width=340)
        self.qp_description.grid(row=3, column=1, sticky="w")

        ctk.CTkLabel(card2, text="Paid To / Received From", width=140, anchor="w", font=label_font, text_color=TEXT_MUTED).grid(row=4, column=0, sticky="w", pady=8)
        self.qp_paid_to = ctk.CTkEntry(card2, width=340, placeholder_text="Optional - vendor, payee, or source")
        self.qp_paid_to.grid(row=4, column=1, sticky="w")

        ctk.CTkLabel(card2, text="Reference", width=140, anchor="w", font=label_font, text_color=TEXT_MUTED).grid(row=5, column=0, sticky="w", pady=8)
        self.qp_reference = ctk.CTkEntry(card2, width=200)
        self.qp_reference.grid(row=5, column=1, sticky="w")

        location_options = [r["name"] for r in settings_model.list_locations(self.conn, active_only=True)]
        ctk.CTkLabel(card2, text="Location", width=140, anchor="w", font=label_font, text_color=TEXT_MUTED).grid(row=6, column=0, sticky="w", pady=8)
        self.qp_location = ctk.CTkComboBox(card2, values=["(Unallocated)"] + location_options, width=200,
                                            fg_color=NAVY_MID, button_color=BLUE_ACCENT, button_hover_color=BLUE_HOVER)
        self.qp_location.set("(Unallocated)")
        self.qp_location.grid(row=6, column=1, sticky="w")
        ctk.CTkLabel(card2, text="which branch this belongs to - only needed if it should show up on that "
                                  "branch's income statement rather than 'Unallocated'",
                     text_color=TEXT_DIM, font=("Segoe UI", 10)).grid(row=6, column=2, sticky="w", padx=(10, 0))

        ctk.CTkFrame(card2, height=1, fg_color=NAVY_BORDER).grid(row=7, column=0, columnspan=3, sticky="ew", pady=(18, 14))
        primary_button(card2, "Post Entry", self._do_quick_posting, icon="✓", width=170).grid(
            row=8, column=1, sticky="w")

    def _quick_new_expense_category(self):
        fields = [{"key": "name", "label": "Category Name*", "default": ""}]

        def submit(values):
            name = values["name"].strip()
            if not name:
                raise ValueError("Category name is required.")
            get_or_create_expense_account(self.conn, name)
            self.conn.commit()
            info(f"'{name}' expense account is ready - select it from the Account field above.")
            
            self._refresh_account_dropdowns()
            accounts = self._account_choices()
            match = next((k for k in accounts if f"- {name} (" in k), None)
            if match:
                self.qp_account.set(match)

        FormDialog(self, "New Expense Category", fields, submit)

    def _do_quick_posting(self):
        try:
            account_label = self.qp_account.get()
            offset_label = self.qp_offset.get()
            accounts = self._account_choices()
            account_code = accounts.get(account_label)
            offset_code = accounts.get(offset_label)
            if not account_code:
                raise ValueError("Select a valid account to post to.")
            if not offset_code:
                raise ValueError("Select a valid offset account.")
            if account_code == offset_code:
                raise ValueError("Account and offset account can't be the same.")
            description = self.qp_description.get().strip()
            if not description:
                raise ValueError("Description is required.")
            paid_to = self.qp_paid_to.get().strip()
            if paid_to:
                description = f"{description} (Paid To/From: {paid_to})"
            accounting.post_manual_entry(
                self.conn, entry_date=self.qp_date.get(), description=description,
                account_code_or_name=account_code, amount=parse_money(self.qp_amount.get()),
                direction=self.qp_direction.get().lower(), offset_account=offset_code,
                reference=self.qp_reference.get().strip() or None, user_id=Session.current_user["id"],
                location=(self.qp_location.get().strip() or None) if self.qp_location.get() != "(Unallocated)" else None,
            )
            self.conn.commit()
            info(f"Posted: {self.qp_direction.get()} {account_label.split(' - ')[0]} by {money(parse_money(self.qp_amount.get()))}.")
            self.qp_amount.delete(0, "end")
            self.qp_description.delete(0, "end")
            self.qp_paid_to.delete(0, "end")
            self.qp_reference.delete(0, "end")
            self.qp_location.set("(Unallocated)")
            self._refresh_recent_postings()
        except Exception as e:
            error(str(e))

    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # TAB 2: ADVANCED JOURNAL ENTRY - single ledger-style grid (tksheet)
    #
    # Every row is one journal line: Date | Description | Account | Debit |
    # Credit. Consecutive rows are grouped into one journal entry by date:
    # a row with a Date starts a new entry; a row with a blank Date
    # continues the entry above it (inheriting its Description if that's
    # also left blank) - so you only type the date/description once per
    # entry and just keep listing accounts underneath. Because the date
    # lives on the row, different entries in the same batch can carry
    # different dates and still post together in one click.
    # ------------------------------------------------------------------
    JE_COL_DATE, JE_COL_DESC, JE_COL_ACCOUNT, JE_COL_DEBIT, JE_COL_CREDIT, JE_COL_LOCATION = range(6)
    JE_HEADERS = ["Date", "Description", "Account", "Debit", "Credit", "Location"]
    JE_COL_WIDTHS = [110, 320, 320, 130, 130, 160]

    def _je_blank_row(self, entry_date=None):
        return [entry_date or "", "", "", 0.0, 0.0, ""]

    def _build_journal_entry(self, tab):
        accounts = self._account_choices()
        acc_list = list(accounts.keys())

        toolbar = ctk.CTkFrame(tab, fg_color="transparent")
        toolbar.pack(fill="x", padx=20, pady=(20, 6))
        ctk.CTkLabel(toolbar, text="📓  Journal Postings", font=("Segoe UI", 15, "bold"),
                     text_color=TEXT_PRIMARY).pack(side="left")

        primary_button(toolbar, "Add Entry", self._je_add_entry_rows, icon="+", width=120, height=32).pack(side="right")
        secondary_button(toolbar, "Add Rows", self._je_add_rows_dialog, icon="+", width=110, height=32).pack(side="right", padx=6)
        secondary_button(toolbar, "Duplicate Row", self._je_duplicate_row, icon="⧉", width=130, height=32).pack(side="right")
        secondary_button(toolbar, "Set Date", self._je_set_date_for_selection, icon="📅", width=120, height=32).pack(side="right", padx=6)
        outline_button(toolbar, "Validate", self._je_validate, icon="✔", width=110, height=32).pack(side="right", padx=6)

        hint = ctk.CTkLabel(
            tab, text="💡  Type = to calculate a cell, e.g. =1500+250. Fill Date/Description once per "
                      "entry and leave them blank on the following lines - blank lines inherit the entry above them. "
                      "In the Account column, click the cell and type to search, then press Enter to pick. "
                      "Location is optional - set it on an entry's first line to have that entry show up under "
                      "that branch on the location income statement instead of 'Unallocated'.",
            font=("Segoe UI", 11), text_color=TEXT_MUTED, anchor="w")
        hint.pack(fill="x", padx=20, pady=(0, 6))

        # Draggable divider between the entry grid and the status/post
        # footer, so the grid can be given more (or less) vertical room.
        split = resizable_split(tab, orient="vertical", bg=NAVY_DEEP)
        split.pack(fill="both", expand=True, padx=20, pady=(0, 20))

        grid_frame = ctk.CTkFrame(split, fg_color=NAVY_CARD, corner_radius=12,
                                   border_width=1, border_color=NAVY_BORDER)

        self.je_sheet = tksheet.Sheet(
            grid_frame,
            headers=list(self.JE_HEADERS),
            show_row_index=True,
            theme="dark" if ctk.get_appearance_mode() == "Dark" else "light",
        )
        self.je_sheet.enable_bindings((
            "single_select", "drag_select",
            "column_select", "row_select",
            "column_width_resize", "double_click_column_resize",
            "row_height_resize",
            "arrowkeys",
            "rc_select", "rc_popup_menu",
            "rc_insert_row", "rc_delete_row",
            "copy", "cut", "paste", "delete",
            "undo", "edit_cell",
        ))
        # Fill the whole grid_frame edge-to-edge; the sheet auto-fits its
        # host, and its last column soaks up any leftover width so the grid
        # always spans the full frame regardless of window size.
        self.je_sheet.pack(fill="both", expand=True, padx=0, pady=0)

        self.je_sheet.set_sheet_data([
            self._je_blank_row(date.today().isoformat()),
            self._je_blank_row(),
        ])
        self.je_sheet.set_column_widths(list(self.JE_COL_WIDTHS))
        self.je_sheet.create_dropdown(r="all", c=self.JE_COL_ACCOUNT, values=acc_list, state="normal")
        location_options = [r["name"] for r in settings_model.list_locations(self.conn, active_only=True)]
        self.je_sheet.create_dropdown(r="all", c=self.JE_COL_LOCATION, values=[""] + location_options, state="normal")

        # Let the Description column soak up any extra width so the grid
        # always spans the full frame edge-to-edge, however wide the window is.
        def _stretch_description_column(event=None):
            try:
                total_w = grid_frame.winfo_width()
                index_w = 40
                other_fixed = (self.JE_COL_WIDTHS[0] + self.JE_COL_WIDTHS[2] + self.JE_COL_WIDTHS[3]
                               + self.JE_COL_WIDTHS[4] + self.JE_COL_WIDTHS[5])
                new_desc_w = max(self.JE_COL_WIDTHS[1], total_w - index_w - other_fixed - 20)
                self.je_sheet.column_width(column=self.JE_COL_DESC, width=new_desc_w)
            except Exception:
                pass

        grid_frame.bind("<Configure>", _stretch_description_column)

        def _on_end_edit(event):
            row = getattr(event, "row", None)
            col = getattr(event, "column", None)
            if row is None and isinstance(event, dict):
                row, col = event.get("row"), event.get("column")
            if row is None or col is None or col not in (self.JE_COL_DEBIT, self.JE_COL_CREDIT):
                return
            value = self.je_sheet.get_cell_data(row, col)
            if isinstance(value, str) and value.strip().startswith("="):
                try:
                    result = evaluate_cell_formula(value)
                    self.je_sheet.set_cell_data(row, col, round(result, 2))
                    self.je_sheet.refresh()
                except ValueError as e:
                    error(f"Invalid formula in that cell: {e}")
            self._je_update_totals()

        self.je_sheet.extra_bindings("end_edit_cell", _on_end_edit)

        footer = ctk.CTkFrame(split, fg_color=NAVY_CARD, corner_radius=12,
                               border_width=1, border_color=NAVY_BORDER)
        self.je_status_label = ctk.CTkLabel(footer, text="", font=("Segoe UI", 11), justify="left", anchor="w")
        self.je_status_label.pack(side="left", padx=14, pady=10, fill="x", expand=True)
        self.je_totals_label = ctk.CTkLabel(footer, text="", font=("Segoe UI", 13, "bold"))
        self.je_totals_label.pack(side="left", padx=(0, 14))
        primary_button(footer, "Post All Journal Entries", self._do_post_journal_entries,
                       icon="✓", width=210).pack(side="right", padx=14, pady=10)

        split.add(grid_frame, minsize=150, stretch="always")
        split.add(footer, minsize=64, height=64, stretch="never")

        self._je_update_totals()

    # ---------------- row/entry helpers ----------------
    def _je_add_entry_rows(self):
        start = self.je_sheet.get_total_rows()
        self.je_sheet.insert_rows(rows=[
            self._je_blank_row(date.today().isoformat()),
            self._je_blank_row(),
        ], idx=start)
        accounts = self._account_choices()
        location_options = [r["name"] for r in settings_model.list_locations(self.conn, active_only=True)]
        for r in (start, start + 1):
            self.je_sheet.create_dropdown(r=r, c=self.JE_COL_ACCOUNT, values=list(accounts.keys()), state="normal")
            self.je_sheet.create_dropdown(r=r, c=self.JE_COL_LOCATION, values=[""] + location_options, state="normal")
        self.je_sheet.see(start + 1, 0)
        self._je_update_totals()

    def _je_add_rows_dialog(self):
        def do_add(values):
            raw = values.get("count", "").strip()
            if not raw.isdigit() or int(raw) < 1:
                raise ValueError("Enter a whole number of 1 or more.")
            count = min(int(raw), 200)
            start = self.je_sheet.get_total_rows()
            # Blank Date/Description so these new lines continue whichever
            # entry is currently above them.
            self.je_sheet.insert_rows(rows=[self._je_blank_row() for _ in range(count)], idx=start)
            accounts = self._account_choices()
            location_options = [r["name"] for r in settings_model.list_locations(self.conn, active_only=True)]
            for i in range(count):
                self.je_sheet.create_dropdown(r=start + i, c=self.JE_COL_ACCOUNT, values=list(accounts.keys()), state="normal")
                self.je_sheet.create_dropdown(r=start + i, c=self.JE_COL_LOCATION, values=[""] + location_options, state="normal")
            self.je_sheet.see(start + count - 1, 0)
            self._je_update_totals()

        FormDialog(self, "Add Line(s)", [
            {"key": "count", "label": "Number of lines to add", "default": "2"},
        ], do_add, width=340, height=170)

    def _je_selected_rows(self):
        try:
            rows = sorted(self.je_sheet.get_selected_rows())
            if rows:
                return rows
        except Exception:
            pass
        try:
            sel = self.je_sheet.get_currently_selected()
            row = getattr(sel, "row", None)
            if row is None and isinstance(sel, (list, tuple)) and sel:
                row = sel[0]
            if row is not None:
                return [row]
        except Exception:
            pass
        return []

    def _je_duplicate_row(self):
        rows = self._je_selected_rows()
        if not rows:
            return error("Click a row first, then Duplicate Row.")
        row_idx = rows[-1]
        data = list(self.je_sheet.get_row_data(row_idx))
        # A duplicated line continues the same entry rather than starting a
        # new one, unless the source row itself started a new entry.
        insert_at = row_idx + 1
        self.je_sheet.insert_rows(rows=[data], idx=insert_at)
        accounts = self._account_choices()
        location_options = [r["name"] for r in settings_model.list_locations(self.conn, active_only=True)]
        self.je_sheet.create_dropdown(r=insert_at, c=self.JE_COL_ACCOUNT, values=list(accounts.keys()), state="normal")
        self.je_sheet.create_dropdown(r=insert_at, c=self.JE_COL_LOCATION, values=[""] + location_options, state="normal")
        self.je_sheet.set_cell_data(insert_at, self.JE_COL_DATE, "")
        self.je_sheet.set_cell_data(insert_at, self.JE_COL_DESC, "")
        self._je_update_totals()

    def _je_set_date_for_selection(self):
        rows = self._je_selected_rows()
        if not rows:
            return error("Select one or more rows first (click a row number, or drag across rows).")

        win = ctk.CTkToplevel(self)
        win.title("Set Date")
        win.geometry("320x160")
        win.transient(self)
        win.grab_set()
        win.configure(fg_color=NAVY_DEEP)

        ctk.CTkLabel(win, text=f"Apply a date to {len(rows)} selected row(s):",
                     font=("Segoe UI", 12), text_color=TEXT_PRIMARY, wraplength=280).pack(padx=16, pady=(18, 10))
        picker = DatePicker(win, width=180, default=date.today().isoformat())
        picker.pack(padx=16)

        def apply_date():
            value = picker.get()
            try:
                date.fromisoformat(value)
            except ValueError:
                return error("That doesn't look like a valid date.")
            for r in rows:
                self.je_sheet.set_cell_data(r, self.JE_COL_DATE, value)
            self.je_sheet.refresh()
            self._je_update_totals()
            win.destroy()

        btns = ctk.CTkFrame(win, fg_color="transparent")
        btns.pack(pady=16)
        secondary_button(btns, "Cancel", win.destroy, width=100, height=32).pack(side="left", padx=6)
        primary_button(btns, "Apply", apply_date, icon="✓", width=100, height=32).pack(side="left", padx=6)

    # ---------------- grouping / validation / totals ----------------
    def _je_group_rows(self):
        """
        Groups sheet rows into journal entries. A row with a non-blank Date
        starts a new entry; a row with a blank Date continues the entry
        directly above it (and inherits that entry's Description if its own
        is also left blank). Fully blank rows are ignored. Returns a list
        of dicts: {date, description, row_idxs}.
        """
        data = self.je_sheet.get_sheet_data()
        groups = []
        current = None
        for idx, row in enumerate(data):
            row = list(row) + [""] * (6 - len(row))
            date_val = str(row[self.JE_COL_DATE]).strip()
            desc_val = str(row[self.JE_COL_DESC]).strip()
            account_val = str(row[self.JE_COL_ACCOUNT]).strip()
            debit_val = row[self.JE_COL_DEBIT]
            credit_val = row[self.JE_COL_CREDIT]
            location_val = str(row[self.JE_COL_LOCATION]).strip()
            fully_blank = not any([date_val, desc_val, account_val, debit_val, credit_val, location_val])
            if fully_blank:
                continue
            if date_val:
                current = {"date": date_val, "description": desc_val, "location": location_val, "row_idxs": [idx]}
                groups.append(current)
            else:
                if current is None:
                    current = {"date": "", "description": desc_val, "location": location_val, "row_idxs": [idx]}
                    groups.append(current)
                else:
                    current["row_idxs"].append(idx)
                    if desc_val:
                        current["description"] = desc_val
                    if location_val:
                        current["location"] = location_val
        return groups

    def _je_cell_amount(self, row_idx, col):
        """Returns the cell's value as INTEGER CENTS - this feeds directly
        into post_manual_journal()'s debit/credit lines."""
        raw = self.je_sheet.get_cell_data(row_idx, col)
        text = str(raw).strip()
        if not text:
            return 0
        if text.startswith("="):
            try:
                return to_cents(evaluate_cell_formula(text))
            except ValueError:
                return 0
        try:
            return to_cents(text.replace(",", "").replace(CUR, ""))
        except ValueError:
            return 0

    def _je_validate(self, silent=False):
        """Recomputes groups, tints each entry's rows green (balanced) or
        amber (not balanced) and returns (groups, all_balanced)."""
        groups = self._je_group_rows()
        try:
            self.je_sheet.dehighlight_rows(rows="all", redraw=False)
        except Exception:
            pass

        all_balanced = True
        status_lines = []
        grand_debit = grand_credit = 0
        for i, g in enumerate(groups, start=1):
            debit = sum(self._je_cell_amount(r, self.JE_COL_DEBIT) for r in g["row_idxs"])
            credit = sum(self._je_cell_amount(r, self.JE_COL_CREDIT) for r in g["row_idxs"])
            grand_debit += debit
            grand_credit += credit
            balanced = debit == credit and debit > 0 and g["date"] != ""
            g["balanced"] = balanced
            g["debit"] = debit
            g["credit"] = credit
            if not balanced:
                all_balanced = False
            color = "#1e3d2f" if balanced else "#4a2f12"
            try:
                self.je_sheet.highlight_rows(rows=g["row_idxs"], bg=color, redraw=False)
            except Exception:
                pass
            label = g["description"] or g["date"] or f"Entry {i}"
            if not g["date"]:
                status_lines.append(f"{label}: missing date")
            elif balanced:
                status_lines.append(f"{label}: balanced ({money(debit)})")
            else:
                status_lines.append(f"{label}: off by {money(abs(debit - credit))}")

        try:
            self.je_sheet.redraw()
        except Exception:
            pass

        n = len(groups)
        self.je_status_label.configure(
            text=(f"{n} journal entr{'y' if n == 1 else 'ies'}   |   " + "   •   ".join(status_lines))
            if groups else "No journal lines entered yet.")
        self.je_totals_label.configure(
            text=f"Debit {money(grand_debit)}   Credit {money(grand_credit)}",
            text_color=("#27AE60" if all_balanced and groups else "#EB5757"))

        if not silent:
            if not groups:
                info("No journal lines to validate yet.")
            elif all_balanced:
                info(f"All {n} journal entr{'y' if n == 1 else 'ies'} balance.")
            else:
                error("One or more entries don't balance yet - see the highlighted rows.")
        return groups, all_balanced

    def _je_update_totals(self):
        self._je_validate(silent=True)

    def _do_post_journal_entries(self):
        try:
            groups, all_balanced = self._je_validate(silent=True)
            if not groups:
                raise ValueError("Enter at least one journal line first.")

            accounts = self._account_choices()
            batches = []
            for i, g in enumerate(groups, start=1):
                label = g["description"] or f"entry {i}"
                if not g["date"]:
                    raise ValueError(f"Entry ({label}): missing a date on its first line.")
                try:
                    date.fromisoformat(g["date"])
                except ValueError:
                    raise ValueError(f"Entry ({label}): '{g['date']}' isn't a valid date (use YYYY-MM-DD).")
                description = g["description"].strip()
                if not description:
                    raise ValueError(f"Entry ({label}): description is required.")

                lines = []
                for r in g["row_idxs"]:
                    account_label = str(self.je_sheet.get_cell_data(r, self.JE_COL_ACCOUNT)).strip()
                    debit = self._je_cell_amount(r, self.JE_COL_DEBIT)
                    credit = self._je_cell_amount(r, self.JE_COL_CREDIT)
                    if not account_label and not debit and not credit:
                        continue
                    if not account_label:
                        raise ValueError(f"Entry ({label}): a line has an amount but no account selected.")
                    account_code = accounts.get(account_label)
                    if not account_code:
                        raise ValueError(f"Entry ({label}): '{account_label}' is not a valid account.")
                    if debit and credit:
                        raise ValueError(f"Entry ({label}): '{account_label}' has both a debit and a credit - use one or the other.")
                    if not debit and not credit:
                        continue
                    lines.append({"account": account_code, "debit": debit, "credit": credit})

                if len(lines) < 2:
                    raise ValueError(f"Entry ({label}): needs at least 2 lines with an account and an amount.")

                batches.append({
                    "entry_date": g["date"],
                    "description": description,
                    "lines": lines,
                    "location": g.get("location") or None,
                })

            posted_ids = []
            for batch in batches:
                journal_id = accounting.post_manual_journal(
                    self.conn, entry_date=batch["entry_date"], description=batch["description"],
                    lines=batch["lines"], user_id=Session.current_user["id"], location=batch["location"],
                )
                posted_ids.append(journal_id)
            self.conn.commit()

            n = len(posted_ids)
            ref_list = ", ".join(f"#{j}" for j in posted_ids)
            info(f"{n} journal entr{'y' if n == 1 else 'ies'} posted (Journal {ref_list}).")

            self.je_sheet.set_sheet_data([
                self._je_blank_row(date.today().isoformat()),
                self._je_blank_row(),
            ])
            accounts_now = self._account_choices()
            location_options = [r["name"] for r in settings_model.list_locations(self.conn, active_only=True)]
            self.je_sheet.create_dropdown(r="all", c=self.JE_COL_ACCOUNT, values=list(accounts_now.keys()), state="normal")
            self.je_sheet.create_dropdown(r="all", c=self.JE_COL_LOCATION, values=[""] + location_options, state="normal")
            self._je_update_totals()
            self._refresh_recent_postings()
        except accounting.UnbalancedEntryError as e:
            self.conn.rollback()
            error(str(e))
        except Exception as e:
            self.conn.rollback()
            error(str(e))

    # ------------------------------------------------------------------
    # TAB: BUDGETS
    # ------------------------------------------------------------------
    def _budgetable_accounts(self):
        accounts = coa_model.list_accounts(self.conn)
        return [a for a in accounts if a["type"] in ("Income", "Expense")]

    def _build_budgets(self, tab):
        ctk.CTkLabel(tab, text="🎯  Budgets", font=("Segoe UI", 15, "bold"),
                     text_color=TEXT_PRIMARY, anchor="w").pack(fill="x", padx=20, pady=(20, 8))
        bar = ctk.CTkFrame(tab, fg_color="transparent")
        bar.pack(fill="x", padx=20, pady=(0, 6))
        primary_button(bar, "New Budget", self._new_budget, icon="+", width=130, height=32).pack(side="left")
        success_button(bar, "Import from Excel", self._import_budget_excel, icon="⇪", width=160, height=32).pack(side="left", padx=6)
        secondary_button(bar, "Edit Selected", self._edit_budget, icon="✎", width=130, height=32).pack(side="left", padx=6)
        danger_button(bar, "Delete Selected", self._delete_budget, icon="🗑", width=140, height=32).pack(side="left", padx=6)
        outline_button(bar, "View Monthly Detail", self._view_budget_detail, width=170, height=32).pack(side="left", padx=6)
        primary_button(bar, "Reconcile Selected", self._reconcile_budget, icon="⇄", width=170, height=32).pack(side="left", padx=6)
        secondary_button(bar, "Refresh", self._refresh_budgets_list, icon="↻", width=110, height=32).pack(side="right")

        self.budgets_table = DataTable(tab, columns=[
            ("name", "Name"),
            ("year", "Year"),
            ("total_income_budget", "Budgeted Income (Full Year)"),
            ("total_expense_budget", "Budgeted Expense (Full Year)"),
            ("notes", "Notes"),
        ], title="Budgets", show_summary=False)
        self.budgets_table.pack(fill="both", expand=True, padx=20, pady=(0, 20))
        self._refresh_budgets_list()

    def _refresh_budgets_list(self):
        rows = budget_model.list_budgets(self.conn)
        self.budgets_table.set_rows([{
            "id": r["id"], "name": r["name"], "year": r["year"],
            "total_income_budget": money(r["total_income_budget"]),
            "total_expense_budget": money(r["total_expense_budget"]),
            "notes": r["notes"] or "",
        } for r in rows])

    def _selected_budget_id(self):
        row = self.budgets_table.selected_row()
        if not row:
            error("Select a budget first.")
            return None
        return int(row["id"])

    # ---------------- Manual line-item editor (tksheet Implementation) ----------------
    def _budget_editor(self, title, existing=None):
        """
        Shared Toplevel editor for creating/editing a budget utilizing tksheet
        for a 12-month spreadsheet layout.
        """
        win = ctk.CTkToplevel(self)
        win.title(title)
        win.geometry("1100x620")
        win.transient(self)
        win.grab_set()

        # --- Top Layout (Name, Year, Notes) ---
        top = ctk.CTkFrame(win, fg_color="transparent")
        top.pack(fill="x", padx=16, pady=(16, 6))
        
        ctk.CTkLabel(top, text="Budget Name*", width=100, anchor="w").grid(row=0, column=0, sticky="w", pady=6)
        name_entry = ctk.CTkEntry(top, width=280)
        name_entry.grid(row=0, column=1, sticky="w")

        ctk.CTkLabel(top, text="Year*", width=60, anchor="w").grid(row=0, column=2, sticky="w", padx=(20, 6))
        year_entry = ctk.CTkEntry(top, width=90)
        year_entry.insert(0, str(date.today().year))
        year_entry.grid(row=0, column=3, sticky="w")

        ctk.CTkLabel(top, text="Notes", width=100, anchor="w").grid(row=1, column=0, sticky="w", pady=6)
        notes_entry = ctk.CTkEntry(top, width=500)
        notes_entry.grid(row=1, column=1, columnspan=3, sticky="w")

        if existing:
            name_entry.delete(0, "end"); name_entry.insert(0, existing["budget"]["name"])
            year_entry.delete(0, "end"); year_entry.insert(0, str(existing["budget"]["year"]))
            if existing["budget"]["notes"]:
                notes_entry.insert(0, existing["budget"]["notes"])

        # --- Accounts Setup for Dropdown ---
        accounts = self._budgetable_accounts()
        account_map = {f"{a['code']} - {a['name']}": a["id"] for a in accounts}
        account_choices = ["(none)"] + list(account_map.keys())

        # Reconciliation-source choices for the reserved "Recon Source" column.
        recon_source_choices = ["(auto)"] + list(budget_model.RECON_SOURCES.keys())

        def _is_recon_source_header(header_name: str) -> bool:
            return (header_name or "").strip().lower() == budget_model.RECON_SOURCE_COLUMN.lower()

        def _apply_recon_dropdown(col_idx: int):
            self.sheet.create_dropdown(r="all", c=col_idx, values=recon_source_choices, set_value="(auto)")

        CORE_COLS = 3
        num_month_cols = len(budget_model.MONTH_LABELS)

        # --- Controls (Add Line / Column tools) ---
        controls_frame = ctk.CTkFrame(win, fg_color="transparent")
        controls_frame.pack(fill="x", padx=16, pady=(10, 0))

        ctk.CTkLabel(controls_frame, text="Line Items", font=("Segoe UI", 12, "bold")).pack(side="left")

        def add_sheet_line():
            def do_add(values):
                raw = values.get("count", "").strip()
                if not raw.isdigit() or int(raw) < 1:
                    raise ValueError("Enter a whole number of 1 or more.")
                count = min(int(raw), 500)

                # Get the strict current total rows to prevent visual gaps
                start_idx = self.sheet.get_total_rows()
                total_cols = self.sheet.total_columns()
                blank_row = ["", "", "(none)"] + [0.0] * (total_cols - CORE_COLS)

                # Insert exactly at the current bottom index rather than "end"
                self.sheet.insert_rows(rows=[list(blank_row) for _ in range(count)], idx=start_idx)

                for i in range(count):
                    row_idx = start_idx + i
                    # Re-apply the account dropdown to the new row
                    self.sheet.create_dropdown(r=row_idx, c=2, values=account_choices, set_value="(none)")
                    
                    # Re-apply reconciliation dropdowns if extra columns exist
                    for j, col_name in enumerate(saved_extra_columns):
                        if _is_recon_source_header(col_name):
                            self.sheet.create_dropdown(r=row_idx, c=CORE_COLS + num_month_cols + j, values=recon_source_choices, set_value="(auto)")

                self.sheet.see(start_idx + count - 1, 0)

            FormDialog(win, "Add Line(s)", [
                {"key": "count", "label": "Number of lines to add", "default": "1"},
            ], do_add, width=340, height=170)

        primary_button(controls_frame, "Add Line", add_sheet_line, icon="+", width=110, height=32).pack(side="right")

        # --- Column tools ---
        col_tools = ctk.CTkFrame(win, fg_color="transparent")
        col_tools.pack(fill="x", padx=16, pady=(6, 0))
        ctk.CTkLabel(col_tools, text="Columns", font=("Segoe UI", 12, "bold")).pack(side="left")

        def _selected_column():
            try:
                sel = self.sheet.get_currently_selected()
                col = getattr(sel, "column", None)
                if col is None and isinstance(sel, (list, tuple)) and len(sel) >= 2:
                    col = sel[1]
                return col
            except Exception:
                return None

        def add_extra_column():
            def do_add(values):
                name = values.get("name", "").strip()
                if not name:
                    raise ValueError("Enter a column name.")
                self.sheet.headers(newheaders=self.sheet.headers() + [name])
                new_col_idx = self.sheet.total_columns()
                default_val = "(auto)" if _is_recon_source_header(name) else ""
                self.sheet.insert_column(values=[default_val] * self.sheet.get_total_rows(), idx="end")
                self.sheet.set_column_widths(list(self.sheet.get_column_widths()) + [100])
                if _is_recon_source_header(name):
                    _apply_recon_dropdown(new_col_idx)

            FormDialog(win, "Add Column", [
                {"key": "name", "label": "Column name", "default": ""},
            ], do_add, width=340, height=170)

        def remove_selected_column():
            col = _selected_column()
            if col is None:
                error("Click a cell in the column you want to remove first.")
                return
            if col < CORE_COLS + num_month_cols:
                error("The Section, Label, Account, and month columns can't be removed - "
                      "only extra columns you've added can be.")
                return
            header = self.sheet.headers()[col]
            if not confirm(f"Remove column '{header}'? Any data in it will be lost."):
                return
            self.sheet.delete_columns([col])

        def fit_columns():
            try:
                self.sheet.set_all_column_widths()
            except Exception:
                pass 

        secondary_button(col_tools, "Fit Columns", fit_columns, icon="↔", width=120, height=32).pack(side="right", padx=(6, 0))
        danger_button(col_tools, "Remove Column", remove_selected_column, icon="-", width=140, height=32).pack(side="right", padx=(6, 0))
        primary_button(col_tools, "Add Column", add_extra_column, icon="+", width=120, height=32).pack(side="right")

        # --- Spreadsheet Setup ---
        grid_frame = ctk.CTkFrame(win)
        grid_frame.pack(fill="both", expand=True, padx=16, pady=10)
        
        saved_extra_columns = (existing.get("extra_columns") or []) if existing else []
        headers = ["Section", "Label", "Account"] + budget_model.MONTH_LABELS + saved_extra_columns

        self.sheet = tksheet.Sheet(
            grid_frame,
            headers=headers,
            show_row_index=True,
            theme="dark" if ctk.get_appearance_mode() == "Dark" else "light"
        )

        # Removed 'rc_insert_row' and 'rc_insert_column' to protect dropdowns.
        # Added 'column_select' and 'row_select' to ensure headers register clicks robustly.
        self.sheet.enable_bindings((
            "single_select", "drag_select",
            "column_select", "row_select",
            "column_width_resize", "double_click_column_resize",
            "row_height_resize",
            "arrowkeys", 
            "rc_select", "rc_popup_menu", 
            "rc_delete_row", "rc_delete_column", 
            "copy", "cut", "paste", "delete",
            "undo", "edit_cell"
        ))
        
        self.sheet.pack(fill="both", expand=True)

        def _formula_event_rc(event):
            row = getattr(event, "row", None)
            col = getattr(event, "column", None)
            if row is None and isinstance(event, dict):
                row, col = event.get("row"), event.get("column")
            if row is None and isinstance(event, (list, tuple)) and len(event) >= 3:
                row, col = event[1], event[2]
            return row, col

        def _on_end_edit(event):
            row, col = _formula_event_rc(event)
            if row is None or col is None or col < CORE_COLS:
                return  
            value = self.sheet.get_cell_data(row, col)
            if isinstance(value, str) and value.strip().startswith("="):
                try:
                    result = evaluate_cell_formula(value)
                    self.sheet.set_cell_data(row, col, round(result, 2))
                    self.sheet.refresh()
                except ValueError as e:
                    error(f"Invalid formula in that cell: {e}")

        self.sheet.extra_bindings("end_edit_cell", _on_end_edit)

        # --- Load Existing Data or Minimal Empty Rows ---
        sheet_data = []
        if existing and existing.get("items"):
            for it in existing["items"]:
                acc_val = "(none)"
                if it.get("account_id"):
                    acc_val = next((k for k, v in account_map.items() if v == it["account_id"]), "(none)")
                
                item_extra = it.get("extra") or {}
                row = (
                    [it.get("section", ""), it.get("label", ""), acc_val]
                    + [money_edit_str(v) for v in it.get("monthly", [0] * 12)]
                    + [item_extra.get(col, "") for col in saved_extra_columns]
                )

                sheet_data.append(row)
        else:
            # Start clean with just 1 empty row by default so you don't get flooded with blanks
            sheet_data.append(["", "", "(none)"] + ["0.00"]*12)

        # 1. LOAD THE DATA FIRST
        self.sheet.set_sheet_data(sheet_data)

        # 2. APPLY WIDTHS AND DROPDOWNS AFTER DATA IS LOADED
        self.sheet.set_column_widths([120, 180, 250] + [80] * 12 + [100] * len(saved_extra_columns))
        self.sheet.create_dropdown(r="all", c=2, values=account_choices, set_value="(none)")

        for i, col_name in enumerate(saved_extra_columns):
            if _is_recon_source_header(col_name):
                self.sheet.create_dropdown(r="all", c=CORE_COLS + num_month_cols + i, values=recon_source_choices)

        # --- Footer and Save Logic ---
        footer = ctk.CTkFrame(win, fg_color="transparent")
        footer.pack(fill="x", padx=16, pady=(6, 16))

        def submit():
            try:
                name = name_entry.get().strip()
                if not name:
                    raise ValueError("Budget name is required.")
                
                year_str = year_entry.get().strip()
                if not year_str.isdigit():
                    raise ValueError("Year must be a valid number.")
                year = int(year_str)
                
                raw_data = self.sheet.get_sheet_data()
                sheet_headers = self.sheet.headers()
                extra_headers = sheet_headers[CORE_COLS + num_month_cols:]
                sections = []
                
                for row in raw_data:
                    if not any(row): continue
                    
                    section_val = str(row[0]).strip() if row[0] else "General"
                    label_val = str(row[1]).strip() if row[1] else ""
                    
                    if not label_val: 
                        continue
                        
                    account_str = str(row[2]) if row[2] else "(none)"
                    account_id = account_map.get(account_str, None)
                    
                    monthly_vals = []
                    for val in row[3:3 + num_month_cols]:
                        try:
                            text_val = str(val).strip()
                            if text_val.startswith("="):
                                monthly_vals.append(to_cents(evaluate_cell_formula(text_val)))
                                continue
                            clean_val = text_val.replace(",", "").replace("$", "")
                            monthly_vals.append(to_cents(clean_val) if clean_val else 0)
                        except ValueError:
                            monthly_vals.append(0)

                    section_entry = {
                        "section": section_val,
                        "label": label_val,
                        "account_id": account_id,
                        "monthly": monthly_vals
                    }

                    if extra_headers:
                        extra_vals = row[CORE_COLS + num_month_cols:]
                        section_entry["extra"] = {
                            h: extra_vals[i] if i < len(extra_vals) else ""
                            for i, h in enumerate(extra_headers)
                        }

                    sections.append(section_entry)

                if not sections:
                    raise ValueError("Add at least one line item with a label.")

                if existing:
                    budget_model.update_budget(
                        self.conn, existing["budget"]["id"], name=name, year=year,
                        sections=sections, notes=notes_entry.get().strip() or None,
                    )
                    info(f"Budget '{name}' updated.")
                else:
                    budget_model.create_budget(
                        self.conn, name=name, year=year, sections=sections,
                        notes=notes_entry.get().strip() or None,
                        user_id=Session.current_user["id"],
                    )
                    info(f"Budget '{name}' created.")
                
                win.destroy()
                self._refresh_budgets_list()
                
            except Exception as e:
                error(str(e))

        primary_button(footer, "Save Budget", submit, icon="✓", width=150).pack(side="right")

    def _new_budget(self):
        self._budget_editor("New Budget")

    def _edit_budget(self):
        budget_id = self._selected_budget_id()
        if not budget_id:
            return
        existing = budget_model.get_budget(self.conn, budget_id)
        self._budget_editor(f"Edit Budget - {existing['budget']['name']}", existing=existing)

    def _delete_budget(self):
        budget_id = self._selected_budget_id()
        if not budget_id:
            return
        row = self.budgets_table.selected_row()
        if not confirm(f"Delete budget '{row['name']}'? This cannot be undone."):
            return
        budget_model.delete_budget(self.conn, budget_id)
        info("Budget deleted.")
        self._refresh_budgets_list()

    # ---------------- Excel import ----------------
    def _import_budget_excel(self):
        path = filedialog.askopenfilename(
            title="Select Budget/Forecast Excel File",
            filetypes=[("Excel files", "*.xlsx *.xlsm")],
        )
        if not path:
            return
        try:
            detected_year, sections = budget_model.parse_budget_excel(self.conn, path)
        except Exception as e:
            return error(str(e))

        n_lines = len(sections)
        default_name = "Imported Forecast"

        def submit(values):
            name = values["name"].strip()
            if not name:
                raise ValueError("Budget name is required.")
            year = int(values["year"])
            budget_model.import_budget_from_excel(
                self.conn, path, name=name, year=year,
                notes=values.get("notes") or None, user_id=Session.current_user["id"],
            )
            info(f"Imported '{name}' - {n_lines} line item(s) for {year}.")
            self._refresh_budgets_list()

        FormDialog(self, "Import Budget from Excel", [
            {"key": "name", "label": "Budget Name*", "default": default_name},
            {"key": "year", "label": "Year*", "default": str(detected_year)},
            {"key": "notes", "label": "Notes", "default": ""},
        ], submit)

    # ---------------- Monthly detail (read-only forecast view) ----------------
    def _view_budget_detail(self):
        budget_id = self._selected_budget_id()
        if not budget_id:
            return
        data = budget_model.get_budget(self.conn, budget_id)
        budget = data["budget"]

        win = ctk.CTkToplevel(self)
        win.title(f"Monthly Detail - {budget['name']}")
        win.geometry("1200x600")
        win.transient(self)
        win.grab_set()

        ctk.CTkLabel(win, text=f"{budget['name']}  ({budget['year']})",
                     font=("Segoe UI", 15, "bold")).pack(anchor="w", padx=16, pady=(16, 6))

        columns = [("section", "Section"), ("label", "Label")]
        columns += [(f"m{i+1}", m) for i, m in enumerate(budget_model.MONTH_LABELS)]
        columns += [("full_year", "Full Year")]
        table = DataTable(win, columns=columns, title=f"Monthly Detail - {budget['name']}", show_summary=False)
        table.pack(fill="both", expand=True, padx=16, pady=(4, 16))
        table.set_rows([{
            "section": it["section"], "label": it["label"],
            **{f"m{i+1}": money(it["monthly"][i]) for i in range(12)},
            "full_year": money(it["full_year"]),
        } for it in data["items"]])

    # ---------------- Reconciliation ----------------
    def _reconcile_budget(self):
        budget_id = self._selected_budget_id()
        if not budget_id:
            return
        budget = budget_model.get_budget(self.conn, budget_id)["budget"]
        is_current_year = budget["year"] == date.today().year
        default_month = date.today().month if is_current_year else 12
        default_quarter = (default_month - 1) // 3 + 1

        def month_options():
            return [f"{i} - {m}" for i, m in enumerate(budget_model.MONTH_LABELS, start=1)]

        def quarter_options():
            return [
                f"Q{q} ({budget_model.MONTH_LABELS[(q - 1) * 3]}-{budget_model.MONTH_LABELS[(q - 1) * 3 + 2]})"
                for q in range(1, 5)
            ]

        def render(period_type, period_value):
            result = budget_model.budget_vs_actual(self.conn, budget_id,
                                                     period_type=period_type, period_value=period_value)

            for w in list(win_body.winfo_children()):
                w.destroy()

            ctk.CTkLabel(win_body, text=result["period_label"],
                         font=("Segoe UI", 12), text_color=TEXT_MUTED).pack(anchor="w", pady=(0, 4))

            totals = ctk.CTkFrame(win_body, fg_color="transparent")
            totals.pack(fill="x", pady=(0, 6))
            income_color = "#27AE60" if result["total_income_actual"] >= result["total_income_budget"] else "#EB5757"
            expense_color = "#27AE60" if result["total_expense_actual"] <= result["total_expense_budget"] else "#EB5757"
            net_color = "#27AE60" if result["net_actual"] >= result["net_budgeted"] else "#EB5757"
            ctk.CTkLabel(totals, text=f"Income: {money(result['total_income_actual'])} of {money(result['total_income_budget'])} budgeted",
                         font=("Segoe UI", 12, "bold"), text_color=income_color).pack(side="left", padx=(0, 24))
            ctk.CTkLabel(totals, text=f"Expense: {money(result['total_expense_actual'])} of {money(result['total_expense_budget'])} budgeted",
                         font=("Segoe UI", 12, "bold"), text_color=expense_color).pack(side="left", padx=(0, 24))
            ctk.CTkLabel(totals, text=f"Net: {money(result['net_actual'])} vs {money(result['net_budgeted'])} budgeted",
                         font=("Segoe UI", 12, "bold"), text_color=net_color).pack(side="left")

            table = DataTable(win_body, columns=[
                ("section", "Section"), ("label", "Label"), ("account_code", "Account"),
                ("recon_source", "Recon Source"),
                ("budgeted_to_date", "Budgeted (Period)"), ("actual_to_date", "Actual (Period)"),
                ("variance", "Variance"), ("budgeted_full_year", "Budgeted (Full Year)"),
            ], title=f"Reconcile - {budget['name']}", show_summary=False)
            table.pack(fill="both", expand=True, pady=(4, 0))
            table.set_rows([{
                "section": r["section"], "label": r["label"], "account_code": r["account_code"] or "-",
                "recon_source": (
                    r["account_code"] and "-"  
                    or (r.get("recon_source") and (
                        r["recon_source"] if r["recon_source"] in budget_model.RECON_SOURCES
                        else f"{r['recon_source']} (unrecognized)"
                    ))
                    or "auto-detect"
                ),
                "budgeted_to_date": money(r["budgeted_to_date"]),
                "actual_to_date": money(r["actual_to_date"]) if r["actual_to_date"] is not None else "-",
                "variance": money(r["variance"]) if r["variance"] is not None else "-",
                "budgeted_full_year": money(r["budgeted_full_year"]),
            } for r in result["items"]])

        def on_value_change(v):
            ptype = period_type_combo.get()
            if ptype == "Monthly":
                render("monthly", int(v.split(" - ")[0]))
            elif ptype == "Quarterly":
                render("quarterly", int(v[1]))
            else:
                render("ytd", int(v.split(" - ")[0]))

        def on_type_change(ptype):
            if ptype == "Monthly":
                value_label.configure(text="Month:")
                opts = month_options()
                default_val = f"{default_month} - {budget_model.MONTH_LABELS[default_month - 1]}"
            elif ptype == "Quarterly":
                value_label.configure(text="Quarter:")
                opts = quarter_options()
                default_val = opts[default_quarter - 1]
            else:
                value_label.configure(text="Through month:")
                opts = month_options()
                default_val = f"{default_month} - {budget_model.MONTH_LABELS[default_month - 1]}"

            period_value_combo.configure(values=opts)
            period_value_combo.set(default_val)
            on_value_change(default_val)

        win = ctk.CTkToplevel(self)
        win.title(f"Reconcile - {budget['name']}")
        win.geometry("980x620")
        win.transient(self)
        win.grab_set()

        header = ctk.CTkFrame(win, fg_color="transparent")
        header.pack(fill="x", padx=16, pady=(16, 6))
        ctk.CTkLabel(header, text=f"{budget['name']}  ({budget['year']})",
                     font=("Segoe UI", 15, "bold")).pack(side="left")

        ctk.CTkLabel(header, text="  View:", font=("Segoe UI", 12)).pack(side="left", padx=(20, 6))
        period_type_combo = ctk.CTkComboBox(header, values=["Monthly", "Quarterly", "Year to Date"],
                                             width=140, command=on_type_change)
        period_type_combo.set("Year to Date")
        period_type_combo.pack(side="left")

        value_label = ctk.CTkLabel(header, text="Through month:", font=("Segoe UI", 12))
        value_label.pack(side="left", padx=(16, 6))
        period_value_combo = ctk.CTkComboBox(header, width=170, command=on_value_change)
        period_value_combo.pack(side="left")

        win_body = ctk.CTkFrame(win, fg_color="transparent")
        win_body.pack(fill="both", expand=True, padx=16, pady=(4, 16))

        # Initialize with the default Year-to-Date view
        period_value_combo.configure(values=month_options())
        period_value_combo.set(f"{default_month} - {budget_model.MONTH_LABELS[default_month - 1]}")
        render("ytd", default_month)

    # ------------------------------------------------------------------
    # TAB 3: RECENT POSTINGS (audit trail for this module)
    # ------------------------------------------------------------------
    def _build_recent_postings(self, tab):
        ctk.CTkLabel(tab, text="🕑  Recent Postings", font=("Segoe UI", 15, "bold"),
                     text_color=TEXT_PRIMARY, anchor="w").pack(fill="x", padx=20, pady=(20, 8))
        bar = ctk.CTkFrame(tab, fg_color=NAVY_CARD, corner_radius=10, border_width=1, border_color=NAVY_BORDER)
        bar.pack(fill="x", padx=20, pady=(0, 6), ipady=10)

        ctk.CTkLabel(bar, text="From", font=("Segoe UI", 12), text_color=TEXT_MUTED).pack(side="left", padx=(14, 6))
        self.mp_from = DatePicker(bar, width=140, default="")
        self.mp_from.pack(side="left", padx=(0, 16))

        ctk.CTkLabel(bar, text="To", font=("Segoe UI", 12), text_color=TEXT_MUTED).pack(side="left", padx=(0, 6))
        self.mp_to = DatePicker(bar, width=140, default="")
        self.mp_to.pack(side="left", padx=(0, 16))

        primary_button(bar, "Search", self._refresh_recent_postings, icon="🔍", width=120, height=32).pack(side="left")

        self.recent_postings_table = DataTable(tab, columns=[
            ("date", "Date"), ("description", "Description"),
            ("account", "Account"), ("dr", "Debit"), ("cr", "Credit"), ("location", "Location"),
        ], title="Manual Journal Entries")
        
        self.recent_postings_table.pack(fill="both", expand=True, padx=20, pady=(10, 20))
        self._refresh_recent_postings()

    def _refresh_recent_postings(self):
        date_from = self.mp_from.get().strip() or None
        date_to = self.mp_to.get().strip() or None
        
        rows = accounting.list_manual_entries(self.conn, date_from=date_from, date_to=date_to)
        
        self.recent_postings_table.set_rows([{
            "date": r["date"], 
            "description": r["description"],
            "account": r["account"], 
            "dr": money(r["dr"]) if r["dr"] else "", 
            "cr": money(r["cr"]) if r["cr"] else "",
            "location": r["location"] or "Unallocated",
        } for r in rows])
                        
# PAYROLL (Zimbabwe statutory payroll - PAYE, AIDS Levy, NSSA, ZIMDEF)
# =====================================================================
class PayrollView(BaseView):
    """
    Six sub-tabs:
      - Employees: the staff master file plus each employee's recurring allowances/deductions.
      - Payroll Run: create a pay period, generate payslips, post the period.
      - Leave: leave types, opening balances, recording leave taken, and each
        employee's running opening/accrued/taken/closing balance. Purely
        informational - it doesn't change pay; leave taken just shows on
        the payslip.
      - Reports: the ZIMRA PAYE schedule and the NSSA P4 schedule.
      - Statutory Rates: Configure NSSA, ZIMDEF, AIDS Levy, and Tax ceilings.
      - PAYE Tax Bands: Configure progressive ZIMRA tax tables.
    """
    def __init__(self, master, conn, app):
        super().__init__(master, conn, app)
        self.header("Payroll")
        self.tabs = ctk.CTkTabview(self)
        self.tabs.pack(fill="both", expand=True)
        
        for t in ["Employees", "Payroll Run", "Leave", "Reports", "Statutory Rates", "PAYE Tax Bands"]:
            self.tabs.add(t)
            
        self._build_employees(self.tabs.tab("Employees"))
        self._build_payroll_run(self.tabs.tab("Payroll Run"))
        self._build_leave(self.tabs.tab("Leave"))
        self._build_reports(self.tabs.tab("Reports"))
        self._build_statutory_rates(self.tabs.tab("Statutory Rates"))
        self._build_paye_bands(self.tabs.tab("PAYE Tax Bands"))

    # ------------------------------------------------------------------
    # TAB 1: EMPLOYEES
    # ------------------------------------------------------------------
    def _build_employees(self, tab):
        bar = ctk.CTkFrame(tab, fg_color="transparent")
        bar.pack(fill="x", padx=20, pady=(20, 6))
        ctk.CTkButton(bar, text="+ New Employee", command=self._new_employee).pack(side="left")
        ctk.CTkButton(bar, text="Edit Selected", command=self._edit_employee).pack(side="left", padx=6)
        ctk.CTkButton(bar, text="Terminate Selected", fg_color="#EB5757", hover_color="#C0392B",
                      command=self._terminate_employee).pack(side="left", padx=6)
        ctk.CTkButton(bar, text="+ Allowance/Deduction", command=self._add_earning_or_deduction
                      ).pack(side="left", padx=(15, 6))

        self.emp_table = DataTable(tab, columns=[
            ("employee_no", "Emp #"), ("name", "Name"), ("job_title", "Job Title"),
            ("department", "Department"), ("basic_salary", "Basic Salary"),
            ("pay_frequency", "Frequency"), ("active", "Active"),
        ])
        self.emp_table.pack(fill="both", expand=True, padx=20, pady=(0, 20))
        self._refresh_employees()

    def _refresh_employees(self):
        rows = payroll_model.list_employees(self.conn)
        self.emp_table.set_rows([{
            "id": e["id"], "employee_no": e["employee_no"],
            "name": f"{e['first_name']} {e['last_name']}",
            "job_title": e["job_title"] or "", "department": e["department"] or "",
            "basic_salary": money(e["basic_salary"]), "pay_frequency": e["pay_frequency"],
            "active": "Yes" if e["active"] else "No",
        } for e in rows])

    def _employee_fields(self, emp=None):
        return [
            {"key": "first_name", "label": "First Name*", "default": emp["first_name"] if emp else ""},
            {"key": "last_name", "label": "Surname*", "default": emp["last_name"] if emp else ""},
            {"key": "national_id", "label": "National ID", "default": emp["national_id"] if emp else ""},
            {"key": "job_title", "label": "Job Title", "default": emp["job_title"] if emp else ""},
            {"key": "department", "label": "Department", "default": emp["department"] if emp else ""},
            {"key": "hire_date", "label": "Hire Date", "type": "date",
             "default": emp["hire_date"] if emp else date.today().isoformat()},
            {"key": "employment_type", "label": "Employment Type", "type": "combobox",
             "options": ["Permanent", "Contract", "Casual"],
             "default": emp["employment_type"] if emp else "Permanent"},
            {"key": "pay_currency", "label": "Pay Currency", "type": "combobox",
             "options": ["USD", "ZWG"], "default": emp["pay_currency"] if emp else "USD"},
            {"key": "pay_frequency", "label": "Pay Frequency", "type": "combobox",
             "options": ["monthly", "weekly", "fortnightly"],
             "default": emp["pay_frequency"] if emp else "monthly"},
            {"key": "basic_salary", "label": "Basic Salary*", "type": "money", "default": money_edit_str(emp["basic_salary"]) if emp else ""},
            {"key": "bank_name", "label": "Bank Name", "default": emp["bank_name"] if emp else ""},
            {"key": "bank_account_no", "label": "Bank Account No.", "default": emp["bank_account_no"] if emp else ""},
            {"key": "nssa_number", "label": "NSSA Number", "default": emp["nssa_number"] if emp else ""},
            {"key": "tax_number", "label": "ZIMRA Tax Number (BP/TIN)", "default": emp["tax_number"] if emp else ""},
            {"key": "is_nssa_exempt", "label": "NSSA Exempt?", "type": "combobox",
             "options": ["No", "Yes"],
             "default": "Yes" if (emp and emp["is_nssa_exempt"]) else "No"},
            {"key": "is_elderly_or_disabled", "label": "Elderly/Blind/Disabled Tax Credit?", "type": "combobox",
             "options": ["No", "Yes"],
             "default": "Yes" if (emp and emp["is_elderly_or_disabled"]) else "No"},
            {"key": "notes", "label": "Notes", "type": "textarea", "default": emp["notes"] if emp else ""},
        ]

    def _new_employee(self):
        fields = self._employee_fields()

        def submit(values):
            if not values["first_name"] or not values["last_name"]:
                raise ValueError("First name and surname are required.")
            if not values.get("basic_salary"):
                raise ValueError("Basic salary is required.")
            values["basic_salary"] = parse_money(values["basic_salary"])
            values["is_nssa_exempt"] = values.get("is_nssa_exempt") == "Yes"
            values["is_elderly_or_disabled"] = values.get("is_elderly_or_disabled") == "Yes"
            payroll_model.create_employee(self.conn, values.pop("first_name"), values.pop("last_name"),
                                           values.pop("basic_salary"), user_id=Session.current_user["id"],
                                           **values)
            self._refresh_employees()
            info("Employee added.")

        FormDialog(self, "New Employee", fields, submit)

    def _edit_employee(self):
        row = self.emp_table.selected_row()
        if not row:
            error("Select an employee first.")
            return
        emp = payroll_model.get_employee(self.conn, int(row["id"]))
        fields = self._employee_fields(emp)

        def submit(values):
            values["basic_salary"] = parse_money(values["basic_salary"])
            values["is_nssa_exempt"] = values.get("is_nssa_exempt") == "Yes"
            values["is_elderly_or_disabled"] = values.get("is_elderly_or_disabled") == "Yes"
            payroll_model.update_employee(self.conn, emp["id"], **values)
            self._refresh_employees()
            info("Employee updated.")

        FormDialog(self, f"Edit {emp['first_name']} {emp['last_name']}", fields, submit)

    def _terminate_employee(self):
        row = self.emp_table.selected_row()
        if not row:
            error("Select an employee first.")
            return
        if not confirm(f"Terminate {row['name']}? They will be excluded from future payroll runs."):
            return
        payroll_model.terminate_employee(self.conn, int(row["id"]))
        self._refresh_employees()
        info("Employee terminated.")

    def _add_earning_or_deduction(self):
        employees = payroll_model.list_employees(self.conn, active_only=True)
        if not employees:
            error("Add an employee first.")
            return
        lookup = {f"{e['employee_no']} - {e['first_name']} {e['last_name']}": e["id"] for e in employees}
        fields = [
            {"key": "employee", "label": "Employee*", "type": "combobox", "options": list(lookup.keys())},
            {"key": "line_type", "label": "Type*", "type": "combobox", "options": ["Earning (Allowance)", "Deduction"]},
            {"key": "label", "label": "Description*"},
            {"key": "amount", "label": "Amount*", "type": "money"},
            {"key": "taxable", "label": "Taxable? (earnings only)", "type": "combobox", "options": ["Yes", "No"], "default": "Yes"},
            {"key": "nssa_applicable", "label": "Counts toward NSSA? (earnings only)", "type": "combobox",
             "options": ["No", "Yes"], "default": "No"},
            {"key": "pre_tax", "label": "Pre-tax? (deductions only, e.g. approved pension)", "type": "combobox",
             "options": ["No", "Yes"], "default": "No"},
        ]

        def submit(values):
            if not values.get("label") or not values.get("amount"):
                raise ValueError("Description and amount are required.")
            employee_id = lookup[values["employee"]]
            amount = parse_money(values["amount"])
            if values["line_type"].startswith("Earning"):
                payroll_model.add_earning(self.conn, employee_id, values["label"], amount,
                                           taxable=values.get("taxable") == "Yes",
                                           nssa_applicable=values.get("nssa_applicable") == "Yes")
            else:
                payroll_model.add_deduction(self.conn, employee_id, values["label"], amount,
                                             pre_tax=values.get("pre_tax") == "Yes")
            info("Saved. It will apply from the next payroll run onwards.")

        FormDialog(self, "Add Recurring Allowance / Deduction", fields, submit)

    # ------------------------------------------------------------------
    # TAB 2: PAYROLL RUN
    # ------------------------------------------------------------------
    def _build_payroll_run(self, tab):
        bar = ctk.CTkFrame(tab, fg_color="transparent")
        bar.pack(fill="x", padx=20, pady=(20, 6))
        ctk.CTkButton(bar, text="+ New Pay Period", command=self._new_period).pack(side="left")
        ctk.CTkButton(bar, text="Generate Payslips", command=self._generate_payslips).pack(side="left", padx=6)
        ctk.CTkButton(bar, text="View Payslips", command=self._view_payslips).pack(side="left", padx=6)
        ctk.CTkButton(bar, text="Post to Ledger", fg_color="#27AE60",
                      command=self._post_period).pack(side="left", padx=6)
        ctk.CTkButton(bar, text="Record Salary Payment", command=self._pay_period).pack(side="left", padx=6)
        ctk.CTkButton(bar, text="Remit Statutory Amount", command=self._remit_statutory).pack(side="left", padx=6)

        self.period_table = DataTable(tab, columns=[
            ("period_label", "Period"), ("period_start", "Start"), ("period_end", "End"),
            ("pay_date", "Pay Date"), ("status", "Status"),
        ])
        self.period_table.pack(fill="both", expand=True, padx=20, pady=(0, 20))
        self._refresh_periods()

    def _refresh_periods(self):
        rows = payroll_model.list_payroll_periods(self.conn)
        self.period_table.set_rows([{
            "id": p["id"], "period_label": p["period_label"], "period_start": p["period_start"],
            "period_end": p["period_end"], "pay_date": p["pay_date"], "status": p["status"],
        } for p in rows])

    def _selected_period(self):
        row = self.period_table.selected_row()
        if not row:
            error("Select a pay period first.")
            return None
        return payroll_model.get_payroll_period(self.conn, int(row["id"]))

    def _new_period(self):
        today = date.today().isoformat()
        fields = [
            {"key": "period_label", "label": "Period Label* (e.g. July 2026)"},
            {"key": "period_start", "label": "Period Start*", "type": "date", "default": today},
            {"key": "period_end", "label": "Period End*", "type": "date", "default": today},
            {"key": "pay_date", "label": "Pay Date*", "type": "date", "default": today},
        ]

        def submit(values):
            if not values.get("period_label"):
                raise ValueError("Period label is required.")
            payroll_model.create_payroll_period(
                self.conn, values["period_label"], values["period_start"], values["period_end"],
                values["pay_date"], user_id=Session.current_user["id"],
            )
            self._refresh_periods()
            info("Pay period created. Generate payslips next.")

        FormDialog(self, "New Pay Period", fields, submit)

    def _generate_payslips(self):
        period = self._selected_period()
        if not period:
            return
        if not confirm(f"Generate payslips for every active employee for '{period['period_label']}'? "
                        f"This replaces any payslips already generated for this period."):
            return
        try:
            summary = payroll_model.generate_payslips(self.conn, period["id"], user_id=Session.current_user["id"])
        except ValueError as e:
            error(str(e))
            return
        self._refresh_periods()
        info(f"Generated {summary['headcount']} payslip(s).\n"
             f"Gross pay: {money(summary['gross_pay'])}   Net pay: {money(summary['net_pay'])}\n"
             f"PAYE: {money(summary['paye'])}   AIDS Levy: {money(summary['aids_levy'])}\n"
             f"NSSA (Employee+Employer): {money(summary['nssa_employee'] + summary['nssa_employer'])}\n"
             f"ZIMDEF (Employer): {money(summary['zimdef_employer'])}")

    def _view_payslips(self):
        period = self._selected_period()
        if not period:
            return
        payslips = payroll_model.list_payslips(self.conn, period["id"])
        if not payslips:
            error("No payslips generated for this period yet.")
            return

        win = ctk.CTkToplevel(self)
        win.title(f"Payslips - {period['period_label']}")
        win.geometry("1000x560")
        win.transient(self.winfo_toplevel())
        win.lift()
        win.focus_force()
        win.after(50, win.lift)

        table = DataTable(win, columns=[
            ("employee_no", "Emp #"), ("name", "Name"), ("basic_salary", "Basic"),
            ("gross_pay", "Gross"), ("paye", "PAYE"), ("aids_levy", "AIDS Levy"),
            ("nssa_employee", "NSSA (Emp)"), ("other_deductions", "Other Ded."),
            ("net_pay", "Net Pay"),
        ])
        table.pack(fill="both", expand=True, padx=15, pady=(15, 6))
        # keep the raw payslip rows (with employee_id etc.) keyed by employee_no,
        # since the displayed row only has formatted/renamed display columns
        payslip_by_emp_no = {p["employee_no"]: p for p in payslips}
        table.set_rows([{
            "employee_no": p["employee_no"], "name": f"{p['first_name']} {p['last_name']}",
            "basic_salary": money(p["basic_salary"]), "gross_pay": money(p["gross_pay"]),
            "paye": money(p["paye"]), "aids_levy": money(p["aids_levy"]),
            "nssa_employee": money(p["nssa_employee"]), "other_deductions": money(p["other_deductions"]),
            "net_pay": money(p["net_pay"]),
        } for p in payslips])

        def open_selected(_event=None):
            row = table.selected_row()
            if not row:
                return
            payslip = payslip_by_emp_no.get(row["employee_no"])
            if payslip:
                payslip_document.open_payslip_window(win, self.conn, payslip, period)

        table.tree.bind("<Double-1>", open_selected)

        bottom = ctk.CTkFrame(win, fg_color="transparent")
        bottom.pack(fill="x", padx=15, pady=(0, 15))
        ctk.CTkButton(bottom, text="View Payslip", fg_color=BLUE_ACCENT, hover_color=BLUE_HOVER,
                      command=open_selected).pack(side="right")

        def view_leave():
            row = table.selected_row()
            if not row:
                error("Select a payslip first.")
                return
            payslip = payslip_by_emp_no.get(row["employee_no"])
            if not payslip:
                return
            leave_rows = leave_model.get_payslip_leave_summary(self.conn, payslip["id"])
            leave_win = ctk.CTkToplevel(win)
            leave_win.title(f"Leave - {row['name']} ({period['period_label']})")
            leave_win.geometry("560x300")
            leave_win.transient(win)
            leave_win.lift()
            leave_win.focus_force()
            leave_win.after(50, leave_win.lift)
            leave_table = DataTable(leave_win, columns=[
                ("leave_type_name", "Leave Type"), ("opening_balance", "Opening"),
                ("accrued", "Accrued"), ("taken", "Taken"), ("closing_balance", "Closing"),
            ])
            leave_table.pack(fill="both", expand=True, padx=15, pady=15)
            leave_table.set_rows([{
                "leave_type_name": r["leave_type_name"], "opening_balance": r["opening_balance"],
                "accrued": r["accrued"], "taken": r["taken"], "closing_balance": r["closing_balance"],
            } for r in leave_rows])

        ctk.CTkButton(bottom, text="View Leave", command=view_leave).pack(side="right", padx=(0, 8))

    def _post_period(self):
        period = self._selected_period()
        if not period:
            return
        if not confirm(f"Post '{period['period_label']}' payroll to the General Ledger? "
                        f"This can't be undone from here - reverse it via a manual journal if needed."):
            return
        try:
            payroll_model.post_payroll_to_gl(self.conn, period["id"], user_id=Session.current_user["id"])
        except ValueError as e:
            error(str(e))
            return
        self._refresh_periods()
        info("Payroll posted to the General Ledger.")

    def _pay_period(self):
        period = self._selected_period()
        if not period:
            return
        fields = [
            {"key": "payment_date", "label": "Payment Date*", "type": "date", "default": date.today().isoformat()},
            {"key": "reference", "label": "Reference (batch/EFT ref)"},
        ]

        def submit(values):
            try:
                payroll_model.pay_net_salaries(
                    self.conn, period["id"], payment_date=values["payment_date"] or None,
                    reference=values.get("reference"), user_id=Session.current_user["id"],
                )
            except ValueError as e:
                raise ValueError(str(e))
            self._refresh_periods()
            info("Net salaries payment recorded.")

        FormDialog(self, f"Record Salary Payment - {period['period_label']}", fields, submit)

    def _remit_statutory(self):
        period = self._selected_period()
        if not period:
            return
        summary = payroll_model.payroll_summary(self.conn, period["id"])
        options = {
            f"PAYE - {money(summary['paye'])}": (payroll_model.ACC_PAYE_PAYABLE, summary["paye"]),
            f"AIDS Levy - {money(summary['aids_levy'])}": (payroll_model.ACC_AIDS_LEVY_PAYABLE, summary["aids_levy"]),
            f"NSSA - {money(summary['nssa_employee'] + summary['nssa_employer'])}":
                (payroll_model.ACC_NSSA_PAYABLE, summary["nssa_employee"] + summary["nssa_employer"]),
            f"ZIMDEF - {money(summary['zimdef_employer'])}":
                (payroll_model.ACC_ZIMDEF_PAYABLE, summary["zimdef_employer"]),
        }
        fields = [
            {"key": "which", "label": "Remit*", "type": "combobox", "options": list(options.keys())},
            {"key": "remit_date", "label": "Date*", "type": "date", "default": date.today().isoformat()},
            {"key": "reference", "label": "Reference (bank ref/receipt no.)"},
        ]

        def submit(values):
            account_code, amount = options[values["which"]]
            if not amount:
                raise ValueError("Nothing owing for that item on this period.")
            payroll_model.remit_statutory(
                self.conn, account_code, amount, remit_date=values["remit_date"] or None,
                description=f"{values['which'].split(' - ')[0]} remittance - {period['period_label']}",
                reference=values.get("reference"), user_id=Session.current_user["id"],
            )
            info("Remittance recorded.")

        FormDialog(self, f"Remit Statutory Amount - {period['period_label']}", fields, submit)

    # ------------------------------------------------------------------
    # TAB 3: LEAVE
    # ------------------------------------------------------------------
    def _build_leave(self, tab):
        top = ctk.CTkFrame(tab, fg_color="transparent")
        top.pack(fill="x", padx=20, pady=(20, 6))
        ctk.CTkButton(top, text="+ New Leave Type", command=self._new_leave_type).pack(side="left")
        ctk.CTkButton(top, text="Edit Selected Type", command=self._edit_leave_type).pack(side="left", padx=6)

        self.leave_types_table = DataTable(tab, columns=[
            ("name", "Leave Type"), ("accrual_days_per_month", "Accrual (Days/Month)"),
            ("active", "Active"),
        ], height=5)
        self.leave_types_table.pack(fill="x", padx=20, pady=(0, 14))
        self._refresh_leave_types()

        emp_bar = ctk.CTkFrame(tab, fg_color="transparent")
        emp_bar.pack(fill="x", padx=20, pady=(6, 6))
        ctk.CTkLabel(emp_bar, text="Employee:").pack(side="left", padx=(0, 8))
        employees = payroll_model.list_employees(self.conn, active_only=True)
        self._leave_employee_lookup = {
            f"{e['employee_no']} - {e['first_name']} {e['last_name']}": e["id"] for e in employees
        }
        self.leave_employee_combo = ctk.CTkComboBox(
            emp_bar, values=list(self._leave_employee_lookup.keys()), width=260,
            command=lambda _v: self._refresh_leave_balances(),
        )
        self.leave_employee_combo.pack(side="left", padx=(0, 10))
        ctk.CTkButton(emp_bar, text="Set Opening Balance", command=self._set_leave_opening_balance
                      ).pack(side="left", padx=6)
        ctk.CTkButton(emp_bar, text="Record Leave Taken", command=self._record_leave_taken
                      ).pack(side="left", padx=6)
        ctk.CTkButton(emp_bar, text="Refresh", command=self._refresh_leave_balances
                      ).pack(side="left", padx=6)

        self.leave_balance_table = DataTable(tab, columns=[
            ("leave_type", "Leave Type"), ("opening_balance", "Opening"), ("as_of_date", "Opening As Of"),
            ("balance_today", "Balance (Today)"),
        ], height=5)
        self.leave_balance_table.pack(fill="x", padx=20, pady=(0, 14))

        ctk.CTkLabel(tab, text="Leave Taken (Selected Employee)", font=("Segoe UI", 13, "bold")
                     ).pack(anchor="w", padx=20)
        self.leave_taken_table = DataTable(tab, columns=[
            ("leave_type_name", "Leave Type"), ("date_from", "From"), ("date_to", "To"),
            ("days", "Days"), ("notes", "Notes"),
        ])
        self.leave_taken_table.pack(fill="both", expand=True, padx=20, pady=(4, 20))

        if employees:
            self.leave_employee_combo.set(list(self._leave_employee_lookup.keys())[0])
            self._refresh_leave_balances()

    def _refresh_leave_types(self):
        rows = leave_model.list_leave_types(self.conn)
        self.leave_types_table.set_rows([{
            "id": t["id"], "name": t["name"],
            "accrual_days_per_month": t["accrual_days_per_month"],
            "active": "Yes" if t["active"] else "No",
        } for t in rows])

    def _selected_leave_type(self):
        row = self.leave_types_table.selected_row()
        if not row:
            error("Select a leave type first.")
            return None
        return leave_model.get_leave_type(self.conn, int(row["id"]))

    def _new_leave_type(self):
        fields = [
            {"key": "name", "label": "Leave Type Name*"},
            {"key": "accrual_days_per_month", "label": "Accrual (Days/Month, 0 if none)", "default": "0"},
        ]

        def submit(values):
            if not values.get("name"):
                raise ValueError("Leave type name is required.")
            leave_model.create_leave_type(
                self.conn, values["name"], float(values.get("accrual_days_per_month") or 0),
            )
            self._refresh_leave_types()
            info("Leave type added.")

        FormDialog(self, "New Leave Type", fields, submit)

    def _edit_leave_type(self):
        lty = self._selected_leave_type()
        if not lty:
            return
        fields = [
            {"key": "name", "label": "Leave Type Name*", "default": lty["name"]},
            {"key": "accrual_days_per_month", "label": "Accrual (Days/Month, 0 if none)",
             "default": str(lty["accrual_days_per_month"])},
            {"key": "active", "label": "Active?", "type": "combobox", "options": ["Yes", "No"],
             "default": "Yes" if lty["active"] else "No"},
        ]

        def submit(values):
            leave_model.update_leave_type(
                self.conn, lty["id"], name=values.get("name"),
                accrual_days_per_month=float(values.get("accrual_days_per_month") or 0),
                active=values.get("active") == "Yes",
            )
            self._refresh_leave_types()
            info("Leave type updated.")

        FormDialog(self, f"Edit Leave Type - {lty['name']}", fields, submit)

    def _selected_leave_employee_id(self):
        label = self.leave_employee_combo.get()
        emp_id = self._leave_employee_lookup.get(label)
        if not emp_id:
            error("Select an employee first.")
            return None
        return emp_id

    def _refresh_leave_balances(self):
        employee_id = self._selected_leave_employee_id()
        if not employee_id:
            self.leave_balance_table.set_rows([])
            self.leave_taken_table.set_rows([])
            return

        today = date.today().isoformat()
        rows = []
        for lty in leave_model.list_leave_types(self.conn, active_only=True):
            opening_balance, as_of_date = leave_model.get_opening_balance(self.conn, employee_id, lty["id"])
            balance_today = leave_model.leave_balance_as_of(self.conn, employee_id, lty["id"], today)
            rows.append({
                "leave_type": lty["name"], "opening_balance": opening_balance,
                "as_of_date": as_of_date or "-", "balance_today": balance_today,
            })
        self.leave_balance_table.set_rows(rows)

        taken = leave_model.list_leave_taken(self.conn, employee_id)
        self.leave_taken_table.set_rows([{
            "leave_type_name": t["leave_type_name"], "date_from": t["date_from"], "date_to": t["date_to"],
            "days": t["days"], "notes": t["notes"] or "",
        } for t in taken])

    def _set_leave_opening_balance(self):
        employee_id = self._selected_leave_employee_id()
        if not employee_id:
            return
        leave_types = leave_model.list_leave_types(self.conn, active_only=True)
        if not leave_types:
            error("Add a leave type first.")
            return
        type_lookup = {t["name"]: t["id"] for t in leave_types}
        fields = [
            {"key": "leave_type", "label": "Leave Type*", "type": "combobox", "options": list(type_lookup.keys())},
            {"key": "opening_balance", "label": "Opening Balance (Days)*"},
            {"key": "as_of_date", "label": "As Of Date*", "type": "date", "default": date.today().isoformat()},
        ]

        def submit(values):
            if not values.get("opening_balance"):
                raise ValueError("Opening balance is required.")
            leave_model.set_opening_balance(
                self.conn, employee_id, type_lookup[values["leave_type"]],
                float(values["opening_balance"]), values["as_of_date"],
            )
            self._refresh_leave_balances()
            info("Opening balance saved.")

        FormDialog(self, "Set Leave Opening Balance", fields, submit)

    def _record_leave_taken(self):
        employee_id = self._selected_leave_employee_id()
        if not employee_id:
            return
        leave_types = leave_model.list_leave_types(self.conn, active_only=True)
        if not leave_types:
            error("Add a leave type first.")
            return
        type_lookup = {t["name"]: t["id"] for t in leave_types}
        today = date.today().isoformat()
        fields = [
            {"key": "leave_type", "label": "Leave Type*", "type": "combobox", "options": list(type_lookup.keys())},
            {"key": "date_from", "label": "From*", "type": "date", "default": today},
            {"key": "date_to", "label": "To*", "type": "date", "default": today},
            {"key": "days", "label": "Days Taken*"},
            {"key": "notes", "label": "Notes"},
        ]

        def submit(values):
            if not values.get("days"):
                raise ValueError("Days taken is required.")
            leave_model.record_leave_taken(
                self.conn, employee_id, type_lookup[values["leave_type"]],
                values["date_from"], values["date_to"], float(values["days"]),
                notes=values.get("notes"), user_id=Session.current_user["id"],
            )
            self._refresh_leave_balances()
            info("Leave recorded.")

        FormDialog(self, "Record Leave Taken", fields, submit)

    # ------------------------------------------------------------------
    # TAB 4: REPORTS
    # ------------------------------------------------------------------
    def _build_reports(self, tab):
        bar = ctk.CTkFrame(tab, fg_color="transparent")
        bar.pack(fill="x", padx=20, pady=(20, 6))
        ctk.CTkLabel(bar, text="Period:").pack(side="left", padx=(0, 8))
        periods = payroll_model.list_payroll_periods(self.conn)
        self._report_period_lookup = {p["period_label"]: p["id"] for p in periods}
        self.report_period_combo = ctk.CTkComboBox(bar, values=list(self._report_period_lookup.keys()), width=220)
        self.report_period_combo.pack(side="left", padx=(0, 10))
        ctk.CTkButton(bar, text="PAYE Schedule", command=self._show_paye_schedule).pack(side="left", padx=6)
        ctk.CTkButton(bar, text="NSSA P4 Schedule", command=self._show_nssa_schedule).pack(side="left", padx=6)

        self.reports_table = DataTable(tab, columns=[
            ("employee_no", "Emp #"), ("name", "Name"),
            ("col1", "Taxable Inc. / Insurable Earn."), ("col2", "PAYE / NSSA (Employee)"),
            ("col3", "AIDS Levy / NSSA (Employer)"),
        ])
        self.reports_table.pack(fill="both", expand=True, padx=20, pady=(0, 20))

    def _report_period_id(self):
        label = self.report_period_combo.get()
        if label not in self._report_period_lookup:
            error("Select a pay period first.")
            return None
        return self._report_period_lookup[label]

    def _show_paye_schedule(self):
        period_id = self._report_period_id()
        if not period_id:
            return
        rows = payroll_model.paye_remittance_schedule(self.conn, period_id)
        self.reports_table.set_rows([{
            "employee_no": r["employee_no"], "name": f"{r['first_name']} {r['last_name']}",
            "col1": money(r["taxable_income"]), "col2": money(r["paye"]), "col3": money(r["aids_levy"]),
        } for r in rows])

    def _show_nssa_schedule(self):
        period_id = self._report_period_id()
        if not period_id:
            return
        rows = payroll_model.nssa_p4_schedule(self.conn, period_id)
        self.reports_table.set_rows([{
            "employee_no": r["employee_no"], "name": f"{r['first_name']} {r['last_name']}",
            "col1": money(r["nssa_insurable"]), "col2": money(r["nssa_employee"]), "col3": money(r["nssa_employer"]),
        } for r in rows])

    # ------------------------------------------------------------------
    # TAB 5: STATUTORY RATES
    # ------------------------------------------------------------------
    def _build_statutory_rates(self, tab):
        scroll = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=15, pady=15)

        card = ctk.CTkFrame(scroll, fg_color=("gray95", "gray15"), corner_radius=10)
        card.pack(fill="x", padx=10, pady=10, ipadx=20, ipady=20)

        ctk.CTkLabel(
            card, 
            text="Zimbabwe Statutory Rates & Ceilings", 
            font=("Segoe UI", 18, "bold")
        ).pack(anchor="w", pady=(0, 15))

        # Definition of statutory keys, user-friendly labels, and input types (% vs flat amount)
        self.statutory_schema = [
            ("nssa_employee_rate", "NSSA Employee Contribution Rate (%)", "pct"),
            ("nssa_employer_rate", "NSSA Employer Contribution Rate (%)", "pct"),
            ("nssa_ceiling", "NSSA Monthly Insurable Ceiling ($)", "amount"),
            ("zimdef_rate", "ZIMDEF Training Levy Rate (%)", "pct"),
            ("aids_levy_rate", "AIDS Levy Rate (%)", "pct"),
            ("elderly_disabled_credit_annual", "Elderly/Disabled Tax Credit ($/year)", "amount"),
        ]

        self.statutory_entries = {}

        for key, label, val_type in self.statutory_schema:
            row_frame = ctk.CTkFrame(card, fg_color="transparent")
            row_frame.pack(fill="x", pady=6)

            ctk.CTkLabel(
                row_frame, text=label, width=280, anchor="w", font=("Segoe UI", 12)
            ).pack(side="left")

            entry = ctk.CTkEntry(row_frame, width=180)
            entry.pack(side="left", padx=10)
            if val_type == "amount":
                enable_quick_math(entry)
            self.statutory_entries[key] = (entry, val_type)

        btn_bar = ctk.CTkFrame(card, fg_color="transparent")
        btn_bar.pack(fill="x", pady=(20, 0))

        if perm_model.has_permission(self.conn, Session.current_user, "Settings", "edit"):
            ctk.CTkButton(
                btn_bar,
                text="Save Statutory Rates",
                fg_color="#27AE60",
                hover_color="#219653",
                font=("Segoe UI", 13, "bold"),
                height=36,
                command=self._save_statutory_rates
            ).pack(side="left")

        ctk.CTkButton(
            btn_bar,
            text="Refresh / Undo Changes",
            fg_color="gray40",
            height=36,
            command=self._refresh_statutory_rates
        ).pack(side="left", padx=10)

        self._refresh_statutory_rates()

    def _refresh_statutory_rates(self):
        """Load current settings from the database into entry fields."""
        settings_rows = payroll_model.list_settings(self.conn)
        settings_map = {row["key"]: row["value"] for row in settings_rows}

        for key, (entry, val_type) in self.statutory_entries.items():
            raw_val = settings_map.get(key, "0")
            entry.delete(0, "end")
            try:
                if val_type == "pct":
                    # Convert decimal rate to percentage display (e.g., 0.045 -> 4.5)
                    num_val = float(raw_val)
                    entry.insert(0, f"{num_val * 100:.2f}".rstrip('0').rstrip('.'))
                else:
                    # "amount" settings (nssa_ceiling, elderly_disabled_credit_annual)
                    # are stored as integer cents - see payroll.py DEFAULT_SETTINGS.
                    entry.insert(0, money_edit_str(int(float(raw_val))))
            except ValueError:
                entry.insert(0, raw_val)

    def _save_statutory_rates(self):
        """Validate and save user updates to the database."""
        try:
            for key, (entry, val_type) in self.statutory_entries.items():
                val_str = entry.get().strip()
                if not val_str:
                    raise ValueError(f"Value for {key} cannot be empty.")

                if val_type == "pct":
                    num_val = float(val_str)
                    if num_val < 0:
                        raise ValueError("Statutory rates and values cannot be negative.")
                    # Convert user percentage input back to decimal (e.g., 4.5% -> 0.045)
                    db_val = num_val / 100.0
                else:
                    # "amount" settings are stored as integer cents.
                    db_val = parse_money(val_str)
                    if db_val < 0:
                        raise ValueError("Statutory rates and values cannot be negative.")

                payroll_model.set_setting(self.conn, key, db_val)

            info("Statutory rates and ceilings saved successfully.")
            self._refresh_statutory_rates()
        except ValueError as e:
            error(f"Invalid input: {str(e)}")
        except Exception as e:
            error(f"Error saving settings: {str(e)}")

    # ------------------------------------------------------------------
    # TAB 6: PAYE TAX BANDS
    # ------------------------------------------------------------------
    def _build_paye_bands(self, tab):
        bar = ctk.CTkFrame(tab, fg_color="transparent")
        bar.pack(fill="x", padx=20, pady=(20, 6))
        
        ctk.CTkButton(bar, text="+ Add Tax Band", command=self._new_paye_band).pack(side="left")
        ctk.CTkButton(bar, text="Edit Selected", command=self._edit_paye_band).pack(side="left", padx=6)
        ctk.CTkButton(bar, text="Delete Selected", fg_color="#EB5757", hover_color="#C0392B",
                      command=self._delete_paye_band).pack(side="left", padx=6)

        self.paye_table = DataTable(tab, columns=[
            ("currency", "Currency"),
            ("lower_bound", "Lower Bound"),
            ("upper_bound", "Upper Bound"),
            ("rate", "Rate (%)"),
            ("deduct", "Deduction"),
        ])
        self.paye_table.pack(fill="both", expand=True, padx=20, pady=(0, 20))
        self._refresh_paye_bands()

    def _refresh_paye_bands(self):
        # Fetching all currencies to allow for USD, ZWG, etc.
        rows = self.conn.execute("SELECT * FROM payroll_tax_bands ORDER BY currency, lower_bound").fetchall()
        
        self.paye_table.set_rows([{
            "id": r["id"], 
            "currency": r["currency"],
            "lower_bound": money(r["lower_bound"]),
            "upper_bound": money(r["upper_bound"]) if r["upper_bound"] is not None else "And Above",
            "rate": f"{r['rate'] * 100:.2f}%",
            "deduct": money(r["deduct"]),
        } for r in rows])

    def _paye_band_fields(self, band=None):
        return [
            {"key": "currency", "label": "Currency*", "type": "combobox", "options": ["USD", "ZWG"], "default": band["currency"] if band else "USD"},
            {"key": "lower_bound", "label": "Lower Bound*", "default": money_edit_str(band["lower_bound"]) if band else ""},
            {"key": "upper_bound", "label": "Upper Bound (Leave blank for 'And Above')", "default": money_edit_str(band["upper_bound"]) if band and band["upper_bound"] else ""},
            {"key": "rate", "label": "Tax Rate (%)*", "default": str(band["rate"] * 100) if band else ""},
            {"key": "deduct", "label": "Deduction Amount*", "default": money_edit_str(band["deduct"]) if band else ""},
        ]

    def _new_paye_band(self):
        def submit(values):
            try:
                curr = values["currency"]
                lower = parse_money(values["lower_bound"])
                upper = parse_money(values["upper_bound"]) if values["upper_bound"].strip() else None
                rate = float(values["rate"]) / 100.0
                deduct = parse_money(values["deduct"])
                
                self.conn.execute(
                    "INSERT INTO payroll_tax_bands (currency, lower_bound, upper_bound, rate, deduct) VALUES (?, ?, ?, ?, ?)",
                    (curr, lower, upper, rate, deduct)
                )
                self.conn.commit()
                self._refresh_paye_bands()
                info("Tax band added successfully.")
            except ValueError:
                raise ValueError("Please enter valid numbers for bounds, rate, and deduction.")
                
        FormDialog(self, "New PAYE Tax Band", self._paye_band_fields(), submit)
        
    def _edit_paye_band(self):
        row = self.paye_table.selected_row()
        if not row: return error("Select a tax band first.")
        
        # Re-query raw data for editing rather than using formatted string table outputs
        band = self.conn.execute("SELECT * FROM payroll_tax_bands WHERE id = ?", (row["id"],)).fetchone()
        
        def submit(values):
            try:
                curr = values["currency"]
                lower = parse_money(values["lower_bound"])
                upper = parse_money(values["upper_bound"]) if values["upper_bound"].strip() else None
                rate = float(values["rate"]) / 100.0
                deduct = parse_money(values["deduct"])
                
                self.conn.execute(
                    "UPDATE payroll_tax_bands SET currency=?, lower_bound=?, upper_bound=?, rate=?, deduct=? WHERE id=?",
                    (curr, lower, upper, rate, deduct, band["id"])
                )
                self.conn.commit()
                self._refresh_paye_bands()
                info("Tax band updated successfully.")
            except ValueError:
                raise ValueError("Please enter valid numbers for bounds, rate, and deduction.")
                
        FormDialog(self, "Edit PAYE Tax Band", self._paye_band_fields(band), submit)

    def _delete_paye_band(self):
        row = self.paye_table.selected_row()
        if not row: return error("Select a tax band first.")
        if not confirm("Delete this tax band?"): return
        
        self.conn.execute("DELETE FROM payroll_tax_bands WHERE id = ?", (row["id"],))
        self.conn.commit()
        self._refresh_paye_bands()
        info("Tax band deleted.")