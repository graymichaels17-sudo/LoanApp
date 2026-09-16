from datetime import date
from . import accounting
from .loans import outstanding_balance
from ..money import round_cents


def write_off_loan(conn, loan_id: int, reason: str = None, date_written_off: str = None,
                    approved_by=None) -> int:
    loan = conn.execute("SELECT * FROM loans WHERE id = ?", (loan_id,)).fetchone()
    if loan is None:
        raise ValueError("Loan not found.")
    if loan["status"] not in ("Active",):
        raise ValueError(f"Only Active loans can be written off (current status={loan['status']}).")

    bal = outstanding_balance(conn, loan_id)
    
    # Calculate the exact components for the UI
    principal = round_cents(bal["principal"])
    interest = round_cents(bal["interest"])
    penalty = round_cents(bal.get("penalty", 0))
    
    # The total bad debt amount now includes principal, interest, and penalties
    amount = principal + interest + penalty
    date_written_off = date_written_off or date.today().isoformat()

    cur = conn.execute(
        """INSERT INTO bad_debts 
           (loan_id, date_written_off, principal_written_off, interest_written_off, amount_written_off, reason, approved_by, status)
           VALUES (?,?,?,?,?,?,?, 'WrittenOff')""",
        (loan_id, date_written_off, principal, interest, amount, reason, approved_by),
    )
    bad_debt_id = cur.lastrowid
    conn.execute("UPDATE loans SET status='BadDebt' WHERE id = ?", (loan_id,))

    bd_row = conn.execute("SELECT * FROM bad_debts WHERE id = ?", (bad_debt_id,)).fetchone()
    accounting.post_bad_debt_writeoff(conn, bd_row, approved_by)
    conn.commit()
    return bad_debt_id


def record_recovery(conn, bad_debt_id: int, amount: int, recovery_date: str = None,
                     method: str = "Cash", reference: str = None, user_id=None) -> int:
    bad_debt = conn.execute("SELECT * FROM bad_debts WHERE id = ?", (bad_debt_id,)).fetchone()
    if bad_debt is None:
        raise ValueError("Bad debt record not found.")
    recovery_date = recovery_date or date.today().isoformat()

    cur = conn.execute(
        """INSERT INTO bad_debt_recoveries (bad_debt_id, recovery_date, amount, method, reference, received_by)
           VALUES (?,?,?,?,?,?)""",
        (bad_debt_id, recovery_date, amount, method, reference, user_id),
    )
    recovery_id = cur.lastrowid
    rec_row = conn.execute("SELECT * FROM bad_debt_recoveries WHERE id = ?", (recovery_id,)).fetchone()
    accounting.post_bad_debt_recovery(conn, rec_row, user_id)

    total_recovered = conn.execute(
        "SELECT COALESCE(SUM(amount),0) as t FROM bad_debt_recoveries WHERE bad_debt_id = ?", (bad_debt_id,)
    ).fetchone()["t"]
    new_status = "FullyRecovered" if total_recovered >= bad_debt["amount_written_off"] else "PartiallyRecovered"
    conn.execute("UPDATE bad_debts SET status = ? WHERE id = ?", (new_status, bad_debt_id))

    conn.commit()
    return recovery_id


def list_bad_debts(conn, status: str = None):
    query = """SELECT bd.*, l.loan_no, c.first_name, c.last_name, c.client_no, c.location, c.phone as contact,
                      COALESCE((SELECT SUM(amount) FROM bad_debt_recoveries r WHERE r.bad_debt_id = bd.id),0) as total_recovered
               FROM bad_debts bd JOIN loans l ON l.id = bd.loan_id JOIN clients c ON c.id = l.client_id
               WHERE 1=1"""
    params = []
    if status:
        query += " AND bd.status = ?"
        params.append(status)
    query += " ORDER BY bd.date_written_off DESC"
    return conn.execute(query, params).fetchall()


def list_recoveries(conn, bad_debt_id: int = None):
    query = """SELECT r.*, bd.loan_id, l.loan_no FROM bad_debt_recoveries r
               JOIN bad_debts bd ON bd.id = r.bad_debt_id JOIN loans l ON l.id = bd.loan_id WHERE 1=1"""
    params = []
    if bad_debt_id:
        query += " AND r.bad_debt_id = ?"
        params.append(bad_debt_id)
    query += " ORDER BY r.recovery_date DESC"
    return conn.execute(query, params).fetchall()