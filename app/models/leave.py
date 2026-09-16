"""
Leave management, consolidated into payroll.

Covers running leave balances per employee per leave type:

  - Leave types (e.g. Annual Leave, Sick Leave), each with a monthly
    accrual rate you configure (Zimbabwe's Labour Act minimum for annual
    leave is 1.75 days/month = 21 days/year, seeded as the default -
    adjust it, or set it to 0 for leave types that don't accrue monthly).
  - An opening balance per employee per leave type, effective from
    whatever date you carried it forward from (e.g. when you started
    using this system).
  - One accrual entry per employee per leave type per payroll period,
    posted automatically the first time payslips are generated for that
    period (safe to regenerate payslips for the same period - it won't
    double-accrue).
  - A log of leave days actually taken, which can be tied to a specific
    payroll period or entered ad hoc.
  - A frozen opening/accrued/taken/closing snapshot saved against each
    payslip at generation time, so a payslip's leave figures don't drift
    if leave is logged or balances are corrected later.

Nothing here posts to the General Ledger or changes pay - by design (see
generate_payslips in payroll.py), this is informational: leave taken is
shown on the payslip, not deducted from it.
"""
from datetime import date, timedelta


# Zimbabwe Labour Act minimum: 1.75 days/month = 21 days/year for annual
# leave. Sick/compassionate leave have no statutory monthly-accrual
# formula, so they default to 0 (taken can still be logged and shown;
# there's just nothing auto-added to the balance each period) - set a
# rate on them if your policy accrues them monthly too.
DEFAULT_LEAVE_TYPES = [
    ("Annual Leave", 1.75),
    ("Sick Leave", 0.0),
    ("Compassionate Leave", 0.0),
]


def ensure_leave_tables(conn):
    """Safe to call on every startup - CREATE TABLE IF NOT EXISTS throughout."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS leave_types (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            accrual_days_per_month REAL NOT NULL DEFAULT 0,
            active INTEGER NOT NULL DEFAULT 1
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS employee_leave_opening_balances (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL,
            leave_type_id INTEGER NOT NULL,
            opening_balance REAL NOT NULL DEFAULT 0,
            as_of_date TEXT NOT NULL,
            UNIQUE(employee_id, leave_type_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS leave_accruals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL,
            leave_type_id INTEGER NOT NULL,
            payroll_period_id INTEGER,
            accrual_date TEXT NOT NULL,
            amount REAL NOT NULL,
            UNIQUE(employee_id, leave_type_id, payroll_period_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS leave_days_taken (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL,
            leave_type_id INTEGER NOT NULL,
            payroll_period_id INTEGER,
            date_from TEXT NOT NULL,
            date_to TEXT NOT NULL,
            days REAL NOT NULL,
            notes TEXT,
            created_by INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS payslip_leave_summary (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            payslip_id INTEGER NOT NULL,
            leave_type_id INTEGER NOT NULL,
            opening_balance REAL NOT NULL DEFAULT 0,
            accrued REAL NOT NULL DEFAULT 0,
            taken REAL NOT NULL DEFAULT 0,
            closing_balance REAL NOT NULL DEFAULT 0,
            UNIQUE(payslip_id, leave_type_id)
        )
    """)
    conn.commit()


def seed_default_leave_types(conn):
    """Safe to call on every startup - only inserts a type if its name isn't already there."""
    ensure_leave_tables(conn)
    for name, rate in DEFAULT_LEAVE_TYPES:
        existing = conn.execute("SELECT id FROM leave_types WHERE name = ?", (name,)).fetchone()
        if not existing:
            conn.execute(
                "INSERT INTO leave_types (name, accrual_days_per_month) VALUES (?, ?)",
                (name, rate),
            )
    conn.commit()


# ---------------------------------------------------------------------
# Leave types
# ---------------------------------------------------------------------

def list_leave_types(conn, active_only=False):
    q = "SELECT * FROM leave_types"
    if active_only:
        q += " WHERE active = 1"
    return conn.execute(q + " ORDER BY name").fetchall()


def get_leave_type(conn, leave_type_id):
    return conn.execute("SELECT * FROM leave_types WHERE id = ?", (leave_type_id,)).fetchone()


def create_leave_type(conn, name, accrual_days_per_month=0.0):
    name = (name or "").strip()
    if not name:
        raise ValueError("Leave type name is required.")
    cur = conn.execute(
        "INSERT INTO leave_types (name, accrual_days_per_month) VALUES (?, ?)",
        (name, float(accrual_days_per_month or 0)),
    )
    conn.commit()
    return cur.lastrowid


def update_leave_type(conn, leave_type_id, name=None, accrual_days_per_month=None, active=None):
    fields, values = [], []
    if name is not None:
        fields.append("name = ?"); values.append(name.strip())
    if accrual_days_per_month is not None:
        fields.append("accrual_days_per_month = ?"); values.append(float(accrual_days_per_month))
    if active is not None:
        fields.append("active = ?"); values.append(1 if active else 0)
    if not fields:
        return
    values.append(leave_type_id)
    conn.execute(f"UPDATE leave_types SET {', '.join(fields)} WHERE id = ?", values)
    conn.commit()


# ---------------------------------------------------------------------
# Opening balances
# ---------------------------------------------------------------------

def set_opening_balance(conn, employee_id, leave_type_id, opening_balance, as_of_date):
    """One opening balance per employee per leave type - re-saving updates it in place."""
    conn.execute(
        "INSERT INTO employee_leave_opening_balances "
        "(employee_id, leave_type_id, opening_balance, as_of_date) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(employee_id, leave_type_id) DO UPDATE SET "
        "opening_balance = excluded.opening_balance, as_of_date = excluded.as_of_date",
        (employee_id, leave_type_id, float(opening_balance), as_of_date),
    )
    conn.commit()


def get_opening_balance(conn, employee_id, leave_type_id):
    """Returns (opening_balance, as_of_date); (0.0, None) if never set."""
    row = conn.execute(
        "SELECT opening_balance, as_of_date FROM employee_leave_opening_balances "
        "WHERE employee_id = ? AND leave_type_id = ?",
        (employee_id, leave_type_id),
    ).fetchone()
    if row is None:
        return 0.0, None
    return row["opening_balance"], row["as_of_date"]


# ---------------------------------------------------------------------
# Leave taken
# ---------------------------------------------------------------------

def record_leave_taken(conn, employee_id, leave_type_id, date_from, date_to, days,
                        payroll_period_id=None, notes=None, user_id=None):
    if days is None or float(days) <= 0:
        raise ValueError("Days taken must be a positive number.")
    conn.execute(
        "INSERT INTO leave_days_taken (employee_id, leave_type_id, payroll_period_id, "
        "date_from, date_to, days, notes, created_by) VALUES (?,?,?,?,?,?,?,?)",
        (employee_id, leave_type_id, payroll_period_id, date_from, date_to, float(days), notes, user_id),
    )
    conn.commit()


def list_leave_taken(conn, employee_id, leave_type_id=None):
    q = ("SELECT lt.*, lty.name as leave_type_name FROM leave_days_taken lt "
         "JOIN leave_types lty ON lty.id = lt.leave_type_id WHERE lt.employee_id = ?")
    params = [employee_id]
    if leave_type_id:
        q += " AND lt.leave_type_id = ?"
        params.append(leave_type_id)
    q += " ORDER BY lt.date_from DESC"
    return conn.execute(q, params).fetchall()


def delete_leave_taken(conn, leave_taken_id):
    conn.execute("DELETE FROM leave_days_taken WHERE id = ?", (leave_taken_id,))
    conn.commit()


# ---------------------------------------------------------------------
# Accrual - one entry per employee per leave type per payroll period
# ---------------------------------------------------------------------

def accrue_leave_for_period(conn, payroll_period_id, employees=None, user_id=None):
    """
    Posts one leave accrual row per active employee per leave type that has
    a nonzero monthly accrual rate, for this payroll period. Safe to call
    every time payslips are (re)generated for the same period: the UNIQUE
    constraint on (employee, leave type, period) makes a repeat call a
    no-op rather than double-accruing.
    """
    ensure_leave_tables(conn)
    # Local imports to avoid a circular import at module load time -
    # payroll.py imports this module at the top of the file, so importing
    # payroll.py back at *load* time here would deadlock; importing inside
    # the function is fine since by the time this runs, payroll.py has
    # already finished loading.
    from .payroll import get_payroll_period, list_employees

    period = get_payroll_period(conn, payroll_period_id)
    if period is None:
        raise ValueError("Payroll period not found.")

    leave_types = [lt for lt in list_leave_types(conn, active_only=True) if lt["accrual_days_per_month"]]
    if not leave_types:
        return

    if employees is None:
        employees = list_employees(conn, active_only=True)

    for emp in employees:
        for lty in leave_types:
            existing = conn.execute(
                "SELECT id FROM leave_accruals WHERE employee_id = ? AND leave_type_id = ? "
                "AND payroll_period_id = ?",
                (emp["id"], lty["id"], payroll_period_id),
            ).fetchone()
            if existing:
                continue
            conn.execute(
                "INSERT INTO leave_accruals (employee_id, leave_type_id, payroll_period_id, "
                "accrual_date, amount) VALUES (?, ?, ?, ?, ?)",
                (emp["id"], lty["id"], payroll_period_id, period["period_end"], lty["accrual_days_per_month"]),
            )
    conn.commit()


# ---------------------------------------------------------------------
# Balances
# ---------------------------------------------------------------------

def leave_balance_as_of(conn, employee_id, leave_type_id, as_of_date):
    """
    Running balance for one employee/leave type as of a given date:
    opening_balance (anchored at its own as_of_date) plus every accrual
    and minus every day taken strictly after that anchor and on/before
    as_of_date.
    """
    opening_balance, anchor_date = get_opening_balance(conn, employee_id, leave_type_id)
    anchor_date = anchor_date or "0000-01-01"

    accrued = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) as total FROM leave_accruals "
        "WHERE employee_id = ? AND leave_type_id = ? AND accrual_date > ? AND accrual_date <= ?",
        (employee_id, leave_type_id, anchor_date, as_of_date),
    ).fetchone()["total"]

    taken = conn.execute(
        "SELECT COALESCE(SUM(days), 0) as total FROM leave_days_taken "
        "WHERE employee_id = ? AND leave_type_id = ? AND date_from > ? AND date_to <= ?",
        (employee_id, leave_type_id, anchor_date, as_of_date),
    ).fetchone()["total"]

    return round(opening_balance + accrued - taken, 2)


def leave_summary_for_employee_period(conn, employee_id, payroll_period_id):
    """
    Opening/accrued/taken/closing per active leave type for one employee's
    payslip in this period. Opening is the balance as of the day before
    the period starts; accrued/taken are scoped to this specific period
    (rather than "everything up to period end") so re-viewing an older,
    already-processed period's payslip still shows that period's own
    activity, not activity from periods processed after it.
    """
    from .payroll import get_payroll_period

    period = get_payroll_period(conn, payroll_period_id)
    if period is None:
        raise ValueError("Payroll period not found.")

    period_start = date.fromisoformat(period["period_start"])
    day_before = (period_start - timedelta(days=1)).isoformat()

    summary = []
    for lty in list_leave_types(conn, active_only=True):
        opening = leave_balance_as_of(conn, employee_id, lty["id"], day_before)

        accrued = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) as total FROM leave_accruals "
            "WHERE employee_id = ? AND leave_type_id = ? AND payroll_period_id = ?",
            (employee_id, lty["id"], payroll_period_id),
        ).fetchone()["total"]

        taken = conn.execute(
            "SELECT COALESCE(SUM(days), 0) as total FROM leave_days_taken "
            "WHERE employee_id = ? AND leave_type_id = ? AND date_from >= ? AND date_to <= ?",
            (employee_id, lty["id"], period["period_start"], period["period_end"]),
        ).fetchone()["total"]

        closing = round(opening + accrued - taken, 2)
        summary.append({
            "leave_type_id": lty["id"], "leave_type": lty["name"],
            "opening_balance": opening, "accrued": round(accrued, 2),
            "taken": round(taken, 2), "closing_balance": closing,
        })
    return summary


def leave_summary_for_period(conn, payroll_period_id):
    """All active employees' leave summary for a period - for a Leave report tab."""
    from .payroll import list_employees

    rows = []
    for emp in list_employees(conn, active_only=True):
        for s in leave_summary_for_employee_period(conn, emp["id"], payroll_period_id):
            rows.append({
                "employee_id": emp["id"], "employee_no": emp["employee_no"],
                "employee_name": f"{emp['first_name']} {emp['last_name']}",
                **s,
            })
    return rows


# ---------------------------------------------------------------------
# Per-payslip snapshot
# ---------------------------------------------------------------------

def save_payslip_leave_summary(conn, payslip_id, employee_id, payroll_period_id):
    """
    Freezes this employee's leave summary for this period against the
    payslip record, so it stops reflecting later corrections/edits to
    leave data the way a live recalculation would. Called automatically
    from generate_payslips(); safe to re-run (replaces the snapshot).
    """
    summary = leave_summary_for_employee_period(conn, employee_id, payroll_period_id)
    conn.execute("DELETE FROM payslip_leave_summary WHERE payslip_id = ?", (payslip_id,))
    for s in summary:
        conn.execute(
            "INSERT INTO payslip_leave_summary "
            "(payslip_id, leave_type_id, opening_balance, accrued, taken, closing_balance) "
            "VALUES (?,?,?,?,?,?)",
            (payslip_id, s["leave_type_id"], s["opening_balance"], s["accrued"], s["taken"], s["closing_balance"]),
        )
    conn.commit()
    return summary


def get_payslip_leave_summary(conn, payslip_id):
    return conn.execute(
        "SELECT pls.*, lty.name as leave_type_name FROM payslip_leave_summary pls "
        "JOIN leave_types lty ON lty.id = pls.leave_type_id "
        "WHERE pls.payslip_id = ? ORDER BY lty.name",
        (payslip_id,),
    ).fetchall()
