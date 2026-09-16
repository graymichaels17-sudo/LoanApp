"""
Core double-entry engine. Every financial event in the system (disbursement,
repayment, fee collection, expense, bad debt write-off, bad debt recovery)
posts a balanced journal entry through post_journal(). Financial statements
are then derived purely from journal_lines, guaranteeing everything ties out.

All amounts in this module are integer cents (see ../money.py) - callers
hand in cents, journal_lines stores cents, and every balance/statement
figure returned here is cents. Formatting to a dollar string happens only
at the UI boundary, via money.fmt().
"""
from ..database import get_or_create_expense_account
from ..money import round_cents


class UnbalancedEntryError(Exception):
    pass


# ---------------------------------------------------------------------
# Chart of accounts cache
#
# post_journal() and post_manual_entry() resolve an account code/name to
# its id on every single line they post, which used to mean a
# "SELECT ... FROM accounts" round-trip per line. The chart of accounts
# rarely changes mid-session (accounts are created/renamed/deleted only
# through chart_of_accounts.py or get_or_create_expense_account()), so we
# cache the code/name -> id mapping per connection instead and only ever
# hit the database again when something explicitly invalidates it.
#
# Keyed by id(conn) rather than the connection object itself: sqlite3
# Connection objects can't be weakly referenced, and this app opens a
# single long-lived connection per session (see main_window.py's
# self.conn = get_connection()) rather than one per request, so a plain
# dict here doesn't accumulate stale entries in practice. If that
# assumption ever changes (e.g. short-lived per-request connections),
# call invalidate_account_cache(conn) when a connection closes too.
# ---------------------------------------------------------------------
_account_id_cache = {}


def invalidate_account_cache(conn=None):
    """
    Drops the cached code/name -> account id mapping so the next lookup
    re-reads the chart of accounts from the database. Must be called
    after any INSERT/UPDATE/DELETE against the accounts table (account
    creation, rename, code/type change, deletion, or a lazily-created
    expense account) - see chart_of_accounts.py and
    database.get_or_create_expense_account().

    Pass the connection to invalidate just that connection's cache;
    omit it to clear the cache for every connection.
    """
    if conn is None:
        _account_id_cache.clear()
    else:
        _account_id_cache.pop(id(conn), None)


def _cached_account_id(conn, code_or_name):
    key = id(conn)
    cache = _account_id_cache.get(key)
    if cache is None:
        cache = _load_account_id_cache(conn)
        _account_id_cache[key] = cache
    account_id = cache.get(code_or_name)
    if account_id is None:
        # Cache miss could mean a genuinely unknown account, or the chart of
        # accounts changed since we last loaded it without going through
        # invalidate_account_cache(). Refresh once before giving up.
        cache = _load_account_id_cache(conn)
        _account_id_cache[key] = cache
        account_id = cache.get(code_or_name)
    if account_id is None:
        raise ValueError(f"Account '{code_or_name}' not found in chart of accounts.")
    return account_id


def _load_account_id_cache(conn):
    cache = {}
    for row in conn.execute("SELECT id, code, name FROM accounts"):
        cache[row["code"]] = row["id"]
        cache[row["name"]] = row["id"]
    return cache


def post_journal(conn, entry_date, description, lines, source_type=None, source_id=None,
                  reference=None, created_by=None, location=None):
    """
    lines: list of dicts: {"account": "1000" or account name, "debit": x, "credit": y, "memo": ""}
    Raises UnbalancedEntryError if total debits != total credits.
    Returns the new journal_entry id.

    location: optional branch/location tag for this entry. Only meaningful
    for manual postings (post_manual_entry/post_manual_journal) - every other
    event type (disbursement, repayment, fee, bad debt) is left NULL here and
    has its location derived instead via the loan -> client relationship, so
    this column is never populated for those.
    """
    total_debit = round_cents(sum(round_cents(l.get("debit", 0)) for l in lines))
    total_credit = round_cents(sum(round_cents(l.get("credit", 0)) for l in lines))
    if total_debit != total_credit:
        raise UnbalancedEntryError(
            f"Journal entry does not balance: debit={total_debit} credit={total_credit} (cents)"
        )

    cur = conn.execute(
        "INSERT INTO journal_entries (entry_date, reference, source_type, source_id, description, created_by, location) "
        "VALUES (?,?,?,?,?,?,?)",
        (entry_date, reference, source_type, source_id, description, created_by, location),
    )
    journal_id = cur.lastrowid

    # Resolve every line's account via the cache (no per-line SELECT), then
    # insert all lines in a single executemany() round-trip instead of one
    # INSERT per line.
    line_rows = [
        (journal_id, _cached_account_id(conn, line["account"]),
         round_cents(line.get("debit", 0)), round_cents(line.get("credit", 0)),
         line.get("memo"))
        for line in lines
    ]
    conn.executemany(
        "INSERT INTO journal_lines (journal_entry_id, account_id, debit, credit, memo) VALUES (?,?,?,?,?)",
        line_rows,
    )
    return journal_id


# ---------------------------------------------------------------------
# Event-specific posting helpers (keep business modules free of GL detail)
# ---------------------------------------------------------------------

def post_disbursement(conn, disbursement_row, user_id=None):
    return post_journal(
        conn,
        entry_date=disbursement_row["disbursement_date"],
        description=f"Loan disbursement - Loan #{disbursement_row['loan_id']}",
        lines=[
            {"account": "1100", "debit": disbursement_row["amount"], "credit": 0},
            {"account": "1000", "debit": 0, "credit": disbursement_row["amount"]},
        ],
        source_type="disbursement",
        source_id=disbursement_row["id"],
        reference=f"DISB-{disbursement_row['id']:06d}",
        created_by=user_id,
    )


def post_repayment(conn, repayment_row, user_id=None):
    lines = [{"account": "1000", "debit": repayment_row["amount"], "credit": 0}]
    allocated = 0
    if repayment_row["principal_paid"]:
        lines.append({"account": "1100", "debit": 0, "credit": repayment_row["principal_paid"]})
        allocated += repayment_row["principal_paid"]
    if repayment_row["interest_paid"]:
        lines.append({"account": "4000", "debit": 0, "credit": repayment_row["interest_paid"]})
        allocated += repayment_row["interest_paid"]
    if repayment_row["penalty_paid"]:
        lines.append({"account": "4200", "debit": 0, "credit": repayment_row["penalty_paid"]})
        allocated += repayment_row["penalty_paid"]
    if repayment_row["admin_fee_paid"]:
        lines.append({"account": "4100", "debit": 0, "credit": repayment_row["admin_fee_paid"]})
        allocated += repayment_row["admin_fee_paid"]
    if "rollover_fee_paid" in repayment_row.keys() and repayment_row["rollover_fee_paid"]:
        lines.append({"account": "4500", "debit": 0, "credit": repayment_row["rollover_fee_paid"]})
        allocated += repayment_row["rollover_fee_paid"]

    # Any cash received but not allocated to principal/interest/penalty/fees
    # (a genuine overpayment with nothing left to apply it to, or plain
    # floating-point rounding dust) must still land somewhere, or this
    # entry doesn't balance and the whole repayment silently fails to post
    # to the ledger while the repayments row itself still gets saved -
    # understating Cash and Bank by the unposted amount. Route it to a
    # client-credit suspense account instead, so it's a real, visible,
    # auditable liability (money owed back to/on behalf of the client)
    # rather than vanishing.
    unapplied = repayment_row["amount"] - allocated
    if unapplied != 0:
        lines.append({"account": "2050", "debit": 0, "credit": unapplied})

    return post_journal(
        conn,
        entry_date=repayment_row["payment_date"],
        description=f"Loan repayment - Loan #{repayment_row['loan_id']}",
        lines=lines,
        source_type="repayment",
        source_id=repayment_row["id"],
        reference=f"RPY-{repayment_row['id']:06d}",
        created_by=user_id,
    )


def post_fee_paid(conn, fee_row, user_id=None):
    if fee_row["fee_type"] == "Admin":
        income_account = "4100"
    elif fee_row["fee_type"] == "Application":
        income_account = "4400"
    elif fee_row["fee_type"] == "Rollover":
        income_account = "4500"
    else:
        income_account = "4200"
    return post_journal(
        conn,
        entry_date=fee_row["date_charged"],
        description=f"{fee_row['fee_type']} fee collected - Loan #{fee_row['loan_id']}",
        lines=[
            {"account": "1000", "debit": fee_row["amount"], "credit": 0},
            {"account": income_account, "debit": 0, "credit": fee_row["amount"]},
        ],
        source_type="fee",
        source_id=fee_row["id"],
        reference=f"FEE-{fee_row['id']:06d}",
        created_by=user_id,
    )


def post_bad_debt_writeoff(conn, bad_debt_row, user_id=None):
    return post_journal(
        conn,
        entry_date=bad_debt_row["date_written_off"],
        description=f"Bad debt write-off - Loan #{bad_debt_row['loan_id']}",
        lines=[
            {"account": "5000", "debit": bad_debt_row["amount_written_off"], "credit": 0},
            {"account": "1100", "debit": 0, "credit": bad_debt_row["amount_written_off"]},
        ],
        source_type="bad_debt",
        source_id=bad_debt_row["id"],
        reference=f"WO-{bad_debt_row['id']:06d}",
        created_by=user_id,
    )


def post_bad_debt_recovery(conn, recovery_row, user_id=None):
    return post_journal(
        conn,
        entry_date=recovery_row["recovery_date"],
        description=f"Bad debt recovery - Write-off #{recovery_row['bad_debt_id']}",
        lines=[
            {"account": "1000", "debit": recovery_row["amount"], "credit": 0},
            {"account": "4300", "debit": 0, "credit": recovery_row["amount"]},
        ],
        source_type="bad_debt_recovery",
        source_id=recovery_row["id"],
        reference=f"REC-{recovery_row['id']:06d}",
        created_by=user_id,
    )


def post_expense(conn, expense_row, category_name, user_id=None):
    expense_account_id = get_or_create_expense_account(conn, category_name)
    cur_lines = [
        {"account": expense_account_id, "debit": expense_row["amount"], "credit": 0},
        {"account": "1000", "debit": 0, "credit": expense_row["amount"]},
    ]
    # post_journal resolves "account" via the cached code/name lookup; since
    # we already have the id for the dynamic expense account, resolve by id directly.
    return _post_journal_with_ids(
        conn,
        entry_date=expense_row["expense_date"],
        description=f"Expense - {category_name}: {expense_row['description'] or ''}",
        line_ids=[
            (expense_account_id, expense_row["amount"], 0),
            (_cached_account_id(conn, "1000"), 0, expense_row["amount"]),
        ],
        source_type="expense",
        source_id=expense_row["id"],
        reference=f"EXP-{expense_row['id']:06d}",
        created_by=user_id,
    )


def _post_journal_with_ids(conn, entry_date, description, line_ids, source_type, source_id,
                            reference, created_by):
    total_debit = round_cents(sum(round_cents(d) for _, d, c in line_ids))
    total_credit = round_cents(sum(round_cents(c) for _, d, c in line_ids))
    if total_debit != total_credit:
        raise UnbalancedEntryError("Journal entry does not balance.")
    cur = conn.execute(
        "INSERT INTO journal_entries (entry_date, reference, source_type, source_id, description, created_by) "
        "VALUES (?,?,?,?,?,?)",
        (entry_date, reference, source_type, source_id, description, created_by),
    )
    journal_id = cur.lastrowid
    line_rows = [
        (journal_id, account_id, round_cents(debit), round_cents(credit))
        for account_id, debit, credit in line_ids
    ]
    conn.executemany(
        "INSERT INTO journal_lines (journal_entry_id, account_id, debit, credit) VALUES (?,?,?,?)",
        line_rows,
    )
    return journal_id


# ---------------------------------------------------------------------
# Ledger queries
# ---------------------------------------------------------------------

def account_balance(conn, account_code_or_name, as_of_date=None):
    acc = conn.execute(
        "SELECT * FROM accounts WHERE code = ? OR name = ?",
        (account_code_or_name, account_code_or_name),
    ).fetchone()
    if acc is None:
        return 0
    params = [acc["id"]]
    date_clause = ""
    if as_of_date:
        date_clause = " AND je.entry_date <= ?"
        params.append(as_of_date)
    row = conn.execute(
        f"""SELECT COALESCE(SUM(jl.debit),0) as d, COALESCE(SUM(jl.credit),0) as c
            FROM journal_lines jl JOIN journal_entries je ON je.id = jl.journal_entry_id
            WHERE jl.account_id = ? {date_clause}""",
        params,
    ).fetchone()
    debit, credit = int(row["d"]), int(row["c"])
    if acc["type"] in ("Asset", "Expense"):
        return debit - credit
    return credit - debit


def trial_balance(conn, as_of_date=None):
    """
    Returns balances in integer cents. Format with money.fmt() for display.

    Computes every account's net balance in one GROUP BY query instead of
    looping over the chart of accounts and calling account_balance() (and
    therefore issuing a separate SELECT) once per account.
    """
    params = []
    # jl.id IS NULL keeps accounts with zero activity in the result (so they
    # still get a 0 balance, matching the LEFT JOIN's behaviour before any
    # date filtering); OR je.entry_date <= ? then restricts everything else
    # to lines posted on or before the cutoff.
    where_clause = ""
    if as_of_date:
        where_clause = "WHERE jl.id IS NULL OR je.entry_date <= ?"
        params.append(as_of_date)

    query = f"""
        SELECT a.code, a.name, a.type,
               COALESCE(SUM(jl.debit), 0) AS total_debit,
               COALESCE(SUM(jl.credit), 0) AS total_credit
        FROM accounts a
        LEFT JOIN journal_lines jl ON jl.account_id = a.id
        LEFT JOIN journal_entries je ON je.id = jl.journal_entry_id
        {where_clause}
        GROUP BY a.id
        ORDER BY a.code
    """
    accounts = conn.execute(query, params).fetchall()

    rows = []
    for acc in accounts:
        debit, credit = int(acc["total_debit"]), int(acc["total_credit"])
        bal = debit - credit if acc["type"] in ("Asset", "Expense") else credit - debit
        if bal == 0:
            continue
        debit_col = bal if acc["type"] in ("Asset", "Expense") and bal >= 0 else (
            -bal if acc["type"] in ("Liability", "Equity", "Income") and bal < 0 else 0
        )
        credit_col = bal if acc["type"] in ("Liability", "Equity", "Income") and bal >= 0 else (
            -bal if acc["type"] in ("Asset", "Expense") and bal < 0 else 0
        )
        rows.append({
            "code": acc["code"], "name": acc["name"], "type": acc["type"],
            "debit": debit_col, "credit": credit_col,
        })
    return rows


# ---------------------------------------------------------------------
# Manual General Ledger posting (Accounting module) - for entries that
# don't have their own dedicated form: other income, asset purchases/
# additions, or anything else, alongside expenses/equity/liabilities.
# ---------------------------------------------------------------------

def post_manual_entry(conn, entry_date, description, account_code_or_name, amount, direction,
                       offset_account="1000", reference=None, user_id=None, location=None):
    """
    A generic single-line ledger posting against any account, paired against
    an offset account (Cash and Bank by default). Powers the Accounting
    module's "Quick Ledger Posting" screen, which lets someone record a
    transaction just by picking an account and saying whether it went up or
    down, without needing to think in raw debits/credits.

    direction: 'increase' or 'decrease', relative to the account's own
    natural balance - Asset/Expense accounts increase with a debit and
    decrease with a credit; Liability/Equity/Income accounts increase with a
    credit and decrease with a debit.

    location: optional branch/location this entry belongs to (e.g. "Other
    Income" collected at a specific branch, or an expense incurred there) -
    lets it show up in that location's column on the location income
    statement instead of "Unallocated".
    """
    if amount <= 0:
        raise ValueError("Amount must be positive.")
    if direction not in ("increase", "decrease"):
        raise ValueError("direction must be 'increase' or 'decrease'.")

    account_id = _cached_account_id(conn, account_code_or_name)
    acc = conn.execute("SELECT type FROM accounts WHERE id = ?", (account_id,)).fetchone()

    debit_natural = acc["type"] in ("Asset", "Expense")
    account_is_debit = (direction == "increase") if debit_natural else (direction == "decrease")

    lines = [
        {"account": account_code_or_name,
         "debit": amount if account_is_debit else 0,
         "credit": 0 if account_is_debit else amount},
        {"account": offset_account,
         "debit": 0 if account_is_debit else amount,
         "credit": amount if account_is_debit else 0},
    ]
    return post_journal(
        conn, entry_date=entry_date, description=description, lines=lines,
        source_type="manual", reference=reference, created_by=user_id, location=location,
    )


def post_manual_journal(conn, entry_date, description, lines, reference=None, user_id=None, location=None):
    """Full multi-line manual journal entry (Accounting module's "Advanced Journal
    Entry" screen) - a thin, clearly-labelled wrapper around post_journal so manual
    postings are distinguishable (source_type='manual_journal') from every other
    automatic posting in the system when reviewing the ledger.

    location: optional branch/location tag - see post_manual_entry."""
    return post_journal(
        conn, entry_date=entry_date, description=description, lines=lines,
        source_type="manual_journal", reference=reference, created_by=user_id, location=location,
    )


def list_manual_entries(conn, date_from=None, date_to=None):
    """All manually-posted ledger entries, filtered by date, flattened into 
    individual lines for a standard debit/credit ledger view."""
    
    query = """SELECT id, entry_date, reference, description, source_type, location
               FROM journal_entries
               WHERE source_type IN ('manual', 'manual_journal')"""
    params = []
    
    if date_from:
        query += " AND entry_date >= ?"
        params.append(date_from)
    if date_to:
        query += " AND entry_date <= ?"
        params.append(date_to)
        
    query += " ORDER BY entry_date DESC, id DESC"
    
    entries = conn.execute(query, params).fetchall()
    
    result = []
    for je in entries:
        lines = conn.execute(
            """SELECT a.code, a.name, jl.debit, jl.credit
               FROM journal_lines jl JOIN accounts a ON a.id = jl.account_id
               WHERE jl.journal_entry_id = ? ORDER BY jl.id""",
            (je["id"],),
        ).fetchall()
        
        for l in lines:
            result.append({
                "id": je["id"],
                "date": je["entry_date"],
                "description": je["description"],
                "account": f"{l['code']} - {l['name']}",
                "dr": l["debit"],
                "cr": l["credit"],
                "location": je["location"] or "",
            })
            
    return result

def update_disbursement_journal(conn, loan_id: int, new_amount: float, new_date: str, user_id: int = None):
    disb = conn.execute("SELECT id FROM disbursements WHERE loan_id = ?", (loan_id,)).fetchone()
    if not disb:
        return
    disb_id = disb["id"]
    # Look up the journal entry once, then delete by its id directly rather
    # than re-running a "WHERE source_type/source_id" subquery inside each
    # DELETE. journal_lines.journal_entry_id is declared ON DELETE CASCADE
    # in the schema, so deleting the journal_entries row alone is enough -
    # its lines go with it in the same statement, no second DELETE needed.
    je = conn.execute(
        "SELECT id FROM journal_entries WHERE source_type = 'disbursement' AND source_id = ?",
        (disb_id,),
    ).fetchone()
    if je:
        conn.execute("DELETE FROM journal_entries WHERE id = ?", (je["id"],))
    # Update disbursement record
    conn.execute("UPDATE disbursements SET amount = ?, disbursement_date = ? WHERE id = ?", 
                 (new_amount, new_date, disb_id))
    conn.commit()
    # Post new disbursement journal
    disb = conn.execute("SELECT * FROM disbursements WHERE id = ?", (disb_id,)).fetchone()
    from .accounting import post_disbursement
    post_disbursement(conn, disb, user_id)

def update_fee_journal(conn, fee_id: int, new_amount: float, user_id: int = None):
    fee = conn.execute("SELECT * FROM fees WHERE id = ?", (fee_id,)).fetchone()
    if not fee:
        return
    # Same one-lookup-then-delete-by-id approach as update_disbursement_journal
    # above; the cascade on journal_lines.journal_entry_id takes care of the
    # lines automatically.
    je = conn.execute(
        "SELECT id FROM journal_entries WHERE source_type = 'fee' AND source_id = ?",
        (fee_id,),
    ).fetchone()
    if je:
        conn.execute("DELETE FROM journal_entries WHERE id = ?", (je["id"],))
    # Update fee amount
    conn.execute("UPDATE fees SET amount = ? WHERE id = ?", (new_amount, fee_id))
    conn.commit()
    # Post new fee journal
    fee = conn.execute("SELECT * FROM fees WHERE id = ?", (fee_id,)).fetchone()
    from .accounting import post_fee_paid
    post_fee_paid(conn, fee, user_id)