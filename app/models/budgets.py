import sqlite3
import calendar
import re
from datetime import date
from openpyxl import load_workbook
from ..money import to_cents, round_cents

# ---------------------------------------------------------------------
# Constants for Excel Parsing
# ---------------------------------------------------------------------
# Month labels for UI headers
MONTH_LABELS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

_MONTH_TOKEN_RE = re.compile(r"^([a-zA-Z]+)[- ]?(\d{2,4})$")
_MONTH_ABBR = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12
}
_SKIP_LABELS = {"total", "net", "subtotal", "gross profit", "net income"}

# ---------------------------------------------------------------------
# Reconciliation sources
# ---------------------------------------------------------------------
# Each entry is a named, safe (parameterized, no user-supplied SQL) way to
# pull an "actual" total for a date range. This is what used to be baked
# directly into budget_vs_actual as hardcoded label/section string
# matching (e.g. "if 'disbursement' in label"). It's now an explicit
# registry so a line item can be pointed at one of these sources via the
# reserved "Recon Source" column in the budget sheet, instead of relying
# on the wording of its label matching a hidden keyword.
RECON_SOURCES = {
    "disbursements": {
        "description": "All disbursements in the period",
        "query": "SELECT COALESCE(SUM(amount), 0) as total FROM disbursements "
                 "WHERE disbursement_date >= ? AND disbursement_date <= ?",
    },
    "rollover_disbursements": {
        "description": "Disbursements made via rollover",
        "query": "SELECT COALESCE(SUM(amount), 0) as total FROM disbursements "
                 "WHERE method = 'Rollover' AND disbursement_date >= ? AND disbursement_date <= ?",
    },
    "repayments": {
        "description": "Loan repayments received",
        "query": "SELECT COALESCE(SUM(amount), 0) as total FROM repayments "
                 "WHERE payment_date >= ? AND payment_date <= ?",
    },
}

# Reserved column name (case-insensitive, whitespace-trimmed) that, when
# added to the budget sheet, lets a line item pick one of RECON_SOURCES
# by name rather than relying on label/section keyword-guessing.
RECON_SOURCE_COLUMN = "Recon Source"


def _get_extra_value(extra: dict, field_name: str):
    """Case-insensitive, whitespace-trimmed lookup into an item's 'extra' dict."""
    if not extra:
        return None
    target = field_name.strip().lower()
    for k, v in extra.items():
        if (k or "").strip().lower() == target:
            return v
    return None


def _ensure_extras_table(conn):
    """
    Table for any custom columns a user adds beyond the fixed Section/
    Label/Account/12-months layout in the budget editor sheet. Stored as
    simple (line_item_id, field_name) -> field_value pairs so arbitrary
    extra columns don't require schema changes.
    """
    conn.execute("""
        CREATE TABLE IF NOT EXISTS budget_line_item_extras (
            line_item_id INTEGER NOT NULL,
            field_name TEXT NOT NULL,
            field_value TEXT,
            PRIMARY KEY (line_item_id, field_name)
        )
    """)


def _save_extras(conn, line_item_id: int, extra: dict):
    if not extra:
        return
    for field_name, value in extra.items():
        if not field_name:
            continue
        conn.execute(
            "INSERT OR REPLACE INTO budget_line_item_extras (line_item_id, field_name, field_value) VALUES (?, ?, ?)",
            (line_item_id, str(field_name), "" if value is None else str(value))
        )


def _month_bounds(year: int, month: int):
    """Returns the start and end dates (YYYY-MM-DD) for a given month and year."""
    start_date = date(year, month, 1).strftime('%Y-%m-%d')
    last_day = calendar.monthrange(year, month)[1]
    end_date = date(year, month, last_day).strftime('%Y-%m-%d')
    return start_date, end_date

def get_budget(conn, budget_id: int):
    """Retrieves the budget header and its associated line items across the normalized schema."""
    _ensure_extras_table(conn)

    cur = conn.execute("SELECT id, name, year, notes FROM budgets WHERE id = ?", (budget_id,))
    b_row = cur.fetchone()
    if not b_row:
        return None
    
    budget = dict(b_row)
    
    # Fetch line items and join with accounts to get the type and code
    cur = conn.execute('''
        SELECT 
            b.id, b.section, b.label, b.account_id, 
            a.type as account_type, a.code as account_code
        FROM budget_line_items b
        LEFT JOIN accounts a ON b.account_id = a.id
        WHERE b.budget_id = ?
        ORDER BY b.sort_order, b.id
    ''', (budget_id,))
    
    items = []
    extra_columns = []  # ordered, de-duped list of every custom column name in use
    for row in cur.fetchall():
        row_dict = dict(row)
        
        # Fetch the monthly amounts for this specific line item
        m_cur = conn.execute('''
            SELECT month, amount 
            FROM budget_monthly_amounts 
            WHERE line_item_id = ?
        ''', (row_dict["id"],))
        
        # Initialize a 12-month list with zeros (integer cents)
        monthly = [0] * 12
        full_year = 0
        for m_row in m_cur.fetchall():
            m_index = m_row["month"] - 1 # Convert 1-12 to 0-11 index
            if 0 <= m_index < 12:
                monthly[m_index] = int(m_row["amount"])
                full_year += int(m_row["amount"])
                
        row_dict["monthly"] = monthly
        row_dict["full_year"] = full_year

        # Any custom columns added in the sheet beyond Section/Label/
        # Account/12-months.
        extras_cur = conn.execute(
            "SELECT field_name, field_value FROM budget_line_item_extras WHERE line_item_id = ?",
            (row_dict["id"],)
        )
        extra = {}
        for e_row in extras_cur.fetchall():
            extra[e_row["field_name"]] = e_row["field_value"]
            if e_row["field_name"] not in extra_columns:
                extra_columns.append(e_row["field_name"])
        row_dict["extra"] = extra

        items.append(row_dict)
        
    return {"budget": budget, "items": items, "extra_columns": extra_columns}

def _account_actual(conn, account_id: int, account_type: str, d_from: str, d_to: str):
    """Calculates the actual movement for a general ledger account within a date range."""
    cur = conn.execute('''
        SELECT COALESCE(SUM(jl.debit), 0) as dr_total, COALESCE(SUM(jl.credit), 0) as cr_total
        FROM journal_lines jl
        JOIN journal_entries je ON je.id = jl.journal_entry_id
        WHERE jl.account_id = ? AND je.entry_date >= ? AND je.entry_date <= ?
          AND (je.source_type IS NULL OR je.source_type != 'period_close')
    ''', (account_id, d_from, d_to))
    row = cur.fetchone()
    
    dr_total = int(row["dr_total"])
    cr_total = int(row["cr_total"])

    if account_type and account_type.lower() in ("revenue", "income", "liability", "equity"):
        return cr_total - dr_total
    else:
        return dr_total - cr_total

def create_budget(conn, name: str, year: int, sections: list, notes: str = None, user_id=None) -> int:
    """Inserts a new budget into the database using the normalized schema structure."""
    _ensure_extras_table(conn)

    cur = conn.execute(
        "INSERT INTO budgets (name, year, notes, created_by) VALUES (?, ?, ?, ?)",
        (name, year, notes, user_id)
    )
    budget_id = cur.lastrowid

    sort_order = 0
    for sec in sections:
        sort_order += 1
        l_cur = conn.execute(
            "INSERT INTO budget_line_items (budget_id, section, label, account_id, sort_order) VALUES (?, ?, ?, ?, ?)",
            (budget_id, sec.get("section"), sec.get("label"), sec.get("account_id"), sort_order)
        )
        line_item_id = l_cur.lastrowid
        
        monthly = sec.get("monthly", [0]*12)
        for month_idx, amount in enumerate(monthly):
            actual_month = month_idx + 1
            if amount != 0:  # Only save non-zero values to save space
                conn.execute(
                    "INSERT INTO budget_monthly_amounts (line_item_id, month, amount) VALUES (?, ?, ?)",
                    (line_item_id, actual_month, amount)
                )

        _save_extras(conn, line_item_id, sec.get("extra"))
    return budget_id

# ---------------------------------------------------------------------
# Reconciliation - budget vs actual, month by month
# ---------------------------------------------------------------------

def _classify_section(it):
    """
    Buckets a line item as 'income' or 'expense' for the reconciliation
    summary totals. Prefers the linked GL account's type (most reliable),
    and otherwise falls back to loose keyword matching on the section
    name so free-typed section labels like "Other Income" or "Operating
    Expenses" (not just the exact words "revenue"/"expenditure") still
    roll up into the summary instead of silently being dropped.
    """
    account_type = (it.get("account_type") or "").strip().lower()
    if account_type == "income":
        return "income"
    if account_type == "expense":
        return "expense"

    section_lower = (it.get("section") or "").strip().lower()
    if "income" in section_lower or "revenue" in section_lower:
        return "income"
    if "expense" in section_lower or "expenditure" in section_lower:
        return "expense"
    return None


def period_bounds(year: int, period_type: str, period_value: int):
    """
    Resolves a (period_type, period_value) pair into a concrete date range
    plus the slice of the 12 monthly indices (0-based, end-exclusive) that
    range covers.
      - "monthly":   period_value is the month number (1-12).
      - "quarterly": period_value is the quarter number (1-4).
      - "ytd":       period_value is the "through" month number (1-12);
                     range always starts from January.
    """
    period_type = (period_type or "ytd").strip().lower()

    if period_type == "monthly":
        month = max(1, min(12, int(period_value or 1)))
        d_from, d_to = _month_bounds(year, month)
        return d_from, d_to, month - 1, month, period_type

    if period_type == "quarterly":
        quarter = max(1, min(4, int(period_value or 1)))
        start_month = (quarter - 1) * 3 + 1
        end_month = start_month + 2
        d_from, _ = _month_bounds(year, start_month)
        _, d_to = _month_bounds(year, end_month)
        return d_from, d_to, start_month - 1, end_month, period_type

    # "ytd" (default)
    upto_month = max(1, min(12, int(period_value or 12)))
    d_from, _ = _month_bounds(year, 1)
    _, d_to = _month_bounds(year, upto_month)
    return d_from, d_to, 0, upto_month, "ytd"


def budget_vs_actual(conn, budget_id: int, period_type: str = "ytd", period_value: int = None,
                      upto_month: int = None):
    """
    Compares each line item's budget against a real "actual" total for a
    chosen period. Three ways an item's actual gets resolved, in priority
    order:
      1. Linked to a GL account (account_id set) -> ledger movement.
      2. A "Recon Source" column value naming one of RECON_SOURCES
         (e.g. 'disbursements', 'repayments', 'rollover_disbursements').
      3. Legacy fallback - guesses from label/section wording (kept only
         for budgets created before the Recon Source column existed).

    period_type is one of "monthly", "quarterly", "ytd" (year to date).
    period_value means: the month (1-12) for "monthly", the quarter
    (1-4) for "quarterly", or the "through" month (1-12) for "ytd".

    upto_month is kept as a deprecated alias for the old signature
    (upto_month=N behaved like period_type="ytd", period_value=N).
    """
    data = get_budget(conn, budget_id)
    if data is None:
        raise ValueError("Budget not found.")
    budget, items = data["budget"], data["items"]
    year = budget["year"]

    if upto_month is not None and period_value is None:
        period_type, period_value = "ytd", upto_month

    d_from, d_to, m_start, m_end, period_type = period_bounds(year, period_type, period_value)

    result_items = []
    total_income_budget = total_income_actual = 0
    total_expense_budget = total_expense_actual = 0

    for it in items:
        budgeted_to_date = sum(it["monthly"][m_start:m_end])
        actual_to_date = None

        recon_source_raw = _get_extra_value(it.get("extra"), RECON_SOURCE_COLUMN)
        recon_source = (recon_source_raw or "").strip().lower()
        if recon_source in ("", "(auto)"):
            recon_source = None

        if it.get("account_id"):
            # Standard GL account reconciliation
            actual_to_date = _account_actual(conn, it["account_id"], it.get("account_type"), d_from, d_to)
        elif recon_source:
            # Explicit source chosen via the "Recon Source" column
            source_def = RECON_SOURCES.get(recon_source)
            if source_def:
                row = conn.execute(source_def["query"], (d_from, d_to)).fetchone()
                actual_to_date = int(row["total"])
            # else: unrecognized source name - leave actual_to_date as None
            # rather than guessing, so a typo is visible instead of silently
            # matching the wrong thing.
        else:
            # Legacy fallback for budgets without a Recon Source column yet
            label_lower = (it.get("label") or "").lower()
            section_lower = (it.get("section") or "").lower()

            if "disbursement" in label_lower or "disbursement" in section_lower:
                row = conn.execute(RECON_SOURCES["disbursements"]["query"], (d_from, d_to)).fetchone()
                actual_to_date = int(row["total"])

            elif "collection" in section_lower or "receipt" in label_lower or "repayment" in label_lower:
                if "rollover" in label_lower:
                    row = conn.execute(RECON_SOURCES["rollover_disbursements"]["query"], (d_from, d_to)).fetchone()
                else:
                    row = conn.execute(RECON_SOURCES["repayments"]["query"], (d_from, d_to)).fetchone()
                actual_to_date = int(row["total"])

        bucket = _classify_section(it)

        # Corrected variance logic to handle income vs expenses appropriately
        if actual_to_date is not None:
            if bucket == "expense":
                # For expenses: Under-budget is positive (favorable), Over-budget is negative (adverse)
                variance = budgeted_to_date - actual_to_date
            else:
                # For income: Over-budget is positive (favorable), Under-budget is negative (adverse)
                variance = actual_to_date - budgeted_to_date
        else:
            variance = None
        
        result_items.append({
            "section": it.get("section"), "label": it.get("label"), "account_code": it.get("account_code"),
            "recon_source": recon_source,
            "budgeted_full_year": it.get("full_year"), "budgeted_to_date": budgeted_to_date,
            "actual_to_date": actual_to_date, "variance": variance,
        })

        if bucket == "income":
            total_income_budget += budgeted_to_date
            if actual_to_date is not None:
                total_income_actual += actual_to_date
        elif bucket == "expense":
            total_expense_budget += budgeted_to_date
            if actual_to_date is not None:
                total_expense_actual += actual_to_date

    if period_type == "monthly":
        period_label = f"{MONTH_LABELS[m_start]} {year}"
    elif period_type == "quarterly":
        quarter = m_start // 3 + 1
        period_label = f"Q{quarter} {year} ({MONTH_LABELS[m_start]}-{MONTH_LABELS[m_end - 1]})"
    else:
        period_label = f"Year to Date {year} (Jan-{MONTH_LABELS[m_end - 1]})"

    return {
        "budget": budget, "period_type": period_type, "period_label": period_label,
        "date_from": d_from, "date_to": d_to, "items": result_items,
        "total_income_budget": total_income_budget,
        "total_income_actual": total_income_actual,
        "total_expense_budget": total_expense_budget,
        "total_expense_actual": total_expense_actual,
        "net_budgeted": total_income_budget - total_expense_budget,
        "net_actual": total_income_actual - total_expense_actual,
    }

def _line_item_recon_kind(it):
    """
    Classifies a budget line item as 'disbursements' or 'collections', using
    the same priority order budget_vs_actual() uses to resolve an item's
    "actual" (explicit Recon Source column first, then legacy label/section
    keyword matching) - just without the GL-account-linked case, since
    disbursement/collection line items are portfolio metrics rather than
    GL accounts. Powers the Dashboard trend chart's budget targets, so
    those numbers always agree with what the Budgets reconciliation screen
    would show for the same line items.
    """
    recon_source_raw = _get_extra_value(it.get("extra"), RECON_SOURCE_COLUMN)
    recon_source = (recon_source_raw or "").strip().lower()
    if recon_source in ("", "(auto)"):
        recon_source = None

    if recon_source in ("disbursements", "rollover_disbursements"):
        return "disbursements"
    if recon_source == "repayments":
        return "collections"
    if recon_source:
        # An explicit but unrecognized source name - don't guess further.
        return None

    label_lower = (it.get("label") or "").lower()
    section_lower = (it.get("section") or "").lower()
    if "disbursement" in label_lower or "disbursement" in section_lower:
        return "disbursements"
    if "collection" in section_lower or "receipt" in label_lower or "repayment" in label_lower:
        return "collections"
    return None


def monthly_disbursements_and_collections_budget(conn, year: int):
    """
    Sums every budget line item tagged as 'disbursements' or 'collections'
    (see _line_item_recon_kind) across all budgets for `year` into two
    12-length month arrays (index 0 = January). Used to draw budget-target
    markers on the Dashboard's Disbursements vs Collections trend chart.
    Returns ([disbursements_by_month], [collections_by_month]); both are
    all-zero if there's no budget for that year yet.
    """
    disb = [0] * 12
    coll = [0] * 12

    budget_ids = [r["id"] for r in conn.execute(
        "SELECT id FROM budgets WHERE year = ?", (year,)
    ).fetchall()]

    for budget_id in budget_ids:
        data = get_budget(conn, budget_id)
        if not data:
            continue
        for it in data["items"]:
            kind = _line_item_recon_kind(it)
            if kind == "disbursements":
                for i in range(12):
                    disb[i] += it["monthly"][i]
            elif kind == "collections":
                for i in range(12):
                    coll[i] += it["monthly"][i]

    return disb, coll


# ---------------------------------------------------------------------
# Excel import
# ---------------------------------------------------------------------

def _parse_amount(cell) -> int:
    """Parses one Excel cell as a dollar amount and returns integer cents.
    This is the boundary where the spreadsheet's float dollars become the
    cents this module (and the DB) works in everywhere else."""
    if cell is None:
        return 0
    if isinstance(cell, (int, float)):
        return to_cents(cell)
    if isinstance(cell, str):
        s = cell.strip().replace(",", "").replace("$", "")
        if not s or s == "-":
            return 0
        try:
            return to_cents(s)
        except ValueError:
            return 0
    return 0

def _match_account_by_label(conn, label):
    """
    Best-effort auto-link: if a row's label exactly matches (case-
    insensitively) a Chart of Accounts account name, link it so the line
    item can be reconciled against real ledger activity. Unmatched labels
    (portfolio metrics like 'Disbursements' that aren't GL accounts) stay
    informational-only - budgeted and displayed, with no actual/variance.
    """
    row = conn.execute("SELECT id FROM accounts WHERE LOWER(name) = LOWER(?)", (label,)).fetchone()
    return row["id"] if row else None

def parse_budget_excel(conn, filepath):
    """
    Parses a forecast spreadsheet shaped like: a header row somewhere near
    the top containing month tokens ('Jan-26', 'Feb-26', ... - any of
    'Jan'/'January'/'Jan-2026' etc. work), then one row per line item
    below it.
    """
    # The try/except block is removed, we just load the workbook directly
    wb = load_workbook(filepath, data_only=True)
    ws = wb.active

    header_row_idx = None
    month_cols = {}
    year = None
        
    for r in range(1, min(ws.max_row, 15) + 1):
        found = {}
        row_year = None
        for c in range(1, ws.max_column + 1):
            val = ws.cell(row=r, column=c).value
            if isinstance(val, str):
                m = _MONTH_TOKEN_RE.match(val.strip())
                if m:
                    abbr = m.group(1).lower()[:3]
                    if abbr in _MONTH_ABBR:
                        found[_MONTH_ABBR[abbr]] = c
                        yy = m.group(2)
                        row_year = 2000 + int(yy) if len(yy) == 2 else int(yy)
        if len(found) >= 6:
            header_row_idx = r
            month_cols = found
            year = row_year
            break

    if header_row_idx is None:
        raise ValueError(
            "Couldn't find a row of month headers (e.g. 'Jan-26' ... 'Dec-26') in this file."
        )
    if year is None:
        year = date.today().year

    sections = []
    current_section = None
    
    for r in range(header_row_idx + 1, ws.max_row + 1):
        label_cell = ws.cell(row=r, column=1).value
        label = str(label_cell).strip() if label_cell not in (None, "") else ""
        if not label:
            continue

        monthly = [
            _parse_amount(ws.cell(row=r, column=month_cols[m]).value) if m in month_cols else 0
            for m in range(1, 13)
        ]

        if all(v == 0 for v in monthly):
            # A label with no monthly figures at all is a section heading, not a budget line.
            current_section = label
            continue

        if label.lower() in _SKIP_LABELS or label.lower().startswith("tithe"):
            continue

        sections.append({
            "section": current_section or "General",
            "label": label,
            "account_id": _match_account_by_label(conn, label),
            "monthly": monthly,
        })

    if not sections:
        raise ValueError("No budget line items found under the month header row.")

    return year, sections

def import_budget_from_excel(conn, filepath, name: str, year: int = None, notes: str = None, user_id=None) -> int:
    detected_year, sections = parse_budget_excel(conn, filepath)
    
    return create_budget(
        conn, 
        name=name, 
        year=year or detected_year, 
        sections=sections,
        notes=notes, 
        user_id=user_id
    )

def list_budgets(conn):
    """
    Returns a list of all budgets with their total income and expense amounts.
    """
    budgets = []
    rows = conn.execute("""
        SELECT id, name, year, notes, created_by, created_at
        FROM budgets
        ORDER BY year DESC, name
    """).fetchall()
    
    for budget in rows:
        # Calculate total budgeted income and expenses for this budget
        total_income = 0
        total_expense = 0
        
        # Get all line items for this budget
        items = conn.execute("""
            SELECT id, section, account_id
            FROM budget_line_items
            WHERE budget_id = ?
        """, (budget["id"],)).fetchall()
        
        for item in items:
            # Sum all monthly amounts for this line item
            monthly_cur = conn.execute("""
                SELECT COALESCE(SUM(amount), 0) as total
                FROM budget_monthly_amounts
                WHERE line_item_id = ?
            """, (item["id"],))
            total = monthly_cur.fetchone()["total"]
            
            # Determine if this is income or expense based on section or account type
            section = item["section"] or ""
            section_lower = section.lower()
            
            if section_lower in ("revenue", "other income", "income"):
                total_income += total
            elif section_lower in ("expenditure", "expense", "expenses"):
                total_expense += total
            else:
                # If section is not specified, try to determine from account type
                if item["account_id"]:
                    acct = conn.execute("""
                        SELECT type FROM accounts WHERE id = ?
                    """, (item["account_id"],)).fetchone()
                    if acct:
                        acct_type = acct["type"].lower()
                        if acct_type in ("income", "revenue"):
                            total_income += total
                        elif acct_type in ("expense", "expenditure"):
                            total_expense += total
        
        budgets.append({
            "id": budget["id"],
            "name": budget["name"],
            "year": budget["year"],
            "notes": budget["notes"],
            "total_income_budget": total_income,
            "total_expense_budget": total_expense,
        })
    
    return budgets

def update_budget(conn, budget_id: int, name: str, year: int, sections: list, notes: str = None):
    """Updates an existing budget."""
    _ensure_extras_table(conn)

    # Update budget header
    conn.execute(
        "UPDATE budgets SET name = ?, year = ?, notes = ? WHERE id = ?",
        (name, year, notes, budget_id)
    )

    # Clean up extras belonging to the line items about to be deleted, since
    # they aren't covered by any FK cascade on budget_line_items.
    conn.execute(
        "DELETE FROM budget_line_item_extras WHERE line_item_id IN "
        "(SELECT id FROM budget_line_items WHERE budget_id = ?)",
        (budget_id,)
    )

    # Delete existing line items and their monthly amounts (cascade will handle)
    conn.execute("DELETE FROM budget_line_items WHERE budget_id = ?", (budget_id,))
    
    # Re-insert line items
    sort_order = 0
    for sec in sections:
        sort_order += 1
        l_cur = conn.execute(
            "INSERT INTO budget_line_items (budget_id, section, label, account_id, sort_order) VALUES (?, ?, ?, ?, ?)",
            (budget_id, sec.get("section"), sec.get("label"), sec.get("account_id"), sort_order)
        )
        line_item_id = l_cur.lastrowid
        
        monthly = sec.get("monthly", [0] * 12)
        for month_idx, amount in enumerate(monthly):
            actual_month = month_idx + 1
            if amount != 0:
                conn.execute(
                    "INSERT INTO budget_monthly_amounts (line_item_id, month, amount) VALUES (?, ?, ?)",
                    (line_item_id, actual_month, amount)
                )

        _save_extras(conn, line_item_id, sec.get("extra"))
    conn.commit()