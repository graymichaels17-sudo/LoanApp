# Microfinance Manager

An offline desktop microfinance/loan management application built with **Python, Tkinter/CustomTkinter, and SQLite**. No internet connection required — all data stays on the local machine in a single SQLite file.

## Features

- **Client registry** — First Name, Surname, National ID, Gender, Location, Phone, Address, Occupation, Average Income, Guarantor, Guarantor Phone, Notes. Type-to-search across all fields.
- **Loan products** — including a **Non-Standard Loan** with flat interest charged once over the whole loan tenure, tenure tracked in **weeks**.
- **Loan approval workflow** — new loans are created "Pending"; a separate **Approvals** tab lets a manager/admin Approve or Decline each application (or edit/delete it while it's still pending). Only Approved loans can be disbursed.
- **Disbursements** — auto-generates the repayment schedule; **First Due Date is auto-calculated** from the disbursement date + repayment frequency (read-only, recalculates live as you change the date or loan).
- **Repayments** — single payment entry auto-allocated across installments using a Penalty → Interest → Principal waterfall. All entry fields clear automatically after a successful transaction.
- **Rolled-over loans** — closes an old loan's balance into a brand-new loan (auto-approved since the rollover itself is the approval action), keeping full audit trail.
- **Loan statement** — a single unified, chronological ledger per loan (opening balance, each installment's interest/penalty as it comes due, each payment received, running balance) — not split into separate tables. Loan search boxes are type-to-search.
- **Bad debts & recoveries** — write off a loan, track partial/full recoveries afterward.
- **Admin fees & penalty fees** — admin fee charged at disbursement; penalty auto-calculated on overdue installments each time the app starts, plus manual ad-hoc fee charges.
- **Expenses** — categorized expense capture (fully editable categories).
- **Reports** (all exportable to CSV):
  - Arrears (aging buckets / portfolio-at-risk)
  - Past Due
  - Bad Debts
  - Disbursement
  - **Repayment report** — Date, Loan #, Client (Name Surname Location), Amount
  - **Loan Statements report** — client info, Location, Principal, Interest, Amount Received, Outstanding Balance
  - **Rollover report** — client info, Location, Principal, Interest, Amount Received, Balance Rolled
- **Financial statements** — Income Statement, Balance Sheet, and Trial Balance, generated live from a real **double-entry general ledger** that every transaction posts to automatically.
- **Users & roles** — login required; admin/manager/loan_officer/teller/viewer roles.

## Getting started

1. Install Python 3.10+ if you don't already have it.
2. Install the one dependency:
   ```
   pip install -r requirements.txt
   ```
3. Run the app:
   ```
   python main.py
   ```
4. Log in with the default administrator account (change the password immediately via **Users → Reset Password**):
   - Username: `admin`
   - Password: `admin123`

The database file is created automatically at `data/microfinance.db` on first run. Existing database files are automatically migrated in place (new columns added) each time the app starts — you don't need to delete anything to pick up updates. To start completely fresh, delete `data/microfinance.db`.

## Loan approval workflow

1. **Loans → New Loan** creates the loan with status `Pending`.
2. **Loans → Approvals** lists everything awaiting a decision. From here you can **Approve**, **Decline**, **Edit** (change principal/rate/term/etc. while it's still pending), or **Delete** it entirely.
3. Only after a loan is Approved does it appear in **Loans → Disburse**.
4. Loan rollovers skip this queue — approving the rollover *is* the approval, so the new loan is created pre-approved and disbursed immediately.

## How the accounting works

Every financial event — a disbursement, a repayment, a fee collection, an expense, a bad-debt write-off, a bad-debt recovery — posts a **balanced double-entry journal entry** behind the scenes to a chart of accounts (`app/models/accounting.py`). The Income Statement, Balance Sheet, and Trial Balance are all derived purely from those journal entries, so they always tie out.

Two simplifying design choices to be aware of:
- Fees are recognized on a **cash basis** (posted to the ledger when marked "Paid", not the moment they're charged).
- When a loan is **rolled over**, any unpaid interest on the old loan is cleared from the sub-ledger without a matching income entry (effectively forgiven at rollover). Add a manual fee/journal entry if your policy is to keep charging it.

## Repayment allocation order

Penalty → Interest → Principal, oldest installment first. Any leftover after the whole schedule is cleared goes toward an unpaid admin fee if one exists.

## Project structure

```
main.py                     entry point
app/
  config.py                 paths, defaults, currency symbol
  schema.sql                full SQLite schema (all tables)
  database.py                connection + schema init + seed data + auto-migration
  auth.py                    password hashing + login/session
  models/
    accounting.py             double-entry journal engine + ledger queries
    clients.py                client registry CRUD
    loans.py                  loan creation, approval workflow, amortization schedule
    disbursements.py          disbursement processing (requires Approved status)
    repayments.py              repayment allocation + unified loan statement ledger
    fees.py                     manual fees + automatic overdue-penalty engine
    rollovers.py                loan rollover processing
    bad_debts.py                 write-off + recovery processing
    expenses.py                  expense categories + capture
    reports.py                    arrears / past due / bad debts / disbursement /
                                   repayment / loan statements / rollover reports
    financials.py                 income statement / balance sheet / trial balance
  ui/
    login_window.py               login screen
    main_window.py                 sidebar navigation + every module's screen
    widgets.py                     data table (CSV export), searchable combobox, form dialog
data/                        SQLite database lives here (auto-created)
exports/                     suggested folder for CSV report exports
```

## Extending it

- **Add a new loan product**: use SQL directly for now (`loan_products` table), or add a small admin screen following the pattern of `UsersView` in `main_window.py`.
- **Add a new report**: write a query function in `reports.py`, then wire up a new tab in `ReportsView`.
- **Change interest calculation**: `app/models/loans.py::build_schedule()` is the single place amortization is computed for both flat and reducing-balance methods.
- **Multi-currency / different currency symbol**: change `CURRENCY_SYMBOL` in `app/config.py`.

## Notes on this being an MVP

- Dates are entered as free-text `YYYY-MM-DD` (no calendar picker) to avoid an extra dependency.
- Reports export to CSV; PDF export can be added later (e.g. with `reportlab`) if you want printable statements.
- No automatic backup — since it's a single SQLite file, back it up by copying `data/microfinance.db` periodically.
