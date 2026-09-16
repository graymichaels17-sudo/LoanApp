from datetime import date, timedelta
from .accounting import trial_balance, post_journal
from .chart_of_accounts import ensure_profit_and_loss_account, PROFIT_AND_LOSS_CODE



def _period_movement(conn, account_type: str, date_from: str, date_to: str):
    """
    Net movement (natural balance direction) per account of a given type,
    within a date range.
    """
    # Build a filtered set of journal lines that are within the date range.
    # Closing entries (source_type='period_close') are deliberately excluded
    # here: they exist to zero out each Income/Expense account's real,
    # cumulative ledger balance into the Profit and Loss account, but they
    # aren't part of the period's actual business activity. If they weren't
    # excluded, re-running a period's income statement after it's been
    # closed would show close to zero (the closing entry's own debits/
    # credits, dated within that same range, would cancel the original
    # activity right back out in this date-filtered query).
    query = """
        SELECT a.code, a.name,
               COALESCE(SUM(jl.debit), 0) AS debit,
               COALESCE(SUM(jl.credit), 0) AS credit
        FROM accounts a
        LEFT JOIN (
            SELECT jl.account_id, jl.debit, jl.credit
            FROM journal_lines jl
            JOIN journal_entries je ON je.id = jl.journal_entry_id
            WHERE je.entry_date >= ? AND je.entry_date <= ?
              AND (je.source_type IS NULL OR je.source_type != 'period_close')
        ) jl ON jl.account_id = a.id
        WHERE a.type = ?
        GROUP BY a.id
        ORDER BY a.code
    """
    rows = conn.execute(query, (date_from, date_to, account_type)).fetchall()
    result = []
    for r in rows:
        if account_type in ("Income",):
            amount = int(r["credit"] - r["debit"])
        else:  # Expense
            amount = int(r["debit"] - r["credit"])
        if amount != 0:
            result.append({"code": r["code"], "name": r["name"], "amount": amount})
    return result



def close_period_to_profit_and_loss(conn, date_from: str, date_to: str, user_id=None):
    """
    Posts one balanced closing journal entry for the given period: every
    Income account is brought down by its period movement (debited, since
    Income is credit-normal) and every Expense account is brought down by
    its period movement (credited, since Expense is debit-normal), with the
    Profit and Loss account taking the offsetting side of each line. The
    P&L account's resulting balance is exactly net income (a credit
    balance) or net loss (a debit balance) for the period - a real,
    auditable ledger entry, computed from the same _period_movement() logic
    income_statement() uses, so it's guaranteed to match what the income
    statement reports for the same dates.

    Moving the P&L account's balance into Retained Earnings afterwards is a
    separate, manual step - post a journal via the existing Advanced
    Journal Entry screen - since only you know when your books are truly
    ready to roll forward.

    Only closes movement WITHIN date_from..date_to. For this to correctly
    zero out each account's overall balance (not just leave a same-period
    slice at zero while older, already-open activity lingers), date_from
    should pick up right where the previous close left off - don't skip a
    stretch of time, and don't close overlapping periods twice.
    """
    ensure_profit_and_loss_account(conn)

    income_lines = _period_movement(conn, "Income", date_from, date_to)
    expense_lines = _period_movement(conn, "Expense", date_from, date_to)
    if not income_lines and not expense_lines:
        raise ValueError("No income or expense activity in this period to close.")

    lines = []
    total_income = total_expense = 0
    for l in income_lines:
        amt = l["amount"]
        # Income is credit-normal: a positive period amount is closed out
        # with a debit. A negative amount (a contra/refund period) is the
        # rare reverse case, closed out with a credit instead.
        lines.append({
            "account": l["code"],
            "debit": amt if amt >= 0 else 0,
            "credit": -amt if amt < 0 else 0,
        })
        total_income += amt
    for l in expense_lines:
        amt = l["amount"]
        # Expense is debit-normal: a positive period amount is closed out
        # with a credit; a negative amount (net credit period) the reverse.
        lines.append({
            "account": l["code"],
            "debit": -amt if amt < 0 else 0,
            "credit": amt if amt >= 0 else 0,
        })
        total_expense += amt

    net_income = int(total_income - total_expense)
    if net_income >= 0:
        lines.append({"account": PROFIT_AND_LOSS_CODE, "debit": 0, "credit": net_income})
    else:
        lines.append({"account": PROFIT_AND_LOSS_CODE, "debit": -net_income, "credit": 0})

    journal_id = post_journal(
        conn,
        entry_date=date_to,
        description=f"Closing entry - Income & Expenses to Profit and Loss ({date_from} to {date_to})",
        lines=lines,
        source_type="period_close",
        reference=f"CLOSE-{date_to}",
        created_by=user_id,
    )
    conn.commit()

    return {
        "journal_id": journal_id,
        "period": {"from": date_from, "to": date_to},
        "total_income_closed": int(total_income),
        "total_expense_closed": int(total_expense),
        "net_income": net_income,
    }


def income_statement(conn, date_from: str = None, date_to: str = None):
    date_from = date_from or "0000-01-01"
    date_to = date_to or date.today().isoformat()
    # Debug print
    print(f"Income Statement period: {date_from} to {date_to}")
    income_lines = _period_movement(conn, "Income", date_from, date_to)
    expense_lines = _period_movement(conn, "Expense", date_from, date_to)
    total_income = int(sum(l["amount"] for l in income_lines))
    total_expense = int(sum(l["amount"] for l in expense_lines))
    return {
        "period": {"from": date_from, "to": date_to},
        "income": income_lines,
        "expenses": expense_lines,
        "total_income": total_income,
        "total_expenses": total_expense,
        "net_income": int(total_income - total_expense),
    }


def _account_name(conn, code):
    row = conn.execute("SELECT name FROM accounts WHERE code = ?", (code,)).fetchone()
    return row["name"] if row else code


def income_statement_by_location(conn, date_from: str = None, date_to: str = None):
    """
    Income statement split by client location, plus a Consolidated view.

    Approach: for each Income/Expense account, attribute as much of its
    ledger movement as possible to a location - via repayments, fees, and
    bad-debt records (joined through loans -> clients), and via manual
    journal entries (joined to the location tag set at posting time, if
    any). Whatever's LEFT OVER after subtracting all of that from the
    account's real, ledger-wide movement (_period_movement - the same
    figure income_statement() itself uses) is placed in "Unallocated".

    This "remainder" design is deliberate: it's what makes Consolidated
    reconcile with income_statement() BY CONSTRUCTION, for every account,
    regardless of what posts to it. Earlier versions of this function tried
    to explicitly enumerate the "location-less" categories (operating
    expenses via source_type='expense'), which broke the moment something
    else started posting to an Expense/Income account under a source_type
    this function didn't know about (e.g. payroll's salaries & wages
    posting) - that activity was real in the ledger but invisible here,
    since it matched neither the "attributed" queries nor the old
    source_type='expense' catch-all. The remainder approach can't have that
    blind spot: anything not specifically attributed above always still
    shows up, in Unallocated, because it's computed as "ledger total minus
    what we could place."

    Caveat this doesn't remove: attribution itself is still best-effort.
    A manual entry only lands in a real location if it was tagged with one
    at posting time; everything else - untagged manual entries, payroll,
    and any other source type - is real money, correctly IN the total, but
    sits in Unallocated rather than a named branch.
    """
    date_from = date_from or "0000-01-01"
    date_to = date_to or date.today().isoformat()

    buckets = {}  # location/bucket name -> {"income": {code: amt}, "expense": {code: amt}}
    attributed = {"income": {}, "expense": {}}  # code -> amount already placed in a real bucket

    def add(name, section, code, amount, track=True):
        amount = amount or 0
        if amount == 0:
            return
        b = buckets.setdefault(name, {"income": {}, "expense": {}})
        b[section][code] = int(b[section].get(code, 0) + amount)
        if track:
            attributed[section][code] = int(attributed[section].get(code, 0) + amount)

    # Interest / Penalty / Admin Fee / Rollover Fee collected as part of a
    # repayment. Joined to the repayment's own journal entry (rather than
    # trusting the repayments table alone) so this only ever counts money
    # that's actually landed in the ledger, on the ledger's own date.
    rows = conn.execute(
        """SELECT r.interest_paid, r.penalty_paid, r.admin_fee_paid, r.rollover_fee_paid,
                  c.location
           FROM repayments r
           JOIN loans l ON l.id = r.loan_id
           JOIN clients c ON c.id = l.client_id
           JOIN journal_entries je ON je.source_type = 'repayment' AND je.source_id = r.id
           WHERE je.entry_date >= ? AND je.entry_date <= ?""",
        (date_from, date_to),
    ).fetchall()
    for r in rows:
        loc = r["location"] or "Unknown"
        add(loc, "income", "4000", r["interest_paid"])
        add(loc, "income", "4200", r["penalty_paid"])
        add(loc, "income", "4100", r["admin_fee_paid"])
        add(loc, "income", "4500", r["rollover_fee_paid"])

    # Standalone ad-hoc fees (Admin/Application/Rollover/Penalty-Other) -
    # joined to a genuine source_type='fee' journal entry, NOT just
    # status='Paid'. Some fees get marked Paid a different way - when a
    # client's overpayment settles an outstanding Admin/Rollover fee inside
    # record_repayment(), that fee's status flips to 'Paid' directly without
    # ever posting its own 'fee' journal entry; that amount is already
    # folded into the repayment's own journal line above. Without this join,
    # such fees would be counted twice - once here, once via the repayment.
    fee_account = {"Admin": "4100", "Application": "4400", "Rollover": "4500"}
    rows = conn.execute(
        """SELECT f.fee_type, f.amount, c.location
           FROM fees f
           JOIN loans l ON l.id = f.loan_id
           JOIN clients c ON c.id = l.client_id
           JOIN journal_entries je ON je.source_type = 'fee' AND je.source_id = f.id
           WHERE f.status = 'Paid' AND je.entry_date >= ? AND je.entry_date <= ?""",
        (date_from, date_to),
    ).fetchall()
    for r in rows:
        code = fee_account.get(r["fee_type"], "4200")
        add(r["location"] or "Unknown", "income", code, r["amount"])

    # Bad debt recoveries (Income, 4300) - joined to their own journal entry
    # for the same reason as above.
    rows = conn.execute(
        """SELECT bdr.amount, c.location
           FROM bad_debt_recoveries bdr
           JOIN bad_debts bd ON bd.id = bdr.bad_debt_id
           JOIN loans l ON l.id = bd.loan_id
           JOIN clients c ON c.id = l.client_id
           JOIN journal_entries je ON je.source_type = 'bad_debt_recovery' AND je.source_id = bdr.id
           WHERE je.entry_date >= ? AND je.entry_date <= ?""",
        (date_from, date_to),
    ).fetchall()
    for r in rows:
        add(r["location"] or "Unknown", "income", "4300", r["amount"])

    # Bad debt write-offs (Expense, 5000) - same treatment.
    rows = conn.execute(
        """SELECT bd.amount_written_off, c.location
           FROM bad_debts bd
           JOIN loans l ON l.id = bd.loan_id
           JOIN clients c ON c.id = l.client_id
           JOIN journal_entries je ON je.source_type = 'bad_debt' AND je.source_id = bd.id
           WHERE je.entry_date >= ? AND je.entry_date <= ?""",
        (date_from, date_to),
    ).fetchall()
    for r in rows:
        add(r["location"] or "Unknown", "expense", "5000", r["amount_written_off"])

    # Manual ledger postings (Quick Ledger Posting / Advanced Journal Entry)
    # aren't tied to a loan, so they can only be located if someone tagged a
    # location on the entry itself (accounting.post_manual_entry /
    # post_manual_journal, going forward) - untagged ones (including every
    # manual entry posted before this feature existed) fall into
    # "Unallocated" alongside every other un-attributable account movement.
    manual_rows = conn.execute(
        """SELECT je.location, a.code, a.type,
                  COALESCE(SUM(jl.debit), 0) as debit, COALESCE(SUM(jl.credit), 0) as credit
           FROM journal_entries je
           JOIN journal_lines jl ON jl.journal_entry_id = je.id
           JOIN accounts a ON a.id = jl.account_id
           WHERE je.source_type IN ('manual', 'manual_journal')
             AND je.entry_date >= ? AND je.entry_date <= ?
             AND a.type IN ('Income', 'Expense')
           GROUP BY je.location, a.id""",
        (date_from, date_to),
    ).fetchall()
    for r in manual_rows:
        name = r["location"] or "Unallocated"
        if r["type"] == "Income":
            add(name, "income", r["code"], r["credit"] - r["debit"])
        else:
            add(name, "expense", r["code"], r["debit"] - r["credit"])

    # Whatever's left, per account, once real ledger movement is compared
    # against everything attributed above - covers genuine operating
    # expenses (post_expense), payroll's GL posting, and anything else this
    # function has no dedicated handling for. Tracked with track=False so
    # this remainder itself is never folded back into `attributed` (it's
    # the leftover BY DEFINITION, not something to subtract twice).
    for l in _period_movement(conn, "Income", date_from, date_to):
        remainder = int(l["amount"] - attributed["income"].get(l["code"], 0))
        add("Unallocated", "income", l["code"], remainder, track=False)
    for l in _period_movement(conn, "Expense", date_from, date_to):
        remainder = int(l["amount"] - attributed["expense"].get(l["code"], 0))
        add("Unallocated", "expense", l["code"], remainder, track=False)

    def _finalize(section_dict):
        lines = [
            {"code": code, "name": _account_name(conn, code), "amount": int(amt)}
            for code, amt in section_dict.items()
        ]
        lines.sort(key=lambda x: x["code"])
        return lines

    by_location = {}
    consolidated_income, consolidated_expense = {}, {}
    for name, data in buckets.items():
        income_lines = _finalize(data["income"])
        expense_lines = _finalize(data["expense"])
        total_income = int(sum(l["amount"] for l in income_lines))
        total_expenses = int(sum(l["amount"] for l in expense_lines))
        by_location[name] = {
            "location": name,
            "income": income_lines,
            "expenses": expense_lines,
            "total_income": total_income,
            "total_expenses": total_expenses,
            "net_income": int(total_income - total_expenses),
        }
        for code, amt in data["income"].items():
            consolidated_income[code] = int(consolidated_income.get(code, 0) + amt)
        for code, amt in data["expense"].items():
            consolidated_expense[code] = int(consolidated_expense.get(code, 0) + amt)

    consolidated_income_lines = _finalize(consolidated_income)
    consolidated_expense_lines = _finalize(consolidated_expense)
    total_income = int(sum(l["amount"] for l in consolidated_income_lines))
    total_expenses = int(sum(l["amount"] for l in consolidated_expense_lines))
    net_income = int(total_income - total_expenses)

    # Reconciliation check: Consolidated should match the ledger-based
    # income_statement() for the same period. If it doesn't, something is
    # falling through the joins above (e.g. an orphaned loan/client record)
    # and needs investigating rather than silently trusting the location
    # breakdown.
    ledger = income_statement(conn, date_from, date_to)
    income_diff = int(ledger["total_income"] - total_income)
    expense_diff = int(ledger["total_expenses"] - total_expenses)
    reconciliation = {
        "ledger_total_income": ledger["total_income"],
        "ledger_total_expenses": ledger["total_expenses"],
        "ledger_net_income": ledger["net_income"],
        "location_total_income": total_income,
        "location_total_expenses": total_expenses,
        "location_net_income": net_income,
        "income_diff": income_diff,
        "expense_diff": expense_diff,
        "matches": income_diff == 0 and expense_diff == 0,
    }

    return {
        "period": {"from": date_from, "to": date_to},
        "by_location": dict(sorted(by_location.items())),
        "consolidated": {
            "income": consolidated_income_lines,
            "expenses": consolidated_expense_lines,
            "total_income": total_income,
            "total_expenses": total_expenses,
            "net_income": net_income,
        },
        "reconciliation": reconciliation,
        "note": (
            "Interest/penalty/fee/bad-debt figures are derived from repayments, "
            "fees, and bad-debt records joined to client location. Manual ledger "
            "postings are included and split by location only where the entry was "
            "tagged with one at posting time; untagged manual entries and all "
            "operating expenses (no location on file) fall under 'Unallocated'. "
            "Consolidated is the sum across every location including Unallocated, "
            "and should match income_statement() for the same period."
        ),
    }


def income_statement_location_table(conn, date_from: str = None, date_to: str = None):
    """
    Pivoted view of income_statement_by_location(), ready for a DataTable:
    one row per account (grouped under an Income/Expense header), one column
    per location, with Consolidated as the last column.
    """
    data = income_statement_by_location(conn, date_from, date_to)
    by_location = data["by_location"]
    consolidated = data["consolidated"]

    # Column order: every location that actually has activity, "Unallocated"
    # pushed to just before Consolidated (it's a catch-all, not a real
    # branch), Consolidated always last.
    location_names = [n for n in by_location.keys() if n != "Unallocated"]
    if "Unallocated" in by_location:
        location_names.append("Unallocated")
    columns = [("metric", "Account")] + [(n, n) for n in location_names] + [("consolidated", "Consolidated")]

    def _rows_for(section, consolidated_lines):
        rows = []
        for line in consolidated_lines:
            code = line["code"]
            row = {"metric": line["name"]}
            for name in location_names:
                loc_lines = {l["code"]: l["amount"] for l in by_location[name][section]}
                row[name] = int(loc_lines.get(code, 0))
            row["consolidated"] = line["amount"]
            rows.append(row)
        return rows

    income_rows = _rows_for("income", consolidated["income"])
    expense_rows = _rows_for("expenses", consolidated["expenses"])

    total_income_row = {"metric": "TOTAL INCOME"}
    total_expense_row = {"metric": "TOTAL EXPENSES"}
    net_income_row = {"metric": "NET INCOME"}
    for name in location_names:
        total_income_row[name] = by_location[name]["total_income"]
        total_expense_row[name] = by_location[name]["total_expenses"]
        net_income_row[name] = by_location[name]["net_income"]
    total_income_row["consolidated"] = consolidated["total_income"]
    total_expense_row["consolidated"] = consolidated["total_expenses"]
    net_income_row["consolidated"] = consolidated["net_income"]

    rows = (
        [{"metric": "INCOME"}] + income_rows + [total_income_row]
        + [{"metric": ""}, {"metric": "EXPENSES"}] + expense_rows + [total_expense_row]
        + [{"metric": ""}, net_income_row]
    )

    return {
        "period": data["period"],
        "columns": columns,
        "rows": rows,
        "note": data["note"],
        "reconciliation": data["reconciliation"],
    }


# The rest of the file remains unchanged (balance_sheet, full_trial_balance, cash_flow_statement, etc.)


def _last_close_date(conn):
    """The entry_date of the most recent period_close journal entry, if any."""
    row = conn.execute(
        "SELECT MAX(entry_date) d FROM journal_entries WHERE source_type = 'period_close'"
    ).fetchone()
    return row["d"] if row else None


def balance_sheet(conn, as_of_date: str = None):
    as_of_date = as_of_date or date.today().isoformat()
    tb = trial_balance(conn, as_of_date)

    assets = [r for r in tb if r["type"] == "Asset"]
    liabilities = [r for r in tb if r["type"] == "Liability"]
    equity = [r for r in tb if r["type"] == "Equity"]

    total_assets = int(sum(r["debit"] - r["credit"] for r in assets))
    total_liabilities = int(sum(r["credit"] - r["debit"] for r in liabilities))
    # Includes the Profit and Loss account's balance, if any periods have
    # been formally closed to it via close_period_to_profit_and_loss().
    equity_recorded = int(sum(r["credit"] - r["debit"] for r in equity))

    # Net income NOT YET closed to the Profit and Loss account - i.e. only
    # activity since the most recent close, not all-time since inception.
    # Anything through the last close is already counted once, for real,
    # inside equity_recorded above (as the P&L account's own posted
    # balance); recomputing net income from account inception here as well
    # would double-count everything up through that close.
    last_close = _last_close_date(conn)
    if last_close:
        unclosed_from = (date.fromisoformat(last_close) + timedelta(days=1)).isoformat()
    else:
        unclosed_from = "0000-01-01"
    inc = income_statement(conn, date_from=unclosed_from, date_to=as_of_date)
    net_income_to_date = inc["net_income"]

    total_equity = int(equity_recorded + net_income_to_date)

    return {
        "as_of": as_of_date,
        "assets": assets, "total_assets": total_assets,
        "liabilities": liabilities, "total_liabilities": total_liabilities,
        # profit_loss_current is now specifically the UNCLOSED portion (see
        # comment above) - the Profit and Loss account's own closed-in
        # balance shows up as its own line inside `equity` instead.
        "equity": equity, "profit_loss_current": net_income_to_date,
        "total_equity": total_equity,
        "total_liabilities_and_equity": int(total_liabilities + total_equity),
        "balanced": total_assets == (total_liabilities + total_equity),
    }


def full_trial_balance(conn, as_of_date: str = None):
    as_of_date = as_of_date or date.today().isoformat()
    rows = trial_balance(conn, as_of_date)
    total_debit = int(sum(r["debit"] for r in rows))
    total_credit = int(sum(r["credit"] for r in rows))
    return {"as_of": as_of_date, "rows": rows, "total_debit": total_debit, "total_credit": total_credit}


def _cash_balance_as_of(conn, cash_account_id, as_of_date, before=False):
    op = "<" if before else "<="
    row = conn.execute(
        f"""SELECT COALESCE(SUM(jl.debit),0) - COALESCE(SUM(jl.credit),0) as bal
            FROM journal_lines jl JOIN journal_entries je ON je.id = jl.journal_entry_id
            WHERE jl.account_id = ? AND je.entry_date {op} ?""",
        (cash_account_id, as_of_date),
    ).fetchone()
    return int(row["bal"])


def cash_flow_statement(conn, date_from: str = None, date_to: str = None):
    """
    Direct-method cash flow statement mapped specifically to detailed summary 
    Inflows and Outflows categories.
    """
    date_from = date_from or "0000-01-01"
    date_to = date_to or date.today().isoformat()

    cash_account = conn.execute("SELECT id FROM accounts WHERE code = '1000'").fetchone()
    empty = {
        "period": {"from": date_from, "to": date_to},
        "inflows": [], "outflows": [],
        "total_inflows": 0, "total_outflows": 0,
        "net_change_in_cash": 0, "opening_cash": 0, "closing_cash": 0,
    }
    if cash_account is None:
        return empty
    cash_id = cash_account["id"]

    # FIX: Sum the credits and debits independently so gross inflows 
    # and gross outflows are not netted against each other.
    sibling_rows = conn.execute(
        """SELECT a.code AS sibling_code,
                  SUM(sib.credit) AS total_credit,
                  SUM(sib.debit) AS total_debit
           FROM journal_lines jl_cash
           JOIN journal_entries je ON je.id = jl_cash.journal_entry_id
           JOIN journal_lines sib ON sib.journal_entry_id = jl_cash.journal_entry_id
                                  AND sib.account_id != jl_cash.account_id
           JOIN accounts a ON a.id = sib.account_id
           WHERE jl_cash.account_id = ?
             AND jl_cash.debit != jl_cash.credit
             AND je.entry_date >= ? AND je.entry_date <= ?
           GROUP BY a.code""",
        (cash_id, date_from, date_to),
    ).fetchall()

    inflows_dict = {
        "Repayments": 0,
        "Bad debts recovery": 0,
        "Admin fees": 0,
        "Rollover fees": 0,
        "Application fee": 0,
        "Other Inflows": 0
    }
    outflows_dict = {
        "Disbursements": 0,
        "Expenses and other outflows": 0
    }

    for r in sibling_rows:
        code = r["sibling_code"]
        total_credit = r["total_credit"] or 0 # Sibling credited = Cash Inflow
        total_debit = r["total_debit"] or 0   # Sibling debited = Cash Outflow

        # 1. Map all Inflows (Sibling Credits)
        if total_credit > 0: 
            if code in ("1100", "4000", "4200"): 
                inflows_dict["Repayments"] += total_credit
            elif code == "4300":
                inflows_dict["Bad debts recovery"] += total_credit
            elif code == "4100":
                inflows_dict["Admin fees"] += total_credit
            elif code == "4500":
                inflows_dict["Rollover fees"] += total_credit
            elif code == "4400":
                inflows_dict["Application fee"] += total_credit
            else:
                inflows_dict["Other Inflows"] += total_credit
                
        # 2. Map all Outflows (Sibling Debits)
        if total_debit > 0: 
            if code == "1100": 
                outflows_dict["Disbursements"] += total_debit
            else:
                outflows_dict["Expenses and other outflows"] += total_debit

    # Format lines for UI (exclude zero balances)
    inflow_lines = [{"description": k, "amount": int(v)} for k, v in inflows_dict.items() if v != 0]
    outflow_lines = [{"description": k, "amount": int(v)} for k, v in outflows_dict.items() if v != 0]

    total_inflows = int(sum(l["amount"] for l in inflow_lines))
    total_outflows = int(sum(l["amount"] for l in outflow_lines))
    net_change = int(total_inflows - total_outflows)

    opening_cash = _cash_balance_as_of(conn, cash_id, date_from, before=True)
    closing_cash = int(opening_cash + net_change)

    return {
        "period": {"from": date_from, "to": date_to},
        "inflows": inflow_lines, "outflows": outflow_lines,
        "total_inflows": total_inflows, "total_outflows": total_outflows,
        "net_change_in_cash": net_change,
        "opening_cash": opening_cash, "closing_cash": closing_cash,
    }