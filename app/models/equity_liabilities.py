"""
Equity and Liabilities recording.
Allows manual entry of equity contributions and liability accounts.
"""
from datetime import date as date_module
from .accounting import post_journal
from ..money import round_cents


def record_equity_contribution(conn, entry_date: str, amount: int, description: str, user_id=None):
    """Record an equity contribution (increase in owner's capital)."""
    if amount <= 0:
        raise ValueError("Amount must be positive.")
    
    # Debit: Cash and Bank (1000)
    # Credit: Owner's Capital (3000)
    lines = [
        {"account": "1000", "debit": amount, "credit": 0},
        {"account": "3000", "debit": 0, "credit": amount},
    ]
    return post_journal(
        conn, entry_date=entry_date, description=description or "Equity contribution",
        lines=lines, source_type="equity", reference="EQUITY", created_by=user_id
    )


def record_liability(conn, entry_date: str, amount: int, description: str, user_id=None):
    """Record a new liability (e.g., loan taken, accrual)."""
    if amount <= 0:
        raise ValueError("Amount must be positive.")
    
    # Debit: Cash and Bank (1000)
    # Credit: Accounts Payable (2000)
    lines = [
        {"account": "1000", "debit": amount, "credit": 0},
        {"account": "2000", "debit": 0, "credit": amount},
    ]
    return post_journal(
        conn, entry_date=entry_date, description=description or "Liability recorded",
        lines=lines, source_type="liability", reference="LIABILITY", created_by=user_id
    )


def record_liability_payment(conn, entry_date: str, amount: int, description: str, user_id=None):
    """Record a payment against liabilities."""
    if amount <= 0:
        raise ValueError("Amount must be positive.")
    
    # Debit: Accounts Payable (2000)
    # Credit: Cash and Bank (1000)
    lines = [
        {"account": "2000", "debit": amount, "credit": 0},
        {"account": "1000", "debit": 0, "credit": amount},
    ]
    return post_journal(
        conn, entry_date=entry_date, description=description or "Liability payment",
        lines=lines, source_type="liability_payment", reference="LIABILITY-PAY", created_by=user_id
    )


def equity_summary(conn, as_of_date: str = None):
    """Get summary of equity and liabilities as of a date."""
    as_of_date = as_of_date or date_module.today().isoformat()
    
    # Get equity balance
    equity_row = conn.execute(
        """SELECT COALESCE(SUM(jl.credit - jl.debit), 0) as balance
           FROM journal_lines jl
           JOIN journal_entries je ON je.id = jl.journal_entry_id
           JOIN accounts a ON a.id = jl.account_id
           WHERE a.code = '3000' AND je.entry_date <= ?""",
        (as_of_date,),
    ).fetchone()
    
    # Get liability balance
    liability_row = conn.execute(
        """SELECT COALESCE(SUM(jl.credit - jl.debit), 0) as balance
           FROM journal_lines jl
           JOIN journal_entries je ON je.id = jl.journal_entry_id
           JOIN accounts a ON a.id = jl.account_id
           WHERE a.code = '2000' AND je.entry_date <= ?""",
        (as_of_date,),
    ).fetchone()
    
    return {
        "as_of": as_of_date,
        "equity": round_cents(equity_row["balance"]) if equity_row else 0,
        "liabilities": round_cents(liability_row["balance"]) if liability_row else 0,
    }


def list_equity_transactions(conn, date_from: str = None, date_to: str = None):
    """List all equity-related journal entries."""
    query = """SELECT je.*, a.code, a.name, jl.debit, jl.credit
               FROM journal_entries je
               JOIN journal_lines jl ON jl.journal_entry_id = je.id
               JOIN accounts a ON a.id = jl.account_id
               WHERE a.code = '3000'"""
    params = []
    if date_from:
        query += " AND je.entry_date >= ?"
        params.append(date_from)
    if date_to:
        query += " AND je.entry_date <= ?"
        params.append(date_to)
    query += " ORDER BY je.entry_date DESC"
    return conn.execute(query, params).fetchall()


def list_liability_transactions(conn, date_from: str = None, date_to: str = None):
    """List all liability-related journal entries."""
    query = """SELECT je.*, a.code, a.name, jl.debit, jl.credit
               FROM journal_entries je
               JOIN journal_lines jl ON jl.journal_entry_id = je.id
               JOIN accounts a ON a.id = jl.account_id
               WHERE a.code = '2000'"""
    params = []
    if date_from:
        query += " AND je.entry_date >= ?"
        params.append(date_from)
    if date_to:
        query += " AND je.entry_date <= ?"
        params.append(date_to)
    query += " ORDER BY je.entry_date DESC"
    return conn.execute(query, params).fetchall()
