import re
import sqlite3
import os
import datetime
from . import config
from .auth import hash_password


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # Performance tuning for a single-machine desktop app:
    # - WAL: readers no longer block writers (and vice versa), and WAL
    #   commits are cheaper than the default rollback-journal commits.
    # - synchronous=NORMAL is the recommended pairing with WAL: still safe
    #   against app/OS crashes, just not fsync'd on every single commit.
    # - Bigger page cache and in-memory temp store cut disk I/O on the
    #   larger report/listing queries (repayment schedules, ledgers, etc).
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA cache_size = -20000")
    conn.execute("PRAGMA temp_store = MEMORY")
    return conn


def _seed_accounts(conn):
    accounts = [
        ("1000", "Cash and Bank", "Asset", 1),
        ("1100", "Loans Receivable - Principal", "Asset", 1),
        ("1150", "Interest Receivable", "Asset", 1),
        ("2000", "Accounts Payable", "Liability", 0),
        ("2050", "Client Credit Balances / Unapplied Payments", "Liability", 1),
        ("3000", "Owner's Capital", "Equity", 0),
        ("3100", "Retained Earnings", "Equity", 0),
        ("4000", "Interest Income", "Income", 1),
        ("4100", "Admin Fee Income", "Income", 1),
        ("4200", "Penalty Fee Income", "Income", 1),
        ("4300", "Bad Debt Recovery Income", "Income", 1),
        ("4400", "Application Fee Income", "Income", 1),
        ("4500", "Rollover Fee Income", "Income", 1),
        ("5000", "Bad Debts Written Off", "Expense", 1),
        ("5900", "General Operating Expenses", "Expense", 0),
        # Payroll (app/models/payroll.py)
        ("2100", "PAYE Payable", "Liability", 1),
        ("2150", "NSSA Payable", "Liability", 1),
        ("2160", "AIDS Levy Payable", "Liability", 1),
        ("2170", "ZIMDEF Payable", "Liability", 1),
        ("2180", "Net Salaries Payable", "Liability", 1),
        ("5100", "Salaries and Wages Expense", "Expense", 1),
        ("5110", "Employer NSSA Contributions", "Expense", 1),
        ("5120", "ZIMDEF Training Levy Expense", "Expense", 1),
    ]
    for code, name, type_, control in accounts:
        conn.execute(
            "INSERT OR IGNORE INTO accounts (code, name, type, is_control) VALUES (?,?,?,?)",
            (code, name, type_, control),
        )


def _seed_expense_categories(conn):
    categories = [
        "Rent", "Salaries and Wages", "Utilities", "Office Supplies",
        "Transport", "Communication", "Loan Loss Provision", "Marketing",
        "Bank Charges", "Depreciation", "Miscellaneous",
    ]
    for name in categories:
        conn.execute("INSERT OR IGNORE INTO expense_categories (name) VALUES (?)", (name,))


def _seed_locations_from_existing_clients(conn):
    """
    One-time convenience: the first time the locations table is empty (e.g.
    right after upgrading an existing database that predates the Settings
    module), populate it from whatever distinct, non-blank location values
    clients already have on file - so existing data shows up as ready-made
    options in Settings instead of starting from a blank list. No-ops on
    every subsequent startup once the table has at least one row, so it
    never fights with locations the user has since added/renamed/removed.
    """
    existing = conn.execute("SELECT COUNT(*) as c FROM locations").fetchone()["c"]
    if existing > 0:
        return
    rows = conn.execute(
        "SELECT DISTINCT TRIM(location) as loc FROM clients "
        "WHERE location IS NOT NULL AND TRIM(location) != ''"
    ).fetchall()
    for row in rows:
        conn.execute("INSERT OR IGNORE INTO locations (name) VALUES (?)", (row["loc"],))


def _seed_admin_user(conn):
    existing = conn.execute("SELECT id FROM users WHERE username = ?",
                             (config.DEFAULT_ADMIN_USERNAME,)).fetchone()
    if existing is None:
        pwd_hash, salt = hash_password(config.DEFAULT_ADMIN_PASSWORD)
        conn.execute(
            "INSERT INTO users (username, password_hash, salt, full_name, role) "
            "VALUES (?,?,?,?,?)",
            (config.DEFAULT_ADMIN_USERNAME, pwd_hash, salt, "System Administrator", "admin"),
        )


def _seed_loan_product(conn):
    conn.execute(
        "INSERT OR IGNORE INTO loan_products "
        "(name, interest_method, interest_rate, rate_period, admin_fee_pct, penalty_pct, "
        " grace_period_days, repayment_frequency, term_unit_label) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        ("Standard Monthly Loan", "flat", 10.0, "month", 2.0, 5.0, 3, "monthly", "months"),
    )
    conn.execute(
        "INSERT OR IGNORE INTO loan_products "
        "(name, interest_method, interest_rate, rate_period, admin_fee_pct, penalty_pct, "
        " grace_period_days, repayment_frequency, term_unit_label) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        ("Non-Standard Weekly Loan (Flat)", "flat", 15.0, "loan_term", 2.0, 5.0, 2, "weekly", "weeks"),
    )
    conn.execute(
        "INSERT OR IGNORE INTO loan_products "
        "(name, interest_method, interest_rate, rate_period, admin_fee_pct, penalty_pct, "
        " grace_period_days, repayment_frequency, term_unit_label) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        ("Weekly Loan (Interest Over Tenure)", "flat", 20.0, "loan_term", 2.0, 5.0, 2, "weekly", "weeks"),
    )
    conn.execute(
        "INSERT OR IGNORE INTO loan_products "
        "(name, interest_method, interest_rate, rate_period, admin_fee_pct, penalty_pct, "
        " grace_period_days, repayment_frequency, term_unit_label) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        ("Interest-Only Balloon Loan", "interest_only_balloon", 20.0, "month", 2.0, 5.0, 3, "monthly", "months"),
    )


def _repair_payslips_dangling_fk(conn):
    """
    Rebuilds the payslips table if any of its foreign keys point at a table
    that no longer exists (e.g. "employees_old" - a name left behind from
    an old rename of the employees table; SQLite auto-rewrites *other*
    tables' stored FK clauses to follow a rename, but never rewrites them
    back once the temporary name is dropped, so the stale reference sticks
    around permanently until the referencing table itself is rebuilt).
    SQLite can't ALTER a column's REFERENCES target directly, so this
    recreates payslips from scratch against the current schema and copies
    across whatever rows already have both a payroll_period_id and
    employee_id set. Safe to call repeatedly - no-ops once clean.
    """
    exists = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='payslips'"
    ).fetchone()
    if not exists:
        return  # schema.sql will create it fresh with correct FKs

    dangling = False
    for fk in conn.execute("PRAGMA foreign_key_list(payslips)").fetchall():
        target_exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (fk["table"],)
        ).fetchone()
        if not target_exists:
            dangling = True
            break
    if not dangling:
        return

    old_cols = [r["name"] for r in conn.execute("PRAGMA table_info(payslips)").fetchall()]
    desired_cols = [
        "payroll_period_id", "employee_id", "basic_salary", "gross_pay", "taxable_income",
        "nssa_insurable", "paye", "aids_levy", "nssa_employee", "nssa_employer",
        "zimdef_employer", "other_deductions", "net_pay",
    ]
    carry_cols = [c for c in desired_cols if c in old_cols]

    conn.commit()
    fk_was_on = bool(conn.execute("PRAGMA foreign_keys").fetchone()[0])
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.execute("""
            CREATE TABLE payslips_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                payroll_period_id INTEGER NOT NULL REFERENCES payroll_periods(id) ON DELETE CASCADE,
                employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
                basic_salary INTEGER NOT NULL,
                gross_pay INTEGER NOT NULL,
                taxable_income INTEGER NOT NULL,
                nssa_insurable INTEGER NOT NULL,
                paye INTEGER NOT NULL,
                aids_levy INTEGER NOT NULL,
                nssa_employee INTEGER NOT NULL,
                nssa_employer INTEGER NOT NULL,
                zimdef_employer INTEGER NOT NULL,
                other_deductions INTEGER NOT NULL,
                net_pay INTEGER NOT NULL
            )
        """)
        if "payroll_period_id" in carry_cols and "employee_id" in carry_cols:
            col_list = ", ".join(carry_cols)
            # Only rows with both keys set are real payslips - anything else
            # was left over from before the feature worked and was never a
            # valid, usable payslip to begin with.
            conn.execute(
                f"INSERT INTO payslips_new ({col_list}) "
                f"SELECT {col_list} FROM payslips "
                f"WHERE payroll_period_id IS NOT NULL AND employee_id IS NOT NULL"
            )
        conn.execute("DROP TABLE payslips")
        conn.execute("ALTER TABLE payslips_new RENAME TO payslips")
        conn.commit()
    finally:
        conn.execute(f"PRAGMA foreign_keys = {'ON' if fk_was_on else 'OFF'}")


def _migrate_legacy_columns(conn):
    """Adds columns introduced after the first release to any pre-existing database file,
    without touching existing data. Safe to call on every startup."""
    def ensure_column(table, column, ddl):
        cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        if column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")
            return True
        return False

    ensure_column("clients", "location", "location TEXT")
    ensure_column("journal_entries", "location", "location TEXT")
    ensure_column("clients", "average_income", "average_income INTEGER")
    ensure_column("clients", "guarantor", "guarantor TEXT")
    ensure_column("clients", "guarantor_phone", "guarantor_phone TEXT")
    ensure_column("loan_products", "repayment_frequency", "repayment_frequency TEXT NOT NULL DEFAULT 'monthly'")
    ensure_column("loan_products", "term_unit_label", "term_unit_label TEXT NOT NULL DEFAULT 'months'")
    # New-client application fee, priced the same way admin_fee_pct is - a
    # percentage of principal - but only ever auto-applied on the New Loan
    # form when the client has no prior loans at all (see
    # loans.is_new_client()). Existing clients keep whatever application
    # fee is typed in manually; this never changes historical loans.
    ensure_column("loan_products", "application_fee_pct", "application_fee_pct REAL NOT NULL DEFAULT 0")
    ensure_column("loans", "approval_status", "approval_status TEXT NOT NULL DEFAULT 'Pending'")
    ensure_column("loans", "approved_by", "approved_by INTEGER REFERENCES users(id)")
    ensure_column("loans", "approved_at", "approved_at TEXT")
    ensure_column("repayments", "rollover_fee_paid", "rollover_fee_paid INTEGER NOT NULL DEFAULT 0")
    ensure_column("users", "security_question", "security_question TEXT")
    ensure_column("users", "security_answer_hash", "security_answer_hash TEXT")
    ensure_column("users", "security_answer_salt", "security_answer_salt TEXT")

    # Rollovers used to be a single instant create+approve+disburse action, so
    # every existing row already represents a completed rollover. New rows
    # start life as 'Pending' (a request awaiting approval) and only become
    # 'Completed' once approve_rollover() runs - see app/models/rollovers.py.
    ensure_column("rollovers", "status", "status TEXT NOT NULL DEFAULT 'Completed'")
    # The fee amount to charge once the request is approved (previously
    # charged immediately, since approval used to be instant).
    ensure_column("rollovers", "rollover_fee", "rollover_fee INTEGER NOT NULL DEFAULT 0")

    # Payroll: some existing database files have a "payslips" table that
    # predates the finished payroll schema (created by an early build of the
    # feature), so it's missing several columns that schema.sql's
    # CREATE TABLE IF NOT EXISTS never adds retroactively to a table that
    # already exists. Bring any pre-existing payslips/payroll_periods table
    # fully up to date in one pass instead of patching one column at a time.
    payslips_cols = [r["name"] for r in conn.execute("PRAGMA table_info(payslips)").fetchall()]
    if payslips_cols:  # table already existed before this app run
        if "payroll_period_id" not in payslips_cols:
            conn.execute(
                "ALTER TABLE payslips ADD COLUMN payroll_period_id "
                "INTEGER REFERENCES payroll_periods(id)"
            )
            if "period_id" in payslips_cols:
                conn.execute("UPDATE payslips SET payroll_period_id = period_id")
        ensure_column("payslips", "employee_id", "employee_id INTEGER REFERENCES employees(id)")
        ensure_column("payslips", "basic_salary", "basic_salary INTEGER NOT NULL DEFAULT 0")
        ensure_column("payslips", "gross_pay", "gross_pay INTEGER NOT NULL DEFAULT 0")
        ensure_column("payslips", "taxable_income", "taxable_income INTEGER NOT NULL DEFAULT 0")
        ensure_column("payslips", "nssa_insurable", "nssa_insurable INTEGER NOT NULL DEFAULT 0")
        ensure_column("payslips", "paye", "paye INTEGER NOT NULL DEFAULT 0")
        ensure_column("payslips", "aids_levy", "aids_levy INTEGER NOT NULL DEFAULT 0")
        ensure_column("payslips", "nssa_employee", "nssa_employee INTEGER NOT NULL DEFAULT 0")
        ensure_column("payslips", "nssa_employer", "nssa_employer INTEGER NOT NULL DEFAULT 0")
        ensure_column("payslips", "zimdef_employer", "zimdef_employer INTEGER NOT NULL DEFAULT 0")
        ensure_column("payslips", "other_deductions", "other_deductions INTEGER NOT NULL DEFAULT 0")
        ensure_column("payslips", "net_pay", "net_pay INTEGER NOT NULL DEFAULT 0")

    payroll_periods_cols = [r["name"] for r in conn.execute("PRAGMA table_info(payroll_periods)").fetchall()]
    if payroll_periods_cols:  # table already existed before this app run
        ensure_column("payroll_periods", "status", "status TEXT DEFAULT 'Draft'")
        ensure_column("payroll_periods", "journal_entry_id", "journal_entry_id INTEGER")
        ensure_column("payroll_periods", "created_by", "created_by INTEGER")

    rate_period_added = ensure_column("loans", "rate_period", "rate_period TEXT NOT NULL DEFAULT 'month'")
    if rate_period_added:
        # rate_period previously lived only on loan_products and was looked
        # up indirectly at schedule-generation time. Backfill it onto every
        # existing loan from its linked product, so behavior for loans
        # already on disk doesn't silently change now that it's read
        # directly off the loan. Only runs the one time this column is
        # first added - not on every startup, since a product's rate_period
        # may legitimately be edited later without that retroactively
        # altering already-originated loans.
        conn.execute(
            "UPDATE loans SET rate_period = ("
            "  SELECT rate_period FROM loan_products WHERE loan_products.id = loans.product_id"
            ") WHERE product_id IS NOT NULL"
        )


def _migrate_fee_type_constraint(conn):
    """
    Widens fees.fee_type's CHECK constraint to allow 'Application' and 'Rollover'
    (introduced after the original release - 'Application' for application fees
    charged on new loans, 'Rollover' for the fee charged to facilitate rolling
    a loan over into a new one). Previously these had to be posted as 'Other'.
    Safe to call on every startup: does nothing if the constraint already
    allows them, and reclassifies any pre-existing 'Other' fees that were
    actually application fees.
    """
    row = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='fees'").fetchone()
    if row is None:
        return  # fees table doesn't exist yet - schema.sql (run just before this) will create it

    original_sql = row["sql"]
    needed = [t for t in ("Application", "Rollover")
              if not re.search(rf"fee_type.*'{t}'", original_sql, re.IGNORECASE | re.DOTALL)]
    if needed:
        match = re.search(r"CHECK\s*\(\s*fee_type\s+IN\s*\(([^)]*)\)\s*\)", original_sql, re.IGNORECASE)
        if match:
            new_list = match.group(1).rstrip() + "".join(f", '{t}'" for t in needed)
            new_sql = original_sql[:match.start(1)] + new_list + original_sql[match.end(1):]
            new_sql, n_subs = re.subn(
                r'(CREATE TABLE\s+(?:IF NOT EXISTS\s+)?)(["\'`]?)fees\2(?=\s|\()',
                r'\1\2fees_new\2',
                new_sql, count=1, flags=re.IGNORECASE,
            )
            if n_subs == 0:
                raise RuntimeError(
                    "Could not safely rename the 'fees' table during migration - "
                    "the CREATE TABLE statement didn't match the expected pattern. "
                    "Aborting to avoid corrupting the fees table."
                )
            cols = [r["name"] for r in conn.execute("PRAGMA table_info(fees)").fetchall()]
            col_list = ", ".join(cols)
            conn.execute(new_sql)
            conn.execute(f"INSERT INTO fees_new ({col_list}) SELECT {col_list} FROM fees")
            conn.execute("DROP TABLE fees")
            conn.execute("ALTER TABLE fees_new RENAME TO fees")
        # If there's no CHECK constraint at all, both types already work fine as-is.

    conn.execute(
        "UPDATE fees SET fee_type = 'Application' "
        "WHERE fee_type = 'Other' AND description LIKE 'Application fee%'"
    )


def _widen_interest_method_check(conn, table: str, new_value: str):
    """
    Shared helper: widens a table's interest_method CHECK constraint to allow
    an additional value, by rebuilding the table (SQLite can't ALTER a CHECK
    constraint directly). Safe to call repeatedly - does nothing once the
    constraint already allows new_value, or if the table doesn't exist yet.
    """
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    if row is None:
        return

    original_sql = row["sql"]
    if re.search(rf"interest_method.*'{new_value}'", original_sql, re.IGNORECASE | re.DOTALL):
        return  # already migrated

    match = re.search(r"CHECK\s*\(\s*interest_method\s+IN\s*\(([^)]*)\)\s*\)", original_sql, re.IGNORECASE)
    if not match:
        return  # no CHECK constraint on this column - nothing to widen

    new_list = match.group(1).rstrip() + f", '{new_value}'"
    new_sql = original_sql[:match.start(1)] + new_list + original_sql[match.end(1):]
    new_sql, n_subs = re.subn(
        rf'(CREATE TABLE\s+(?:IF NOT EXISTS\s+)?)(["\'`]?){table}\2(?=\s|\()',
        r'\1\2' + table + '_new' + r'\2',
        new_sql, count=1, flags=re.IGNORECASE,
    )
    if n_subs == 0:
        raise RuntimeError(
            f"Could not safely rename the '{table}' table during migration - "
            "the CREATE TABLE statement didn't match the expected pattern. "
            "Aborting to avoid corrupting the table."
        )

    cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    col_list = ", ".join(cols)

    # Other tables (repayment_schedule, repayments, disbursements, fees, etc.)
    # hold live rows referencing loans(id)/loan_products(id). With
    # foreign_keys=ON, SQLite treats DROP TABLE as an implicit delete of every
    # row in it and rejects it if any such child rows exist - even though
    # we're about to recreate the table under the same name with the same
    # ids. Turn enforcement off just for this rebuild, then restore whatever
    # it was before. Must run with no transaction pending, or the pragma is
    # silently ignored - conn.commit() first guarantees that.
    conn.commit()
    fk_was_on = bool(conn.execute("PRAGMA foreign_keys").fetchone()[0])
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.execute(new_sql)
        conn.execute(f"INSERT INTO {table}_new ({col_list}) SELECT {col_list} FROM {table}")
        conn.execute(f"DROP TABLE {table}")
        conn.execute(f"ALTER TABLE {table}_new RENAME TO {table}")
        conn.commit()
    finally:
        conn.execute(f"PRAGMA foreign_keys = {'ON' if fk_was_on else 'OFF'}")


def _repair_dangling_fk_table(conn, table, create_new_sql, required_not_null_cols=()):
    """
    Generic version of _repair_payslips_dangling_fk above, for any table
    whose stored foreign key points at a table that no longer exists (most
    commonly "employees_old" - see the docstring on
    _repair_payslips_dangling_fk for the full explanation of how that stale
    reference gets left behind). `create_new_sql` must CREATE TABLE
    `{table}_new` with the current, correct schema. Rows are carried across
    on whichever columns exist in both the old and new table, restricted to
    those where every column in required_not_null_cols is set. Safe to call
    repeatedly - no-ops once clean or if the table doesn't exist yet.
    """
    exists = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    if not exists:
        return  # schema.sql will create it fresh with correct FKs

    dangling = False
    for fk in conn.execute(f"PRAGMA foreign_key_list({table})").fetchall():
        target_exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (fk["table"],)
        ).fetchone()
        if not target_exists:
            dangling = True
            break
    if not dangling:
        return

    old_cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]

    conn.commit()
    fk_was_on = bool(conn.execute("PRAGMA foreign_keys").fetchone()[0])
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.execute(create_new_sql)
        new_cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({table}_new)").fetchall()]
        carry_cols = [c for c in new_cols if c in old_cols]
        col_list = ", ".join(carry_cols)
        query = f"INSERT INTO {table}_new ({col_list}) SELECT {col_list} FROM {table}"
        where_cols = [c for c in required_not_null_cols if c in carry_cols]
        if where_cols:
            query += " WHERE " + " AND ".join(f"{c} IS NOT NULL" for c in where_cols)
        conn.execute(query)
        conn.execute(f"DROP TABLE {table}")
        conn.execute(f"ALTER TABLE {table}_new RENAME TO {table}")
        conn.commit()
    finally:
        conn.execute(f"PRAGMA foreign_keys = {'ON' if fk_was_on else 'OFF'}")


def _repair_employee_fk_tables(conn):
    """
    employee_earnings and employee_deductions were created at the same time
    as the original employees/payslips schema, so they picked up the exact
    same stale "employees_old" foreign key that _repair_payslips_dangling_fk
    fixes for payslips - it just never got applied here too. This is why
    adding an allowance/deduction (add_earning/add_deduction in
    app/models/payroll.py) fails with "no such table main.employees_old"
    even after the payslips repair runs. Safe to call on every startup.
    """
    _repair_dangling_fk_table(
        conn, "employee_earnings",
        """
        CREATE TABLE employee_earnings_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
            label TEXT NOT NULL,
            amount INTEGER NOT NULL,
            taxable INTEGER DEFAULT 1,
            nssa_applicable INTEGER DEFAULT 0,
            active INTEGER DEFAULT 1
        )
        """,
        required_not_null_cols=["employee_id"],
    )
    _repair_dangling_fk_table(
        conn, "employee_deductions",
        """
        CREATE TABLE employee_deductions_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
            label TEXT NOT NULL,
            amount INTEGER NOT NULL,
            pre_tax INTEGER DEFAULT 0,
            active INTEGER DEFAULT 1
        )
        """,
        required_not_null_cols=["employee_id"],
    )


def _repair_rollover_disbursement_method(conn):
    """
    disbursements.method should always be 'Rollover' for any loan created by
    a rollover (l.parent_loan_id IS NOT NULL / an RN- loan number) - that's
    set explicitly by rollovers.approve_rollover() at disbursement time.
    If any of these ended up stored as something else (e.g. 'Cash') - from
    data entered before that logic existed, or from a manual correction that
    touched the wrong row - reports that trusted d.method instead of
    l.parent_loan_id would misreport those as real cash disbursed. Correct
    any such rows in place. Safe to call on every startup; no-ops once clean.
    """
    conn.execute(
        """UPDATE disbursements
           SET method = 'Rollover'
           WHERE method != 'Rollover'
             AND loan_id IN (SELECT id FROM loans WHERE parent_loan_id IS NOT NULL)"""
    )
    conn.commit()


def _migrate_consolidate_interest_over_tenure(conn):
    """
    'interest_over_tenure' always computed total_interest = principal * rate
    as a single lump percentage over the whole term, regardless of whatever
    rate_period was stored - which is exactly what 'flat' already does when
    rate_period='loan_term'. The two methods are mathematically identical;
    'interest_over_tenure' has been retired as a separate interest_method.
    Converts any existing loan/loan_product still using it to
    interest_method='flat', rate_period='loan_term' (same computed result,
    just expressed the one way 'flat' already supports). Safe to call on
    every startup - a no-op once nothing uses the old method anymore.
    """
    conn.execute(
        "UPDATE loans SET interest_method = 'flat', rate_period = 'loan_term' "
        "WHERE interest_method = 'interest_over_tenure'"
    )
    conn.execute(
        "UPDATE loan_products SET interest_method = 'flat', rate_period = 'loan_term' "
        "WHERE interest_method = 'interest_over_tenure'"
    )


def _migrate_interest_method_constraint(conn):
    """
    Widens interest_method's CHECK constraint on both loan_products and loans
    to allow 'interest_only_balloon' - an interest-only method where only
    interest is due each period and the full outstanding principal balloons
    due on the final period. Safe to call on every startup.
    """
    _widen_interest_method_check(conn, "loan_products", "interest_only_balloon")
    _widen_interest_method_check(conn, "loans", "interest_only_balloon")


def _migrate_permissions_table(conn):
    """
    Widens permissions from (user_id, module, allowed) to (user_id, module,
    action, allowed) so access rights can be granted per action (view/edit/
    delete/approve), not just per module. Existing rows (which only ever
    meant "can view this module") are preserved as action='view'. Safe to
    call on every startup: does nothing once the table already has the
    'action' column.
    """
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='permissions'"
    ).fetchone()
    if row is None:
        return  # table doesn't exist yet - schema.sql (run just before this) will create it

    cols = [c["name"] for c in conn.execute("PRAGMA table_info(permissions)").fetchall()]
    if "action" in cols:
        return  # already migrated

    conn.execute(
        """CREATE TABLE permissions_new (
               id          INTEGER PRIMARY KEY AUTOINCREMENT,
               user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
               module      TEXT NOT NULL,
               action      TEXT NOT NULL DEFAULT 'view',
               allowed     INTEGER NOT NULL DEFAULT 0,
               UNIQUE(user_id, module, action)
           )"""
    )
    conn.execute(
        "INSERT INTO permissions_new (user_id, module, action, allowed) "
        "SELECT user_id, module, 'view', allowed FROM permissions"
    )
    conn.execute("DROP TABLE permissions")
    conn.execute("ALTER TABLE permissions_new RENAME TO permissions")


def _migrate_locations_collation(conn):
    """
    Rebuilds the locations table with a case-insensitive UNIQUE constraint
    on name, if it was created (by an earlier version of this app) without
    COLLATE NOCASE. Without this, 'Harare' and 'harare' would be treated as
    two different locations, defeating the whole point of a standardized
    picklist. Safe to call on every startup - no-ops once already migrated,
    or if the table doesn't exist yet.
    """
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='locations'"
    ).fetchone()
    if row is None:
        return  # doesn't exist yet - schema.sql (run just before this) creates it correctly

    original_sql = row["sql"]
    if re.search(r"name\s+TEXT\s+UNIQUE\s+NOT\s+NULL\s+COLLATE\s+NOCASE", original_sql, re.IGNORECASE):
        return  # already migrated

    conn.commit()
    fk_was_on = bool(conn.execute("PRAGMA foreign_keys").fetchone()[0])
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.execute(
            "CREATE TABLE locations_new ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "name TEXT UNIQUE NOT NULL COLLATE NOCASE, "
            "active INTEGER NOT NULL DEFAULT 1)"
        )
        # Case-variant duplicates (e.g. 'Harare' and 'harare') can't both
        # survive a case-insensitive UNIQUE index - keep the first one
        # (lowest id) and drop the rest, rather than fail the migration.
        conn.execute(
            "INSERT INTO locations_new (id, name, active) "
            "SELECT id, name, active FROM locations "
            "WHERE id = (SELECT MIN(id) FROM locations AS l2 WHERE l2.name = locations.name COLLATE NOCASE)"
        )
        conn.execute("DROP TABLE locations")
        conn.execute("ALTER TABLE locations_new RENAME TO locations")
        conn.commit()
    finally:
        conn.execute(f"PRAGMA foreign_keys = {'ON' if fk_was_on else 'OFF'}")


# ---------------------------------------------------------------------
# CURRENCY MIGRATION: dollars-as-REAL -> cents-as-INTEGER
#
# schema.sql declares every money column as INTEGER now, but
# `CREATE TABLE IF NOT EXISTS` is a no-op against a table that already
# exists on disk - it does NOT retype or rewrite that table's existing
# columns or data. So for anyone upgrading from a pre-existing database
# file, every one of these columns is still physically storing float
# dollar values (e.g. 1234.56) until this migration runs once and
# rewrites them as integer cents (123456). This is idempotent and
# guarded by a marker in company_details, so it only ever runs once per
# database file - running it twice would silently multiply every amount
# in the ledger by 100 again.
# ---------------------------------------------------------------------
_CURRENCY_MIGRATION_KEY = "currency_cents_migrated"

_MONEY_COLUMNS = {
    "clients": ["average_income"],
    "loans": ["principal", "admin_fee", "capitalized_interest"],
    "repayment_schedule": [
        "principal_due", "interest_due", "total_due",
        "principal_paid", "interest_paid", "penalty_charged", "penalty_paid",
    ],
    "disbursements": ["amount"],
    "rollovers": ["outstanding_balance", "rollover_fee"],
    "repayments": [
        "amount", "principal_paid", "interest_paid", "penalty_paid",
        "admin_fee_paid", "rollover_fee_paid",
    ],
    "fees": ["amount"],
    "bad_debts": ["amount_written_off", "principal_written_off", "interest_written_off"],
    "bad_debt_recoveries": ["amount"],
    "expenses": ["amount"],
    "journal_lines": ["debit", "credit"],
    "budget_monthly_amounts": ["amount"],
    "payroll_tax_bands": ["lower_bound", "upper_bound", "deduct"],
    "employees": ["basic_salary"],
    "employee_earnings": ["amount"],
    "employee_deductions": ["amount"],
    "payslips": [
        "basic_salary", "gross_pay", "taxable_income", "nssa_insurable", "paye",
        "aids_levy", "nssa_employee", "nssa_employer", "zimdef_employer",
        "other_deductions", "net_pay",
    ],
    "payslip_lines": ["amount"],
    "one_off_earnings": ["amount"],
    "one_off_deductions": ["amount"],
}


def _migrate_currency_to_cents(conn):
    """One-time conversion of every money column from float dollars to
    integer cents, for databases that predate this change. See module
    docstring above _MONEY_COLUMNS. NOT for percentage/rate columns
    (loan_products.interest_rate, payroll_tax_bands.rate, etc.) - those
    were never dollars and are left untouched.
    """
    already_done = conn.execute(
        "SELECT value FROM company_details WHERE key = ?", (_CURRENCY_MIGRATION_KEY,)
    ).fetchone()
    if already_done is not None:
        return

    for table, columns in _MONEY_COLUMNS.items():
        table_exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        if not table_exists:
            continue
        existing_cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        for col in columns:
            if col not in existing_cols:
                continue  # column doesn't exist on this (older) install yet - nothing to convert
            # ROUND(...*100) before CAST so e.g. 19.99 -> 1999 rather than
            # truncating a float-representation artifact like 1998.9999999998.
            conn.execute(
                f"UPDATE {table} SET {col} = CAST(ROUND({col} * 100) AS INTEGER) "
                f"WHERE {col} IS NOT NULL"
            )

    conn.execute(
        "INSERT OR REPLACE INTO company_details (key, value) VALUES (?, ?)",
        (_CURRENCY_MIGRATION_KEY, "1"),
    )
    conn.commit()


def _migrate_budgets_schema(conn):
    """
    An earlier version of this app created 'budgets' as a single-period
    table (name/period_from/period_to) paired with a flat 'budget_lines'
    table (one row per account for that whole period). Budgeting has since
    been redesigned around a full yearly forecast instead (a 'year' column,
    plus 'budget_line_items' + 'budget_monthly_amounts' for month-by-month
    figures) - CREATE TABLE IF NOT EXISTS in schema.sql won't touch a table
    that already exists under the old name/shape, so this drops the old
    tables outright (there's no way to carry a single lump-sum-per-period
    budget forward into a month-by-month one) and lets schema.sql's own
    executescript, which already ran just before this, recreate the tables
    fresh on the very next call. Safe to call on every startup - no-ops
    once already migrated, or if 'budgets' doesn't exist at all yet.
    """
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='budgets'"
    ).fetchone()
    if row is None:
        return  # doesn't exist yet - schema.sql just created the current shape

    if "year" in row["sql"].lower():
        return  # already the new yearly-forecast shape

    conn.execute("DROP TABLE IF EXISTS budget_lines")
    conn.execute("DROP TABLE IF EXISTS budget_line_items")
    conn.execute("DROP TABLE IF EXISTS budget_monthly_amounts")
    conn.execute("DROP TABLE IF EXISTS budgets")
    conn.commit()
    with open(config.SCHEMA_PATH, "r") as f:
        conn.executescript(f.read())
    conn.commit()


def init_db():
    conn = get_connection()
    with open(config.SCHEMA_PATH, "r") as f:
        conn.executescript(f.read())
    _repair_payslips_dangling_fk(conn)
    _repair_employee_fk_tables(conn)
    _repair_rollover_disbursement_method(conn)
    _migrate_legacy_columns(conn)
    _migrate_fee_type_constraint(conn)
    _migrate_permissions_table(conn)
    _migrate_interest_method_constraint(conn)
    _migrate_consolidate_interest_over_tenure(conn)
    _migrate_locations_collation(conn)
    _migrate_budgets_schema(conn)
    _migrate_currency_to_cents(conn)
    _seed_accounts(conn)
    _seed_expense_categories(conn)
    _seed_locations_from_existing_clients(conn)
    _seed_admin_user(conn)
    _seed_loan_product(conn)

    # Payroll: schema_payroll_addition.sql's tables are created above as
    # part of the main schema.sql executescript (see file-header note in
    # that migration file for where it plugs in). Only the data seeding
    # needs a separate call, same as _seed_accounts()/_seed_loan_product().
    from .models.payroll import seed_payroll_defaults
    seed_payroll_defaults(conn)

    # Once-per-day backup to OneDrive - see run_daily_backup_if_needed() for
    # details. Placed last so it captures the database in its fully
    # migrated/seeded state, and after all commits above.
    conn.commit()
    run_daily_backup_if_needed(conn)

    conn.commit()
    conn.close()


def get_account_id(conn, code_or_name: str) -> int:
    row = conn.execute(
        "SELECT id FROM accounts WHERE code = ? OR name = ?", (code_or_name, code_or_name)
    ).fetchone()
    if row is None:
        raise ValueError(f"Account '{code_or_name}' not found in chart of accounts.")
    return row["id"]


def get_or_create_expense_account(conn, category_name: str) -> int:
    """Every expense category maps 1:1 to a GL expense account, created lazily."""
    code = "EXP-" + category_name.strip().upper().replace(" ", "_")[:20]
    row = conn.execute("SELECT id FROM accounts WHERE code = ?", (code,)).fetchone()
    if row:
        return row["id"]
    parent = conn.execute("SELECT id FROM accounts WHERE code = '5900'").fetchone()
    cur = conn.execute(
        "INSERT INTO accounts (code, name, type, parent_id, is_control) VALUES (?,?,?,?,0)",
        (code, category_name, "Expense", parent["id"] if parent else None),
    )
    new_id = cur.lastrowid
    # accounting.py caches code/name -> id lookups per connection; imported
    # here (not at module level) since accounting.py itself imports from
    # this module, and a top-level import would be circular.
    from .models import accounting
    accounting.invalidate_account_cache(conn)
    return new_id


# ---------------------------------------------------------------------
# DAILY BACKUP TO ONEDRIVE
#
# Runs once per calendar day, triggered from init_db() (i.e. app startup),
# rather than a separate scheduled task - so it "just works" the next time
# the app is opened on a given day, with nothing else to configure.
# ---------------------------------------------------------------------
BACKUP_FOLDER_NAME = "Loan Manager Backups"  # subfolder created inside OneDrive; rename freely
BACKUP_RETENTION_DAYS = 30                    # older daily backups get pruned automatically
_LAST_BACKUP_KEY = "last_auto_backup_date"


def _find_onedrive_folder():
    """
    Locates the local OneDrive-synced folder on this machine. OneDrive sets
    one of these environment variables depending on account type (personal
    vs work/school), so checking all three covers most installs. Returns
    None if OneDrive isn't installed/signed in here, so the caller can skip
    the backup quietly instead of failing app startup.
    """
    for var in ("OneDriveConsumer", "OneDriveCommercial", "OneDrive"):
        path = os.environ.get(var)
        if path and os.path.isdir(path):
            return path
    return None


def _prune_old_backups(folder):
    """Removes daily backups older than BACKUP_RETENTION_DAYS so the
    OneDrive folder doesn't grow forever. Always keeps at least the most
    recent backup, even if something odd left it looking "too old"."""
    cutoff = datetime.date.today() - datetime.timedelta(days=BACKUP_RETENTION_DAYS)
    files = sorted(f for f in os.listdir(folder) if f.startswith("backup_") and f.endswith(".db"))
    for f in files[:-1]:
        try:
            file_date = datetime.date.fromisoformat(f[len("backup_"):-len(".db")])
        except ValueError:
            continue
        if file_date < cutoff:
            try:
                os.remove(os.path.join(folder, f))
            except OSError:
                pass  # not worth failing startup over a cleanup step


def run_daily_backup_if_needed(conn):
    """
    Once per calendar day (tracked via a marker in company_details, the
    same pattern already used for the one-time currency migration), copies
    the live database into a "Loan Manager Backups" folder inside the
    user's OneDrive, which OneDrive then syncs to the cloud automatically.

    Uses SQLite's own online backup API rather than a plain file copy: a
    raw file copy while the app might be mid-write risks grabbing a
    corrupt/partial snapshot, whereas conn.backup() always produces a
    consistent copy. Never raises - a backup failure (e.g. OneDrive signed
    out, disk full) should never prevent the app itself from opening.
    """
    today_str = datetime.date.today().isoformat()
    try:
        row = conn.execute(
            "SELECT value FROM company_details WHERE key = ?", (_LAST_BACKUP_KEY,)
        ).fetchone()
        if row is not None and row["value"] == today_str:
            return  # already backed up today

        onedrive_root = _find_onedrive_folder()
        if onedrive_root is None:
            return  # OneDrive not installed/signed in on this machine - skip quietly

        backup_dir = os.path.join(onedrive_root, BACKUP_FOLDER_NAME)
        os.makedirs(backup_dir, exist_ok=True)
        backup_path = os.path.join(backup_dir, f"backup_{today_str}.db")

        dest = sqlite3.connect(backup_path)
        try:
            with dest:
                conn.backup(dest)
        finally:
            dest.close()

        _prune_old_backups(backup_dir)

        conn.execute(
            "INSERT OR REPLACE INTO company_details (key, value) VALUES (?, ?)",
            (_LAST_BACKUP_KEY, today_str),
        )
        conn.commit()
    except Exception:
        return  # backups are best-effort; never block app startup on one failing


def next_sequence_number(conn, table: str, column: str, prefix: str, pad: int = 6) -> str:
    """Generate a friendly sequential code like CLI-000001, LN-000012, etc."""
    row = conn.execute(f"SELECT COUNT(*) as c FROM {table}").fetchone()
    n = row["c"] + 1
    candidate = f"{prefix}-{str(n).zfill(pad)}"
    # ensure uniqueness even if rows were deleted previously
    while conn.execute(f"SELECT 1 FROM {table} WHERE {column} = ?", (candidate,)).fetchone():
        n += 1
        candidate = f"{prefix}-{str(n).zfill(pad)}"
    return candidate
