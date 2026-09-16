"""
Zimbabwe statutory payroll engine.

Covers the "standard package" every Zimbabwean employer must run through
on every payslip:

  - PAYE (Pay As You Earn) income tax, via ZIMRA's progressive monthly tax
    bands (stored in payroll_tax_bands so they can be updated the moment
    ZIMRA gazettes a new table, without a code change).
  - AIDS Levy: 3% of PAYE payable after credits (Income Tax Act, Thirteenth
    Schedule; ZIMRA "PAYE Explained").
  - NSSA (National Social Security Authority) Pension and Other Benefits
    Scheme: 4.5% employee + 4.5% employer of insurable earnings, capped at
    a monthly ceiling that NSSA gazettes quarterly (currently USD 700 -
    see nssa.org.zw/contributions). Both figures are kept in
    payroll_settings so they can be updated without a code change.
  - ZIMDEF (Zimbabwe Manpower Development Fund) Training Levy: 1% of the
    gross wage bill, employer-only (Manpower Planning & Development Act,
    Chapter 28:02, s.53).
  - An optional elderly/blind/disabled ZIMRA tax credit (USD 900/year),
    flagged per employee.

Sector-specific items this deliberately does NOT hardcode, because they
vary by NEC/industry and are usually negotiated or gazetted separately:
NEC collective bargaining minimum wages, the Workers' Compensation
Insurance Fund (APWCS) premium (2%-11% depending on industry risk class),
and the Standards Development Fund levy. Model these as ordinary
employee_deductions / a manual journal entry if your business needs them.

Every payroll run posts a single balanced journal entry through
accounting.post_journal(), exactly like disbursements/repayments/expenses
elsewhere in this system, so payroll ties out in the trial balance and
financial statements without any special-casing there.
"""
from datetime import date
from .accounting import post_journal, UnbalancedEntryError
from ..database import next_sequence_number
from ..money import round_cents, to_cents
from . import leave as leave_model


# ---------------------------------------------------------------------
# GL account codes this module posts to directly (see chart_of_accounts.py
# PROTECTED_CODES - these must be added there too).
# ---------------------------------------------------------------------
ACC_SALARIES_EXPENSE = "5100"     # Dr - gross pay (Expense)
ACC_NSSA_EXPENSE = "5110"         # Dr - employer's NSSA contribution (Expense)
ACC_ZIMDEF_EXPENSE = "5120"       # Dr - ZIMDEF training levy (Expense)
ACC_PAYE_PAYABLE = "2100"         # Cr - owed to ZIMRA (Liability)
ACC_AIDS_LEVY_PAYABLE = "2160"    # Cr - owed to ZIMRA, remitted with PAYE (Liability)
ACC_NSSA_PAYABLE = "2150"         # Cr - owed to NSSA, employee + employer (Liability)
ACC_ZIMDEF_PAYABLE = "2170"       # Cr - owed to ZIMDEF (Liability)
ACC_NET_SALARIES_PAYABLE = "2180"  # Cr - owed to employees until paid out (Liability)
ACC_CASH = "1000"

# Percentage-rate settings (nssa_employee_rate, nssa_employer_rate, zimdef_rate,
# aids_levy_rate) are plain decimals (0.045 = 4.5%) and untouched by the cents
# migration. nssa_ceiling and elderly_disabled_credit_annual ARE money, so -
# same as every other money value in this app - they're stored here as
# integer cents (e.g. "70000" = $700.00), not dollars, even though this
# table is a generic TEXT key/value store the schema conversion couldn't
# reach automatically.
DEFAULT_SETTINGS = {
    # NSSA POBS: 4.5% employee + 4.5% employer, ceiling gazetted quarterly.
    # Source: nssa.org.zw/contributions (checked mid-2026).
    "nssa_employee_rate": "0.045",
    "nssa_employer_rate": "0.045",
    "nssa_ceiling": "70000",  # $700.00, in cents
    # ZIMDEF Training Levy: 1% of gross wage bill, employer only.
    "zimdef_rate": "0.01",
    # AIDS Levy: 3% of PAYE payable after credits.
    "aids_levy_rate": "0.03",
    # ZIMRA elderly/blind/disabled personal tax credit, USD/year.
    "elderly_disabled_credit_annual": "90000",  # $900.00/year, in cents
}

# ZIMRA "PAY AS YOU EARN (PAYE) FOREIGN CURRENCY TAX TABLES", monthly USD
# bands, effective 1 January 2025 (still the current published table as of
# mid-2026 - zimra.co.zw/domestic-taxes/tax-tables). Tax on taxable monthly
# income = income * rate - deduct.
DEFAULT_PAYE_BANDS_USD = [
    # (lower, upper, rate, deduct)
    (0.00, 100.00, 0.00, 0.00),
    (100.01, 300.00, 0.20, 20.00),
    (300.01, 1000.00, 0.25, 35.00),
    (1000.01, 2000.00, 0.30, 85.00),
    (2000.01, 3000.00, 0.35, 185.00),
    (3000.01, None, 0.40, 335.00),
]


def seed_payroll_defaults(conn):
    """
    Safe to call on every startup - checks if a band exists before inserting,
    so it never overwrites or duplicates a rate.
    """
    for lo, hi, rate, deduct in DEFAULT_PAYE_BANDS_USD:
        # Bands above are authored in dollars for readability; convert to
        # integer cents before storing, since payroll_tax_bands.lower_bound/
        # upper_bound/deduct are money columns (rate is a percentage, left
        # as-is).
        lo_cents = to_cents(lo)
        hi_cents = to_cents(hi) if hi is not None else None
        deduct_cents = to_cents(deduct)
        # Check if this lower bound already exists for the currency
        existing = conn.execute(
            "SELECT id FROM payroll_tax_bands WHERE currency = 'USD' AND lower_bound = ?", 
            (lo_cents,)
        ).fetchone()
        
        if not existing:
            conn.execute(
                "INSERT INTO payroll_tax_bands (currency, lower_bound, upper_bound, rate, deduct) "
                "VALUES ('USD', ?, ?, ?, ?)",
                (lo_cents, hi_cents, rate, deduct_cents),
            )
            
    for key, value in DEFAULT_SETTINGS.items():
        # Check if the setting exists first
        existing_setting = conn.execute(
            "SELECT value FROM payroll_settings WHERE key = ?", 
            (key,)
        ).fetchone()
        
        if not existing_setting:
            conn.execute(
                "INSERT INTO payroll_settings (key, value) VALUES (?, ?)", 
                (key, value)
            )

    # Leave balances/accrual, consolidated into payroll.
    leave_model.seed_default_leave_types(conn)

def get_setting(conn, key: str) -> float:
    """Returns the raw stored value: a plain decimal rate (e.g. 0.045) for
    *_rate keys, or integer cents (as a float, e.g. 70000.0 for $700.00)
    for nssa_ceiling/elderly_disabled_credit_annual - see DEFAULT_SETTINGS."""
    row = conn.execute("SELECT value FROM payroll_settings WHERE key = ?", (key,)).fetchone()
    if row is None:
        raise ValueError(f"Payroll setting '{key}' is not configured.")
    return float(row["value"])


def set_setting(conn, key: str, value):
    conn.execute(
        "INSERT INTO payroll_settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value)),
    )
    conn.commit()


def list_settings(conn):
    return conn.execute("SELECT key, value FROM payroll_settings ORDER BY key").fetchall()


def get_tax_bands(conn, currency="USD"):
    return conn.execute(
        "SELECT * FROM payroll_tax_bands WHERE currency = ? ORDER BY lower_bound", (currency,)
    ).fetchall()


# ---------------------------------------------------------------------
# Statutory calculations
# ---------------------------------------------------------------------

def compute_paye(conn, taxable_monthly_income: float, currency="USD", elderly_or_disabled=False) -> float:
    """Progressive PAYE per the ZIMRA monthly tax table, minus the elderly/
    blind/disabled credit (a flat monthly amount) if applicable. Never
    returns a negative figure - a credit larger than the tax due simply
    zeroes it out (no refund via payroll)."""
    if taxable_monthly_income <= 0:
        return 0.0
    bands = get_tax_bands(conn, currency)
    tax = 0.0
    for b in bands:
        lo, hi = b["lower_bound"], b["upper_bound"]
        if taxable_monthly_income >= lo and (hi is None or taxable_monthly_income <= hi):
            tax = taxable_monthly_income * b["rate"] - b["deduct"]
            break
    tax = max(tax, 0.0)
    if elderly_or_disabled:
        monthly_credit = get_setting(conn, "elderly_disabled_credit_annual") / 12
        tax = max(tax - monthly_credit, 0.0)
    return round_cents(tax)


def compute_aids_levy(conn, paye_after_credits: float) -> float:
    return round_cents(paye_after_credits * get_setting(conn, "aids_levy_rate"))


def compute_nssa(conn, insurable_earnings: float, exempt=False) -> tuple:
    """Returns (employee_contribution, employer_contribution), each capped
    by the gazetted insurable earnings ceiling."""
    if exempt or insurable_earnings <= 0:
        return 0.0, 0.0
    ceiling = get_setting(conn, "nssa_ceiling")
    base = min(insurable_earnings, ceiling)
    employee = round_cents(base * get_setting(conn, "nssa_employee_rate"))
    employer = round_cents(base * get_setting(conn, "nssa_employer_rate"))
    return employee, employer


def compute_zimdef(conn, gross_wage: float) -> float:
    return round_cents(gross_wage * get_setting(conn, "zimdef_rate"))


# ---------------------------------------------------------------------
# Employees
# ---------------------------------------------------------------------

def list_employees(conn, active_only=False):
    q = "SELECT * FROM employees"
    if active_only:
        q += " WHERE active = 1"
    return conn.execute(q + " ORDER BY employee_no").fetchall()


def get_employee(conn, employee_id: int):
    return conn.execute("SELECT * FROM employees WHERE id = ?", (employee_id,)).fetchone()


def create_employee(conn, first_name, last_name, basic_salary, employee_no=None, **kw):
    first_name, last_name = (first_name or "").strip(), (last_name or "").strip()
    if not first_name or not last_name:
        raise ValueError("First name and last name are required.")
    if basic_salary is None or round_cents(basic_salary) < 0:
        raise ValueError("Basic salary must be a non-negative number.")
    employee_no = employee_no or next_sequence_number(conn, "employees", "employee_no", "EMP")

    fields = {
        "employee_no": employee_no, "first_name": first_name, "last_name": last_name,
        "basic_salary": round_cents(basic_salary),
        "national_id": kw.get("national_id"), "date_of_birth": kw.get("date_of_birth"),
        "gender": kw.get("gender"), "job_title": kw.get("job_title"), "department": kw.get("department"),
        "hire_date": kw.get("hire_date") or date.today().isoformat(),
        "employment_type": kw.get("employment_type", "Permanent"),
        "pay_currency": kw.get("pay_currency", "USD"),
        "pay_frequency": kw.get("pay_frequency", "monthly"),
        "bank_name": kw.get("bank_name"), "bank_account_no": kw.get("bank_account_no"),
        "nssa_number": kw.get("nssa_number"), "tax_number": kw.get("tax_number"),
        "is_nssa_exempt": 1 if kw.get("is_nssa_exempt") else 0,
        "is_elderly_or_disabled": 1 if kw.get("is_elderly_or_disabled") else 0,
        "notes": kw.get("notes"), "created_by": kw.get("user_id"),
    }
    cols = ", ".join(fields.keys())
    placeholders = ", ".join("?" for _ in fields)
    cur = conn.execute(f"INSERT INTO employees ({cols}) VALUES ({placeholders})", list(fields.values()))
    conn.commit()
    return cur.lastrowid


def update_employee(conn, employee_id: int, **kw):
    row = get_employee(conn, employee_id)
    if row is None:
        raise ValueError("Employee not found.")
    allowed = ("first_name", "last_name", "national_id", "date_of_birth", "gender", "job_title",
               "department", "employment_type", "pay_currency", "pay_frequency", "basic_salary",
               "bank_name", "bank_account_no", "nssa_number", "tax_number", "is_nssa_exempt",
               "is_elderly_or_disabled", "active", "notes", "termination_date")
    fields, values = [], []
    for key in allowed:
        if key in kw:
            fields.append(f"{key} = ?")
            values.append(kw[key])
    if not fields:
        return
    values.append(employee_id)
    conn.execute(f"UPDATE employees SET {', '.join(fields)} WHERE id = ?", values)
    conn.commit()


def terminate_employee(conn, employee_id: int, termination_date: str = None):
    update_employee(conn, employee_id, active=0,
                     termination_date=termination_date or date.today().isoformat())


# ---------------------------------------------------------------------
# Recurring earnings / deductions
# ---------------------------------------------------------------------

def add_earning(conn, employee_id, label, amount, taxable=True, nssa_applicable=False):
    cur = conn.execute(
        "INSERT INTO employee_earnings (employee_id, label, amount, taxable, nssa_applicable) "
        "VALUES (?,?,?,?,?)",
        (employee_id, label, round_cents(amount), 1 if taxable else 0, 1 if nssa_applicable else 0),
    )
    conn.commit()
    return cur.lastrowid


def add_deduction(conn, employee_id, label, amount, pre_tax=False):
    cur = conn.execute(
        "INSERT INTO employee_deductions (employee_id, label, amount, pre_tax) VALUES (?,?,?,?)",
        (employee_id, label, round_cents(amount), 1 if pre_tax else 0),
    )
    conn.commit()
    return cur.lastrowid


def list_earnings(conn, employee_id, active_only=True):
    q = "SELECT * FROM employee_earnings WHERE employee_id = ?"
    if active_only:
        q += " AND active = 1"
    return conn.execute(q, (employee_id,)).fetchall()


def list_deductions(conn, employee_id, active_only=True):
    q = "SELECT * FROM employee_deductions WHERE employee_id = ?"
    if active_only:
        q += " AND active = 1"
    return conn.execute(q, (employee_id,)).fetchall()


def remove_earning(conn, earning_id):
    conn.execute("UPDATE employee_earnings SET active = 0 WHERE id = ?", (earning_id,))
    conn.commit()


def remove_deduction(conn, deduction_id):
    conn.execute("UPDATE employee_deductions SET active = 0 WHERE id = ?", (deduction_id,))
    conn.commit()


# ---------------------------------------------------------------------
# Payroll periods & payslip generation
# ---------------------------------------------------------------------

def create_payroll_period(conn, period_label, period_start, period_end, pay_date, user_id=None):
    cur = conn.execute(
        "INSERT INTO payroll_periods (period_label, period_start, period_end, pay_date, created_by) "
        "VALUES (?,?,?,?,?)",
        (period_label, period_start, period_end, pay_date, user_id),
    )
    conn.commit()
    return cur.lastrowid


def list_payroll_periods(conn):
    return conn.execute("SELECT * FROM payroll_periods ORDER BY period_start DESC").fetchall()


def get_payroll_period(conn, payroll_period_id):
    return conn.execute("SELECT * FROM payroll_periods WHERE id = ?", (payroll_period_id,)).fetchone()


def _compute_payslip(conn, employee, payroll_period_id=None):
    # Fetch recurring items
    earnings = list(list_earnings(conn, employee["id"]))
    deductions = list(list_deductions(conn, employee["id"]))

    # Merge one-off items for this specific period
    if payroll_period_id:
        earnings.extend(list(list_one_off_earnings(conn, employee["id"], payroll_period_id)))
        deductions.extend(list(list_one_off_deductions(conn, employee["id"], payroll_period_id)))

    # ... rest of the original _compute_payslip logic remains exactly the same ...
    
    lines = [{"line_type": "Earning", "label": "Basic Salary", "amount": employee["basic_salary"]}]
    gross_pay = employee["basic_salary"]
    taxable_earnings = employee["basic_salary"]
    nssa_insurable = employee["basic_salary"]
    for e in earnings:
        lines.append({"line_type": "Earning", "label": e["label"], "amount": e["amount"]})
        gross_pay += e["amount"]
        if e["taxable"]:
            taxable_earnings += e["amount"]
        if e["nssa_applicable"]:
            nssa_insurable += e["amount"]

    nssa_employee, nssa_employer = compute_nssa(
        conn, nssa_insurable, exempt=bool(employee["is_nssa_exempt"])
    )

    pre_tax_total = sum(d["amount"] for d in deductions if d["pre_tax"])
    other_deductions_total = sum(d["amount"] for d in deductions if not d["pre_tax"])
    for d in deductions:
        lines.append({"line_type": "Deduction", "label": d["label"], "amount": d["amount"]})

    taxable_income = max(taxable_earnings - nssa_employee - pre_tax_total, 0.0)
    paye = compute_paye(
        conn, taxable_income, currency=employee["pay_currency"],
        elderly_or_disabled=bool(employee["is_elderly_or_disabled"]),
    )
    aids_levy = compute_aids_levy(conn, paye)
    zimdef_employer = compute_zimdef(conn, gross_pay)

    if nssa_employee:
        lines.append({"line_type": "Deduction", "label": "NSSA (Employee)", "amount": nssa_employee})
    if paye:
        lines.append({"line_type": "Deduction", "label": "PAYE", "amount": paye})
    if aids_levy:
        lines.append({"line_type": "Deduction", "label": "AIDS Levy", "amount": aids_levy})

    net_pay = round_cents(
        gross_pay - paye - aids_levy - nssa_employee - pre_tax_total - other_deductions_total)

    return {
        "employee_id": employee["id"],
        "basic_salary": round_cents(employee["basic_salary"]),
        "gross_pay": round_cents(gross_pay),
        "taxable_income": round_cents(taxable_income),
        "nssa_insurable": round_cents(min(nssa_insurable, get_setting(conn, "nssa_ceiling"))),
        "paye": paye,
        "aids_levy": aids_levy,
        "nssa_employee": nssa_employee,
        "nssa_employer": nssa_employer,
        "zimdef_employer": zimdef_employer,
        "other_deductions": round_cents(pre_tax_total + other_deductions_total),
        "net_pay": net_pay,
        "_lines": lines,
    }


def generate_payslips(conn, payroll_period_id: int, user_id=None):
    """
    Computes and (re)writes a payslip for every active employee for this
    period. Safe to re-run on a Draft period (e.g. after editing an
    employee's salary) - it replaces that employee's payslip rather than
    duplicating it. Refuses to run once the period has already been posted
    to the ledger, since payslips must stay frozen once the GL entry that
    was derived from them exists.
    """
    period = get_payroll_period(conn, payroll_period_id)
    if period is None:
        raise ValueError("Payroll period not found.")
    if period["status"] in ("Posted", "Paid"):
        raise ValueError(
            f"This period is already {period['status']} - it can't be regenerated. "
            f"Reverse the posting first if you need to correct it."
        )

    employees = list_employees(conn, active_only=True)
    if not employees:
        raise ValueError("No active employees to run payroll for.")

    # Leave accrues once per period, no matter how many times payslips get
    # (re)generated for it - accrue_leave_for_period() is idempotent per
    # (employee, leave type, period), so re-running this is safe.
    leave_model.accrue_leave_for_period(conn, payroll_period_id, employees=employees, user_id=user_id)

    for employee in employees:
        existing = conn.execute(
            "SELECT id FROM payslips WHERE payroll_period_id = ? AND employee_id = ?",
            (payroll_period_id, employee["id"]),
        ).fetchone()
        if existing:
            conn.execute("DELETE FROM payslip_lines WHERE payslip_id = ?", (existing["id"],))
            conn.execute("DELETE FROM payslips WHERE id = ?", (existing["id"],))

        # Change this line:
        result = _compute_payslip(conn, employee, payroll_period_id)
        lines = result.pop("_lines")
        cols = ", ".join(["payroll_period_id"] + list(result.keys()))
        placeholders = ", ".join("?" for _ in range(len(result) + 1))
        cur = conn.execute(
            f"INSERT INTO payslips ({cols}) VALUES ({placeholders})",
            [payroll_period_id] + list(result.values()),
        )
        payslip_id = cur.lastrowid
        for line in lines:
            conn.execute(
                "INSERT INTO payslip_lines (payslip_id, line_type, label, amount) VALUES (?,?,?,?)",
                (payslip_id, line["line_type"], line["label"], line["amount"]),
            )
        # Freeze this employee's opening/accrued/taken/closing leave figures
        # against the payslip - informational only, no effect on pay.
        leave_model.save_payslip_leave_summary(conn, payslip_id, employee["id"], payroll_period_id)

    conn.execute("UPDATE payroll_periods SET status = 'Processed' WHERE id = ?", (payroll_period_id,))
    conn.commit()
    return payroll_summary(conn, payroll_period_id)


def list_payslips(conn, payroll_period_id):
    return conn.execute(
        """SELECT p.*, e.employee_no, e.first_name, e.last_name, e.department
           FROM payslips p JOIN employees e ON e.id = p.employee_id
           WHERE p.payroll_period_id = ? ORDER BY e.employee_no""",
        (payroll_period_id,),
    ).fetchall()


def get_payslip_lines(conn, payslip_id):
    return conn.execute(
        "SELECT * FROM payslip_lines WHERE payslip_id = ? ORDER BY id", (payslip_id,)
    ).fetchall()


def payroll_summary(conn, payroll_period_id):
    row = conn.execute(
        """SELECT COUNT(*) as headcount,
                  COALESCE(SUM(gross_pay),0) as gross_pay,
                  COALESCE(SUM(paye),0) as paye,
                  COALESCE(SUM(aids_levy),0) as aids_levy,
                  COALESCE(SUM(nssa_employee),0) as nssa_employee,
                  COALESCE(SUM(nssa_employer),0) as nssa_employer,
                  COALESCE(SUM(zimdef_employer),0) as zimdef_employer,
                  COALESCE(SUM(other_deductions),0) as other_deductions,
                  COALESCE(SUM(net_pay),0) as net_pay
           FROM payslips WHERE payroll_period_id = ?""",
        (payroll_period_id,),
    ).fetchone()
    return dict(row) if row else {}


# ---------------------------------------------------------------------
# GL posting
# ---------------------------------------------------------------------

def post_payroll_to_gl(conn, payroll_period_id: int, user_id=None):
    """
    Posts one balanced journal entry for the whole period - the same
    "one event, one journal entry" pattern as post_disbursement/
    post_repayment/post_expense in accounting.py:

        Dr Salaries and Wages Expense      (total gross pay)
        Dr Employer NSSA Contributions     (employer's NSSA share)
        Dr ZIMDEF Training Levy Expense    (employer's ZIMDEF share)
            Cr PAYE Payable                (total PAYE withheld)
            Cr AIDS Levy Payable           (total AIDS levy withheld)
            Cr NSSA Payable                (employee + employer NSSA, remitted together)
            Cr ZIMDEF Payable
            Cr Net Salaries Payable        (what's actually owed to staff)

    Actually paying staff and remitting the statutory amounts to ZIMRA/
    NSSA/ZIMDEF are separate steps (pay_net_salaries / remit_statutory
    below) - exactly like a loan disbursement being separate from the fee
    that accrued against it.
    """
    period = get_payroll_period(conn, payroll_period_id)
    if period is None:
        raise ValueError("Payroll period not found.")
    if period["status"] != "Processed":
        raise ValueError("Generate payslips for this period before posting to the ledger.")

    summary = payroll_summary(conn, payroll_period_id)
    if summary["headcount"] == 0:
        raise ValueError("No payslips found for this period.")

    lines = [
        {"account": ACC_SALARIES_EXPENSE, "debit": summary["gross_pay"], "credit": 0},
    ]
    if summary["nssa_employer"]:
        lines.append({"account": ACC_NSSA_EXPENSE, "debit": summary["nssa_employer"], "credit": 0})
    if summary["zimdef_employer"]:
        lines.append({"account": ACC_ZIMDEF_EXPENSE, "debit": summary["zimdef_employer"], "credit": 0})
    if summary["paye"]:
        lines.append({"account": ACC_PAYE_PAYABLE, "debit": 0, "credit": summary["paye"]})
    if summary["aids_levy"]:
        lines.append({"account": ACC_AIDS_LEVY_PAYABLE, "debit": 0, "credit": summary["aids_levy"]})
    nssa_total = summary["nssa_employee"] + summary["nssa_employer"]
    if nssa_total:
        lines.append({"account": ACC_NSSA_PAYABLE, "debit": 0, "credit": nssa_total})
    if summary["zimdef_employer"]:
        lines.append({"account": ACC_ZIMDEF_PAYABLE, "debit": 0, "credit": summary["zimdef_employer"]})
    lines.append({"account": ACC_NET_SALARIES_PAYABLE, "debit": 0, "credit": summary["net_pay"]})

    journal_id = post_journal(
        conn,
        entry_date=period["pay_date"],
        description=f"Payroll - {period['period_label']} ({summary['headcount']} employees)",
        lines=lines,
        source_type="payroll",
        source_id=payroll_period_id,
        reference=f"PAY-{payroll_period_id:06d}",
        created_by=user_id,
    )
    conn.execute(
        "UPDATE payroll_periods SET status = 'Posted', journal_entry_id = ? WHERE id = ?",
        (journal_id, payroll_period_id),
    )
    conn.commit()
    return journal_id


def pay_net_salaries(conn, payroll_period_id, payment_date=None, reference=None, user_id=None):
    """Clears Net Salaries Payable once staff have actually been paid
    (e.g. via bank batch/mobile money) - Dr the liability, Cr Cash and Bank."""
    period = get_payroll_period(conn, payroll_period_id)
    if period is None:
        raise ValueError("Payroll period not found.")
    if period["status"] != "Posted":
        raise ValueError("Post this period to the ledger before recording payment.")
    summary = payroll_summary(conn, payroll_period_id)
    journal_id = post_journal(
        conn,
        entry_date=payment_date or date.today().isoformat(),
        description=f"Net salaries paid - {period['period_label']}",
        lines=[
            {"account": ACC_NET_SALARIES_PAYABLE, "debit": summary["net_pay"], "credit": 0},
            {"account": ACC_CASH, "debit": 0, "credit": summary["net_pay"]},
        ],
        source_type="payroll_payment",
        source_id=payroll_period_id,
        reference=reference or f"PAYPMT-{payroll_period_id:06d}",
        created_by=user_id,
    )
    conn.execute("UPDATE payroll_periods SET status = 'Paid' WHERE id = ?", (payroll_period_id,))
    conn.commit()
    return journal_id


def remit_statutory(conn, liability_account_code, amount, remit_date=None, description=None,
                     reference=None, user_id=None):
    """
    Generic remittance to ZIMRA (PAYE/AIDS Levy), NSSA, or ZIMDEF once the
    payment is actually made: Dr the liability (clearing it), Cr Cash.
    Use ACC_PAYE_PAYABLE / ACC_AIDS_LEVY_PAYABLE / ACC_NSSA_PAYABLE /
    ACC_ZIMDEF_PAYABLE as liability_account_code.
    """
    if amount <= 0:
        raise ValueError("Amount must be positive.")
    return post_journal(
        conn,
        entry_date=remit_date or date.today().isoformat(),
        description=description or "Statutory payroll remittance",
        lines=[
            {"account": liability_account_code, "debit": amount, "credit": 0},
            {"account": ACC_CASH, "debit": 0, "credit": amount},
        ],
        source_type="payroll_remittance",
        reference=reference,
        created_by=user_id,
    )


# ---------------------------------------------------------------------
# Statutory return helpers
# ---------------------------------------------------------------------

def paye_remittance_schedule(conn, payroll_period_id):
    """Per-employee PAYE + AIDS Levy detail, for the ZIMRA monthly return."""
    rows = conn.execute(
        """SELECT e.employee_no, e.first_name, e.last_name, e.tax_number,
                  p.taxable_income, p.paye, p.aids_levy
           FROM payslips p JOIN employees e ON e.id = p.employee_id
           WHERE p.payroll_period_id = ? ORDER BY e.employee_no""",
        (payroll_period_id,),
    ).fetchall()
    return rows


def nssa_p4_schedule(conn, payroll_period_id):
    """Per-employee NSSA detail, for the NSSA P4 monthly return."""
    rows = conn.execute(
        """SELECT e.employee_no, e.first_name, e.last_name, e.nssa_number,
                  p.nssa_insurable, p.nssa_employee, p.nssa_employer,
                  (p.nssa_employee + p.nssa_employer) as nssa_total
           FROM payslips p JOIN employees e ON e.id = p.employee_id
           WHERE p.payroll_period_id = ? ORDER BY e.employee_no""",
        (payroll_period_id,),
    ).fetchall()
    return rows

def add_one_off_earning(conn, employee_id, payroll_period_id, label, amount, taxable=True, nssa_applicable=False):
    conn.execute(
        "INSERT INTO one_off_earnings (employee_id, payroll_period_id, label, amount, taxable, nssa_applicable) VALUES (?,?,?,?,?,?)",
        (employee_id, payroll_period_id, label, round_cents(amount), 1 if taxable else 0, 1 if nssa_applicable else 0)
    )
    conn.commit()

def add_one_off_deduction(conn, employee_id, payroll_period_id, label, amount, pre_tax=False):
    conn.execute(
        "INSERT INTO one_off_deductions (employee_id, payroll_period_id, label, amount, pre_tax) VALUES (?,?,?,?,?)",
        (employee_id, payroll_period_id, label, round_cents(amount), 1 if pre_tax else 0)
    )
    conn.commit()

def list_one_off_earnings(conn, employee_id, payroll_period_id):
    return conn.execute(
        "SELECT * FROM one_off_earnings WHERE employee_id = ? AND payroll_period_id = ?", 
        (employee_id, payroll_period_id)
    ).fetchall()

def list_one_off_deductions(conn, employee_id, payroll_period_id):
    return conn.execute(
        "SELECT * FROM one_off_deductions WHERE employee_id = ? AND payroll_period_id = ?", 
        (employee_id, payroll_period_id)
    ).fetchall()
