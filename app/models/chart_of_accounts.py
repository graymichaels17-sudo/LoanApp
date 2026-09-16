"""
Chart of Accounts management - lets an admin define new General Ledger
accounts beyond the default set database.py seeds on first run, choosing
which category (Asset, Liability, Equity, Income, or Expense) each rolls up
under. Every balance/statement calculation in accounting.py keys off of
exactly these five type names, so they're enforced here rather than left
free-text.
"""

from . import accounting

ACCOUNT_TYPES = ["Asset", "Liability", "Equity", "Income", "Expense"]

PROFIT_AND_LOSS_CODE = "3200"

# Codes the accounting engine references directly by their code string
# (accounting.py, disbursements.py, repayments.py, bad_debts.py, expenses.py,
# equity_liabilities.py, financials.py, payroll.py all post to these by name). Renaming
# or deleting one of these codes would silently break whichever module posts
# to it, so they're locked here - the account can still be renamed (the
# display name), just not have its code changed or be deleted.
PROTECTED_CODES = {
    "1000", "1100", "1150", "2000", "3000", "3100",
    "4000", "4100", "4200", "4300", "4400", "5000",
    PROFIT_AND_LOSS_CODE,
    # Payroll (app/models/payroll.py posts to these directly)
    "2100", "2150", "2160", "2170", "2180", "5100", "5110", "5120",
}


def ensure_profit_and_loss_account(conn) -> int:
    """
    Creates the Profit and Loss (Income Summary) account if it doesn't
    already exist, and returns its id. Used by
    financials.close_period_to_profit_and_loss() so a period can be closed
    without a separate manual setup step first. Safe to call repeatedly -
    it's a no-op once the account exists.
    """
    existing = conn.execute(
        "SELECT id FROM accounts WHERE code = ?", (PROFIT_AND_LOSS_CODE,)
    ).fetchone()
    if existing:
        return existing["id"]
    return create_account(conn, PROFIT_AND_LOSS_CODE, "Profit and Loss Account", "Equity")


def list_accounts(conn):
    return conn.execute("SELECT * FROM accounts ORDER BY code").fetchall()


def get_account(conn, account_id: int):
    return conn.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()


def account_has_activity(conn, account_id: int) -> bool:
    return conn.execute(
        "SELECT COUNT(*) c FROM journal_lines WHERE account_id = ?", (account_id,)
    ).fetchone()["c"] > 0


def create_account(conn, code: str, name: str, type_: str, is_control: bool = False, parent_id=None) -> int:
    code = (code or "").strip()
    name = (name or "").strip()
    if not code or not name:
        raise ValueError("Code and name are required.")
    if type_ not in ACCOUNT_TYPES:
        raise ValueError(f"Type must be one of: {', '.join(ACCOUNT_TYPES)}.")
    existing = conn.execute("SELECT id FROM accounts WHERE code = ? OR name = ?", (code, name)).fetchone()
    if existing:
        raise ValueError("An account with that code or name already exists.")
    cur = conn.execute(
        "INSERT INTO accounts (code, name, type, parent_id, is_control) VALUES (?,?,?,?,?)",
        (code, name, type_, parent_id, 1 if is_control else 0),
    )
    conn.commit()
    # accounting.py caches the code/name -> id mapping for the lifetime of a
    # connection; a newly-created account wouldn't be visible to postings
    # until that cache is dropped and reloaded.
    accounting.invalidate_account_cache(conn)
    return cur.lastrowid


def update_account(conn, account_id: int, code: str = None, name: str = None,
                    type_: str = None, is_control: bool = None):
    row = get_account(conn, account_id)
    if row is None:
        raise ValueError("Account not found.")

    fields, values = [], []
    if code is not None:
        code = code.strip()
        if row["code"] in PROTECTED_CODES and code != row["code"]:
            raise ValueError(
                f"'{row['code']} - {row['name']}' is a core system account posted to directly by "
                f"the accounting engine, so its code can't be changed (you can still rename it)."
            )
        fields.append("code = ?"); values.append(code)
    if name is not None:
        fields.append("name = ?"); values.append(name.strip())
    if type_ is not None:
        if type_ not in ACCOUNT_TYPES:
            raise ValueError(f"Type must be one of: {', '.join(ACCOUNT_TYPES)}.")
        if row["code"] in PROTECTED_CODES and type_ != row["type"] and account_has_activity(conn, account_id):
            raise ValueError(
                f"'{row['code']} - {row['name']}' already has posted transactions; changing its "
                f"category now would make past statements inconsistent."
            )
        fields.append("type = ?"); values.append(type_)
    if is_control is not None:
        fields.append("is_control = ?"); values.append(1 if is_control else 0)

    if not fields:
        return
    values.append(account_id)
    conn.execute(f"UPDATE accounts SET {', '.join(fields)} WHERE id = ?", values)
    conn.commit()
    # code and/or name may have changed, which is exactly what the cached
    # lookup is keyed on - drop it so the next posting re-reads current data.
    accounting.invalidate_account_cache(conn)


def delete_account(conn, account_id: int):
    row = get_account(conn, account_id)
    if row is None:
        raise ValueError("Account not found.")
    if row["code"] in PROTECTED_CODES:
        raise ValueError(
            f"'{row['code']} - {row['name']}' is a core system account used directly by the "
            f"accounting engine and can't be deleted."
        )
    if account_has_activity(conn, account_id):
        raise ValueError(
            f"Can't delete '{row['code']} - {row['name']}' - it already has posted journal "
            f"entries against it. Accounts with transaction history can't be removed."
        )
    conn.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
    conn.commit()
    accounting.invalidate_account_cache(conn)
