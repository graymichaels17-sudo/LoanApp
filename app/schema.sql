-- =====================================================================
-- Microfinance Desktop Application - SQLite Schema
-- Double-entry accounting backbone + operational tables
-- =====================================================================

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------------
-- USERS & ROLES
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    username        TEXT UNIQUE NOT NULL,
    password_hash   TEXT NOT NULL,
    salt            TEXT NOT NULL,
    full_name       TEXT NOT NULL,
    role            TEXT NOT NULL CHECK (role IN ('admin','manager','loan_officer','teller','viewer')),
    active          INTEGER NOT NULL DEFAULT 1,
    security_question      TEXT,
    security_answer_hash   TEXT,
    security_answer_salt   TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    last_login      TEXT
);

-- ---------------------------------------------------------------------
-- PERMISSIONS (per-user, per-module access rights; admins always have
-- full access regardless of what's stored here - see app/permissions.py)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS permissions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    module      TEXT NOT NULL,
    action      TEXT NOT NULL DEFAULT 'view',
    allowed     INTEGER NOT NULL DEFAULT 0,
    UNIQUE(user_id, module, action)
);

-- ---------------------------------------------------------------------
-- SETTINGS: CLIENT LOCATIONS (a managed lookup list so client location
-- entry can be standardized via a dropdown, rather than free text that
-- drifts - e.g. "Harare" vs "harare" vs "Harare " showing up as separate
-- rows in location-based reports. clients.location itself stays plain
-- TEXT rather than a foreign key, so existing data and every report query
-- that already joins/groups on it keep working unchanged.)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS locations (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    name    TEXT UNIQUE NOT NULL COLLATE NOCASE,
    active  INTEGER NOT NULL DEFAULT 1
);

-- ---------------------------------------------------------------------
-- CLIENT REGISTRY
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS clients (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    client_no       TEXT UNIQUE NOT NULL,
    first_name      TEXT NOT NULL,
    last_name       TEXT NOT NULL,
    national_id     TEXT UNIQUE,
    gender          TEXT CHECK (gender IN ('Male','Female','Other')),
    location        TEXT,
    phone           TEXT,
    address         TEXT,
    occupation      TEXT,
    average_income  INTEGER,
    guarantor       TEXT,
    guarantor_phone TEXT,
    date_registered TEXT NOT NULL DEFAULT (date('now')),
    status          TEXT NOT NULL DEFAULT 'Active' CHECK (status IN ('Active','Inactive','Blacklisted')),
    notes           TEXT,
    created_by      INTEGER REFERENCES users(id),
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ---------------------------------------------------------------------
-- SETTINGS: interest rate presets (reusable list of rates, pickable
-- elsewhere in the app - e.g. next to the Interest Rate field on the New
-- Loan form - independent of any particular Loan Product)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS interest_rate_presets (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    label   TEXT UNIQUE NOT NULL COLLATE NOCASE,
    rate    REAL NOT NULL,
    active  INTEGER NOT NULL DEFAULT 1
);

-- ---------------------------------------------------------------------
-- LOAN PRODUCTS (templates for interest/fees so data entry is fast)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS loan_products (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    name                TEXT UNIQUE NOT NULL,
    interest_method     TEXT NOT NULL DEFAULT 'flat' CHECK (interest_method IN ('flat','reducing_balance','interest_only_balloon','interest_only_then_flat')),
    interest_rate       REAL NOT NULL,          -- percent per period (e.g. per month)
    rate_period         TEXT NOT NULL DEFAULT 'month' CHECK (rate_period IN ('month','year','loan_term')),
    admin_fee_pct       REAL NOT NULL DEFAULT 0,   -- % of principal charged on disbursement
    penalty_pct         REAL NOT NULL DEFAULT 0,   -- % of overdue installment charged per period late
    grace_period_days   INTEGER NOT NULL DEFAULT 0,
    repayment_frequency TEXT NOT NULL DEFAULT 'monthly' CHECK (repayment_frequency IN ('weekly','biweekly','monthly')),
    term_unit_label     TEXT NOT NULL DEFAULT 'months',
    -- Phase 2 defaults for the 'interest_only_then_flat' product: after the
    -- interest-only period (interest_rate/rate_period/term_unit_label above),
    -- the principal is re-amortised flat over its own term/frequency. NULL
    -- for every other interest_method.
    phase2_term_months INTEGER,
    phase2_frequency    TEXT CHECK (phase2_frequency IN ('weekly','biweekly','monthly')),
    active              INTEGER NOT NULL DEFAULT 1
);

-- ---------------------------------------------------------------------
-- LOANS
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS loans (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    loan_no             TEXT UNIQUE NOT NULL,
    client_id           INTEGER NOT NULL REFERENCES clients(id),
    product_id          INTEGER REFERENCES loan_products(id),
    officer_id          INTEGER REFERENCES users(id),
    principal           INTEGER NOT NULL,
    interest_rate       REAL NOT NULL,
    interest_method     TEXT NOT NULL CHECK (interest_method IN ('flat','reducing_balance','interest_only_balloon','interest_only_then_flat')),
    rate_period         TEXT NOT NULL DEFAULT 'month' CHECK (rate_period IN ('month','year','loan_term')),
    term_months         INTEGER NOT NULL,
    repayment_frequency TEXT NOT NULL DEFAULT 'monthly' CHECK (repayment_frequency IN ('weekly','biweekly','monthly')),
    -- Phase 2 fields for 'interest_only_then_flat' loans only: after
    -- term_months/repayment_frequency's interest-only period, the principal
    -- is re-amortised flat over its own term/frequency. NULL for every
    -- other interest_method.
    phase2_term_months INTEGER,
    phase2_frequency    TEXT CHECK (phase2_frequency IN ('weekly','biweekly','monthly')),
    application_date    TEXT NOT NULL DEFAULT (date('now')),
    disbursement_date   TEXT,
    first_due_date      TEXT,
    maturity_date       TEXT,
    admin_fee           INTEGER NOT NULL DEFAULT 0,
    -- Capitalized interest as it stood at disbursement (a frozen snapshot -
    -- see disburse_loan()/rebuild_schedule_and_reapply_repayments() in
    -- app/models/loans.py for why this can't just be recalculated live).
    capitalized_interest INTEGER,
    status              TEXT NOT NULL DEFAULT 'Pending'
                        CHECK (status IN ('Pending','Active','Closed','RolledOver','BadDebt','Rejected')),
    approval_status     TEXT NOT NULL DEFAULT 'Pending'
                        CHECK (approval_status IN ('Pending','Approved','Declined')),
    approved_by         INTEGER REFERENCES users(id),
    approved_at         TEXT,
    parent_loan_id      INTEGER REFERENCES loans(id),   -- set if this loan is a rollover of another
    purpose             TEXT,
    collateral          TEXT,
    created_by          INTEGER REFERENCES users(id),
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Amortization / repayment schedule generated per loan
CREATE TABLE IF NOT EXISTS repayment_schedule (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    loan_id         INTEGER NOT NULL REFERENCES loans(id) ON DELETE CASCADE,
    installment_no  INTEGER NOT NULL,
    due_date        TEXT NOT NULL,
    principal_due   INTEGER NOT NULL,
    interest_due    INTEGER NOT NULL,
    total_due       INTEGER NOT NULL,
    principal_paid  INTEGER NOT NULL DEFAULT 0,
    interest_paid   INTEGER NOT NULL DEFAULT 0,
    penalty_charged INTEGER NOT NULL DEFAULT 0,
    penalty_paid    INTEGER NOT NULL DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'Pending' CHECK (status IN ('Pending','PartiallyPaid','Paid','Overdue')),
    UNIQUE(loan_id, installment_no)
);

-- ---------------------------------------------------------------------
-- DISBURSEMENTS
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS disbursements (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    loan_id         INTEGER NOT NULL REFERENCES loans(id),
    amount          INTEGER NOT NULL,
    disbursement_date TEXT NOT NULL DEFAULT (date('now')),
    method          TEXT NOT NULL DEFAULT 'Cash' CHECK (method IN ('Cash','Bank Transfer','Mobile Money','Cheque','Rollover')),
    reference       TEXT,
    disbursed_by    INTEGER REFERENCES users(id),
    notes           TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ---------------------------------------------------------------------
-- ROLLOVERS (linking old loan to new loan)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS rollovers (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    original_loan_id    INTEGER NOT NULL REFERENCES loans(id),
    new_loan_id         INTEGER NOT NULL REFERENCES loans(id),
    -- Set to the request date when a rollover is first requested, then
    -- OVERWRITTEN with the actual approval date once approve_rollover() runs
    -- (see app/models/rollovers.py) - so this always ends up meaning
    -- "the date the rollover actually happened" for any Completed row.
    rollover_date       TEXT NOT NULL DEFAULT (date('now')),
    outstanding_balance INTEGER NOT NULL,   -- balance rolled into the new loan
    reason              TEXT,
    status              TEXT NOT NULL DEFAULT 'Pending' CHECK (status IN ('Pending','Completed','Rejected')),
    rollover_fee        INTEGER NOT NULL DEFAULT 0,   -- charged once approved
    approved_by         INTEGER REFERENCES users(id),
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ---------------------------------------------------------------------
-- REPAYMENTS / TRANSACTIONS (money received from client)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS repayments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    loan_id         INTEGER NOT NULL REFERENCES loans(id),
    payment_date    TEXT NOT NULL DEFAULT (date('now')),
    amount          INTEGER NOT NULL,
    principal_paid  INTEGER NOT NULL DEFAULT 0,
    interest_paid   INTEGER NOT NULL DEFAULT 0,
    penalty_paid    INTEGER NOT NULL DEFAULT 0,
    admin_fee_paid  INTEGER NOT NULL DEFAULT 0,
    method          TEXT NOT NULL DEFAULT 'Cash' CHECK (method IN ('Cash','Bank Transfer','Mobile Money','Cheque')),
    reference       TEXT,
    received_by     INTEGER REFERENCES users(id),
    notes           TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ---------------------------------------------------------------------
-- FEES (admin fees & penalty fees charged, independent audit trail)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fees (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    loan_id         INTEGER NOT NULL REFERENCES loans(id),
    fee_type        TEXT NOT NULL CHECK (fee_type IN ('Admin','Penalty','Other')),
    amount          INTEGER NOT NULL,
    date_charged    TEXT NOT NULL DEFAULT (date('now')),
    description     TEXT,
    status          TEXT NOT NULL DEFAULT 'Unpaid' CHECK (status IN ('Unpaid','Paid','Waived')),
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ---------------------------------------------------------------------
-- BAD DEBTS & RECOVERIES
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bad_debts (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    loan_id             INTEGER NOT NULL UNIQUE REFERENCES loans(id),
    date_written_off    TEXT NOT NULL DEFAULT (date('now')),
    principal_written_off INTEGER NOT NULL DEFAULT 0,
    interest_written_off  INTEGER NOT NULL DEFAULT 0,
    amount_written_off  INTEGER NOT NULL,     -- outstanding principal+interest+penalty at write-off
    reason              TEXT,
    approved_by         INTEGER REFERENCES users(id),
    status              TEXT NOT NULL DEFAULT 'WrittenOff' CHECK (status IN ('WrittenOff','PartiallyRecovered','FullyRecovered')),
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS bad_debt_recoveries (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    bad_debt_id     INTEGER NOT NULL REFERENCES bad_debts(id),
    recovery_date   TEXT NOT NULL DEFAULT (date('now')),
    amount          INTEGER NOT NULL,
    method          TEXT NOT NULL DEFAULT 'Cash',
    reference       TEXT,
    received_by     INTEGER REFERENCES users(id),
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ---------------------------------------------------------------------
-- EXPENSES
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS expense_categories (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT UNIQUE NOT NULL,
    description TEXT
);

CREATE TABLE IF NOT EXISTS expenses (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id     INTEGER NOT NULL REFERENCES expense_categories(id),
    expense_date    TEXT NOT NULL DEFAULT (date('now')),
    amount          INTEGER NOT NULL,
    paid_to         TEXT,
    description     TEXT,
    reference       TEXT,
    recorded_by     INTEGER REFERENCES users(id),
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- ---------------------------------------------------------------------
-- DOUBLE-ENTRY ACCOUNTING: CHART OF ACCOUNTS + JOURNAL
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS accounts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    code        TEXT UNIQUE NOT NULL,
    name        TEXT NOT NULL,
    type        TEXT NOT NULL CHECK (type IN ('Asset','Liability','Equity','Income','Expense')),
    parent_id   INTEGER REFERENCES accounts(id),
    is_control  INTEGER NOT NULL DEFAULT 0    -- 1 = system-managed control account
);

CREATE TABLE IF NOT EXISTS journal_entries (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_date      TEXT NOT NULL DEFAULT (date('now')),
    reference       TEXT,               -- e.g. DISB-000012, RPY-000045
    source_type     TEXT,               -- disbursement / repayment / fee / expense / bad_debt / recovery / manual
    source_id       INTEGER,
    description     TEXT,
    location        TEXT,               -- optional branch/location tag - see accounting.post_journal
    created_by      INTEGER REFERENCES users(id),
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS journal_lines (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    journal_entry_id    INTEGER NOT NULL REFERENCES journal_entries(id) ON DELETE CASCADE,
    account_id          INTEGER NOT NULL REFERENCES accounts(id),
    debit               INTEGER NOT NULL DEFAULT 0,
    credit              INTEGER NOT NULL DEFAULT 0,
    memo                TEXT
);

-- =====================================================================
-- BUDGETING - a budget is a named FORECAST for a given YEAR, laid out
-- exactly like a spreadsheet forecast: line items (grouped under
-- sections such as Disbursements / Collections / Revenue / Other income /
-- Expenditure) each with one amount per calendar month.
--
-- A line item can optionally be linked to a real Chart of Accounts
-- account (account_id) - when it is, budget_vs_actual() in
-- models/budgets.py can reconcile it against real ledger movement for
-- the same months. Line items with no account_id (e.g. a portfolio
-- metric like "Disbursements" that isn't a ledger account) are still
-- budgeted and displayed, just without an actual/variance column.
-- =====================================================================
CREATE TABLE IF NOT EXISTS budgets (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    year          INTEGER NOT NULL,
    notes         TEXT,
    created_by    INTEGER REFERENCES users(id),
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS budget_line_items (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    budget_id     INTEGER NOT NULL REFERENCES budgets(id) ON DELETE CASCADE,
    section       TEXT,                          -- e.g. 'Revenue', 'Expenditure', 'Disbursements', 'Collections'
    label         TEXT NOT NULL,                  -- e.g. 'Interest income', 'Salaries'
    account_id    INTEGER REFERENCES accounts(id),-- optional link, enables reconciliation vs actual
    sort_order    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS budget_monthly_amounts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    line_item_id    INTEGER NOT NULL REFERENCES budget_line_items(id) ON DELETE CASCADE,
    month           INTEGER NOT NULL CHECK (month BETWEEN 1 AND 12),
    amount          INTEGER NOT NULL DEFAULT 0,
    UNIQUE (line_item_id, month)
);


-- =====================================================================
-- PAYROLL MODULE (Zimbabwe statutory payroll: PAYE, AIDS Levy, NSSA,
-- ZIMDEF). Append this block to schema.sql, right before the
-- "USEFUL INDEXES" section at the bottom.
-- =====================================================================

-- =====================================================================
-- PAYROLL TABLES
-- =====================================================================

CREATE TABLE IF NOT EXISTS payroll_settings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT UNIQUE NOT NULL,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS payroll_tax_bands (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    currency TEXT NOT NULL,
    lower_bound INTEGER NOT NULL,
    upper_bound INTEGER,
    rate REAL NOT NULL,
    deduct INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS employees (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_no TEXT UNIQUE NOT NULL,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    national_id TEXT,
    date_of_birth TEXT,
    gender TEXT,
    job_title TEXT,
    department TEXT,
    hire_date TEXT,
    employment_type TEXT DEFAULT 'Permanent',
    pay_currency TEXT DEFAULT 'USD',
    pay_frequency TEXT DEFAULT 'monthly',
    basic_salary INTEGER NOT NULL DEFAULT 0,
    bank_name TEXT,
    bank_account_no TEXT,
    nssa_number TEXT,
    tax_number TEXT,
    is_nssa_exempt INTEGER DEFAULT 0,
    is_elderly_or_disabled INTEGER DEFAULT 0,
    notes TEXT,
    created_by INTEGER,
    active INTEGER DEFAULT 1,
    termination_date TEXT
);

CREATE TABLE IF NOT EXISTS employee_earnings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    label TEXT NOT NULL,
    amount INTEGER NOT NULL,
    taxable INTEGER DEFAULT 1,
    nssa_applicable INTEGER DEFAULT 0,
    active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS employee_deductions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    label TEXT NOT NULL,
    amount INTEGER NOT NULL,
    pre_tax INTEGER DEFAULT 0,
    active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS payroll_periods (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    period_label TEXT NOT NULL,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    pay_date TEXT NOT NULL,
    status TEXT DEFAULT 'Draft',
    journal_entry_id INTEGER,
    created_by INTEGER
);

CREATE TABLE IF NOT EXISTS payslips (
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
);

CREATE TABLE IF NOT EXISTS payslip_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    payslip_id INTEGER NOT NULL REFERENCES payslips(id) ON DELETE CASCADE,
    line_type TEXT NOT NULL,
    label TEXT NOT NULL,
    amount INTEGER NOT NULL
);


CREATE TABLE IF NOT EXISTS one_off_earnings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL,
    payroll_period_id INTEGER NOT NULL,
    label TEXT NOT NULL,
    amount INTEGER NOT NULL,
    taxable INTEGER DEFAULT 1,
    nssa_applicable INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS one_off_deductions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id INTEGER NOT NULL,
    payroll_period_id INTEGER NOT NULL,
    label TEXT NOT NULL,
    amount INTEGER NOT NULL,
    pre_tax INTEGER DEFAULT 0
);

-- ---------------------------------------------------------------------
-- USEFUL INDEXES
-- ---------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_loans_client ON loans(client_id);
CREATE INDEX IF NOT EXISTS idx_loans_status ON loans(status);
CREATE INDEX IF NOT EXISTS idx_schedule_loan ON repayment_schedule(loan_id);
CREATE INDEX IF NOT EXISTS idx_schedule_status ON repayment_schedule(status);
CREATE INDEX IF NOT EXISTS idx_repayments_loan ON repayments(loan_id);
CREATE INDEX IF NOT EXISTS idx_disbursements_loan ON disbursements(loan_id);
CREATE INDEX IF NOT EXISTS idx_fees_loan ON fees(loan_id);
CREATE INDEX IF NOT EXISTS idx_journal_lines_account ON journal_lines(account_id);
CREATE INDEX IF NOT EXISTS idx_journal_entries_date ON journal_entries(entry_date);

CREATE TABLE IF NOT EXISTS company_details (
    key TEXT PRIMARY KEY,
    value TEXT
);