from ..money import round_cents, fmt
from datetime import date
from . import accounting


def charge_fee(conn, loan_id: int, fee_type: str, amount: int, description: str = None,
                date_charged: str = None, mark_paid: bool = False, user_id=None,
                commit: bool = True) -> int:
    """Manually charge an ad-hoc Admin/Penalty/Other fee (independent of the auto overdue-penalty engine).

    commit: defaults to True for standalone use. Pass False when calling this
    from inside another function that manages its own transaction (e.g.
    disburse_loan), so a failure elsewhere in that transaction can still roll
    this back too, instead of this fee charge being permanently committed on
    its own regardless of what happens next.
    """
    date_charged = date_charged or date.today().isoformat()
    cur = conn.execute(
        "INSERT INTO fees (loan_id, fee_type, amount, date_charged, description, status) VALUES (?,?,?,?,?,?)",
        (loan_id, fee_type, amount, date_charged, description, "Paid" if mark_paid else "Unpaid"),
    )
    fee_id = cur.lastrowid
    if mark_paid:
        fee_row = conn.execute("SELECT * FROM fees WHERE id = ?", (fee_id,)).fetchone()
        accounting.post_fee_paid(conn, fee_row, user_id)
    if commit:
        conn.commit()
    return fee_id


def mark_fee_paid(conn, fee_id: int, user_id=None):
    fee_row = conn.execute("SELECT * FROM fees WHERE id = ?", (fee_id,)).fetchone()
    if fee_row is None or fee_row["status"] != "Unpaid":
        return
    conn.execute("UPDATE fees SET status='Paid' WHERE id = ?", (fee_id,))
    fee_row = conn.execute("SELECT * FROM fees WHERE id = ?", (fee_id,)).fetchone()
    accounting.post_fee_paid(conn, fee_row, user_id)
    conn.commit()


def waive_fee(conn, fee_id: int):
    conn.execute("UPDATE fees SET status='Waived' WHERE id = ?", (fee_id,))
    conn.commit()


def list_fees(conn, loan_id: int = None, fee_type: str = None, status: str = None):
    query = """SELECT f.*, l.loan_no, c.first_name, c.last_name FROM fees f
               JOIN loans l ON l.id = f.loan_id JOIN clients c ON c.id = l.client_id WHERE 1=1"""
    params = []
    if loan_id:
        query += " AND f.loan_id = ?"
        params.append(loan_id)
    if fee_type:
        query += " AND f.fee_type = ?"
        params.append(fee_type)
    if status:
        query += " AND f.status = ?"
        params.append(status)
    query += " ORDER BY f.date_charged DESC"
    return conn.execute(query, params).fetchall()


def charge_manual_penalty(conn, loan_id: int, amount: int, installment_no: int = None,
                           reason: str = None, charge_date: str = None, user_id=None) -> int:
    """
    Manually charge a penalty against a loan - staff-initiated, independent of the
    automatic overdue-penalty engine above (which is disabled by default). Adds to
    repayment_schedule.penalty_charged on the target installment (defaults to the
    earliest open installment if none specified), so it flows through the normal
    payment waterfall (post_repayment: Penalty -> Interest -> Principal) and shows
    up on the loan statement / amortisation schedule exactly like an automatic
    penalty would - the difference is it only ever appears when someone explicitly
    charges it. Returns the id of the repayment_schedule row that was charged.
    """
    if amount <= 0:
        raise ValueError("Penalty amount must be positive.")

    if installment_no is not None:
        inst = conn.execute(
            "SELECT * FROM repayment_schedule WHERE loan_id = ? AND installment_no = ?",
            (loan_id, installment_no),
        ).fetchone()
    else:
        inst = conn.execute(
            """SELECT * FROM repayment_schedule WHERE loan_id = ? AND status != 'Paid'
               ORDER BY due_date, installment_no LIMIT 1""",
            (loan_id,),
        ).fetchone()

    if inst is None:
        raise ValueError("No open installment found on this loan to charge a penalty against.")

    new_penalty = round_cents(inst["penalty_charged"] + amount)
    new_status = "Overdue" if inst["status"] != "Paid" else inst["status"]
    conn.execute(
        "UPDATE repayment_schedule SET penalty_charged = ?, status = ? WHERE id = ?",
        (new_penalty, new_status, inst["id"]),
    )
    conn.commit()
    return inst["id"]


def edit_penalty(conn, installment_id: int, new_amount: int, user_id=None) -> None:
    """
    Corrects the penalty already charged against a specific installment
    (via Charge Penalty above or the automatic overdue engine) to an exact
    new amount - unlike charge_manual_penalty, which adds more on top of
    whatever's already there, this replaces it. Use this to fix a mistaken
    or one-off penalty amount.
    """
    if new_amount < 0:
        raise ValueError("Penalty amount can't be negative.")

    inst = conn.execute("SELECT * FROM repayment_schedule WHERE id = ?", (installment_id,)).fetchone()
    if inst is None:
        raise ValueError("Installment not found.")

    if new_amount < inst["penalty_paid"]:
        raise ValueError(
            f"Can't set the penalty below {fmt(inst['penalty_paid'])} - that much has already been "
            f"paid against it. Adjust/reverse the repayment first if it needs to come down further."
        )

    # Recompute status the same way the repayment waterfall (record_repayment)
    # does: fully settled across all three components -> Paid; something
    # paid but not all -> PartiallyPaid; otherwise fall back to whether
    # it's now actually overdue by due date, the same test
    # apply_overdue_penalties uses - so zeroing out a penalty on a
    # still-overdue installment doesn't wrongly reset it to "Pending".
    if (inst["principal_paid"] >= inst["principal_due"]
            and inst["interest_paid"] >= inst["interest_due"]
            and inst["penalty_paid"] >= new_amount):
        new_status = "Paid"
    elif inst["principal_paid"] or inst["interest_paid"] or inst["penalty_paid"]:
        new_status = "PartiallyPaid"
    else:
        today = date.today()
        due = date.fromisoformat(inst["due_date"])
        new_status = "Overdue" if today > due else "Pending"

    conn.execute(
        "UPDATE repayment_schedule SET penalty_charged = ?, status = ? WHERE id = ?",
        (round_cents(new_amount), new_status, installment_id),
    )
    conn.commit()


def list_penalized_installments(conn, loan_id: int):
    """Installments on this loan that currently carry a nonzero penalty, for editing."""
    return conn.execute(
        "SELECT * FROM repayment_schedule WHERE loan_id = ? AND penalty_charged > 0 "
        "ORDER BY due_date, installment_no",
        (loan_id,),
    ).fetchall()


def apply_overdue_penalties(conn, as_of_date: str = None, user_id=None) -> int:
    """
    Scans all Active loans for installments past due (beyond grace period) that have not
    yet had a penalty applied, and charges a one-off penalty (% of the outstanding
    installment amount, per the loan's product) onto repayment_schedule.penalty_charged.
    Safe to run repeatedly (e.g. once daily on app startup) - never re-charges an
    installment that already carries a penalty. Returns number of installments penalized.
    """
    as_of_date = as_of_date or date.today().isoformat()
    count = 0
    rows = conn.execute(
        """SELECT rs.*, l.product_id, l.status as loan_status
           FROM repayment_schedule rs JOIN loans l ON l.id = rs.loan_id
           WHERE l.status = 'Active' AND rs.status != 'Paid' AND rs.penalty_charged = 0
             AND rs.due_date < ?""",
        (as_of_date,),
    ).fetchall()
    for row in rows:
        product = conn.execute("SELECT * FROM loan_products WHERE id = ?", (row["product_id"],)).fetchone()
        penalty_pct = product["penalty_pct"] if product else 5.0
        grace_days = product["grace_period_days"] if product else 0
        due = date.fromisoformat(row["due_date"])
        today = date.fromisoformat(as_of_date)
        if (today - due).days <= grace_days:
            continue
        outstanding = round_cents(row["total_due"] - row["principal_paid"] - row["interest_paid"])
        penalty_amount = round_cents(outstanding * (penalty_pct / 100.0))
        if penalty_amount <= 0:
            continue
        conn.execute(
            "UPDATE repayment_schedule SET penalty_charged = ?, status='Overdue' WHERE id = ?",
            (penalty_amount, row["id"]),
        )
        count += 1
    conn.commit()
    return count

def update_application_fee_and_journal(conn, loan_id: int, new_amount: int, 
                                       date_charged: str = None, user_id: int = None):
    """
    Update the application fee amount for a loan and adjust its journal entry.
    If no fee exists, create one with the given date_charged (or today if not provided).
    If the fee exists, update its amount and its date_charged (if given), then
    delete the old journal entry and create a new one with the updated fee.
    """
    from . import accounting
    from datetime import date

    fee = conn.execute(
        "SELECT id, amount, date_charged FROM fees WHERE loan_id = ? AND fee_type = 'Application'",
        (loan_id,)
    ).fetchone()

    if not fee:
        # Create new fee with specified date or today
        from .fees import charge_fee
        fee_date = date_charged or date.today().isoformat()
        charge_fee(
            conn, loan_id, "Application", new_amount,
            description="Application fee (added during loan edit)",
            date_charged=fee_date,
            mark_paid=True, user_id=user_id
        )
        return

    # Update amount and date if changed
    old_amount = fee["amount"]
    update_fields = []
    update_values = []
    if old_amount != new_amount:
        update_fields.append("amount = ?")
        update_values.append(new_amount)
    if date_charged and date_charged != fee["date_charged"]:
        update_fields.append("date_charged = ?")
        update_values.append(date_charged)
    if not update_fields:
        return  # nothing changed

    update_values.append(fee["id"])
    conn.execute(
        f"UPDATE fees SET {', '.join(update_fields)} WHERE id = ?",
        update_values
    )
    conn.commit()

    # ---- Delete old journal entry for this fee ----
    je = conn.execute(
        "SELECT id FROM journal_entries WHERE source_type = 'fee' AND source_id = ?",
        (fee["id"],)
    ).fetchone()
    if je:
        conn.execute("DELETE FROM journal_lines WHERE journal_entry_id = ?", (je["id"],))
        conn.execute("DELETE FROM journal_entries WHERE id = ?", (je["id"],))
        conn.commit()

    # ---- Create a new journal entry with the updated fee ----
    updated_fee = conn.execute("SELECT * FROM fees WHERE id = ?", (fee["id"],)).fetchone()
    accounting.post_fee_paid(conn, updated_fee, user_id=user_id)
    conn.commit()