from datetime import date
from . import accounting
from ..money import round_cents
from .loans import activate_and_schedule, next_due_date


def disburse_loan(conn, loan_id: int, amount: int, disbursement_date: str,
                  method: str, first_due_date: str = None, user_id: int = None,
                  reference: str = None, notes: str = None, is_rollover: bool = False):
    loan = conn.execute("SELECT * FROM loans WHERE id = ?", (loan_id,)).fetchone()
    if not loan:
        raise ValueError("Loan not found")
    if loan["status"] != "Pending":
        raise ValueError("Only pending loans can be disbursed")
    if loan["approval_status"] != "Approved":
        raise ValueError("Loan must be approved before disbursement")

    # A rollover disbursement is never actual cash out - always record it as
    # such regardless of what the caller passed in, so it can't accidentally
    # show up as "Cash" (or anything else) in disbursement reports.
    if is_rollover:
        method = "Rollover"

    # Everything below runs as ONE transaction. If any step fails partway
    # (e.g. the admin-fee charge), we roll back everything already done in
    # this function - the disbursement record, the journal entry, the
    # schedule, the capitalized-interest snapshot - so the loan is left
    # exactly as it was (still cleanly Pending, not disbursed at all)
    # instead of stuck half-disbursed with no way to finish or delete it.
    try:
        ref = reference or f"DISB-{loan_id:06d}"
        cur = conn.execute(
            "INSERT INTO disbursements (loan_id, amount, disbursement_date, method, reference, notes) "
            "VALUES (?,?,?,?,?,?)",
            (loan_id, amount, disbursement_date, method, ref, notes)
        )
        disbursement_id = cur.lastrowid

        # Skip the cash outflow journal entry if this is a rollover
        if not is_rollover:
            from .accounting import post_disbursement
            disbursement_row = conn.execute(
                "SELECT * FROM disbursements WHERE id = ?", (disbursement_id,)
            ).fetchone()
            post_disbursement(conn, disbursement_row, user_id=user_id)

        # ---- Set disbursement_date before generating schedule ----
        conn.execute(
            "UPDATE loans SET disbursement_date = ? WHERE id = ?",
            (disbursement_date, loan_id)
        )

        from .loans import generate_amortisation_schedule
        generate_amortisation_schedule(conn, loan_id)

        # ---- Snapshot the capitalized interest as it stood at disbursement ----
        # interest_due on the schedule can later be recalculated (e.g. for
        # interest_only_balloon loans, when a repayment reduces the outstanding
        # balance early). That's correct behaviour for the schedule itself, but
        # statements need a fixed, historical "capitalized at disbursement"
        # figure that doesn't drift as repayments come in later. Capture it once,
        # right here, before any repayments can exist for this loan.
        from .loans import get_amortisation_schedule
        fresh_schedule = get_amortisation_schedule(conn, loan_id)
        capitalized_interest = round_cents(sum(s["interest_due"] for s in fresh_schedule))
        conn.execute(
            "UPDATE loans SET capitalized_interest = ? WHERE id = ?",
            (capitalized_interest, loan_id),
        )

        admin_fee = loan["admin_fee"] or 0
        if admin_fee > 0:
            from .fees import charge_fee
            charge_fee(
                conn, loan_id, "Admin", admin_fee,
                description="Admin fee",
                date_charged=disbursement_date,
                mark_paid=True,
                user_id=user_id,
                commit=False,
            )

        conn.execute(
            "UPDATE loans SET status = 'Active' WHERE id = ?",
            (loan_id,)
        )

        conn.commit()
        return disbursement_id

    except Exception:
        conn.rollback()
        raise

def list_disbursements(conn, date_from=None, date_to=None, search: str = ""):
    query = """SELECT d.*, l.loan_no, c.first_name, c.last_name, c.client_no, c.location
               FROM disbursements d
               JOIN loans l ON l.id = d.loan_id
               JOIN clients c ON c.id = l.client_id
               WHERE 1=1"""
    params = []
    if date_from:
        query += " AND d.disbursement_date >= ?"
        params.append(date_from)
    if date_to:
        query += " AND d.disbursement_date <= ?"
        params.append(date_to)
    if search:
        query += " AND (l.loan_no LIKE ? OR c.first_name LIKE ? OR c.last_name LIKE ?)"
        like = f"%{search}%"
        params += [like, like, like]
    query += " ORDER BY d.disbursement_date DESC, d.id DESC"
    return conn.execute(query, params).fetchall()