from datetime import date
from . import loans as loan_model
from . import accounting
from .disbursements import disburse_loan
from ..money import round_cents



def request_rollover(conn, original_loan_id: int, new_loan_data: dict, reason: str = None,
                      requested_by=None, rollover_fee: int = 0) -> dict:
    """
    Step 1 of 2: submit a rollover request.

    Computes the new loan's terms off the original loan's current
    outstanding balance and creates the new loan as Pending/Pending, exactly
    like a normal loan application - it is NOT disbursed here, and the
    original loan is left untouched (still Active). Nothing is final until
    approve_rollover() is called from the Approvals screen; whatever date
    that approval happens on becomes the official rollover date, not
    anything chosen on this request form.
    """
    original = conn.execute("SELECT * FROM loans WHERE id = ?", (original_loan_id,)).fetchone()
    if original is None:
        raise ValueError("Original loan not found.")
    if original["status"] != "Active":
        raise ValueError("Only an Active loan can be rolled over.")

    already_pending = conn.execute(
        "SELECT id FROM rollovers WHERE original_loan_id = ? AND status = 'Pending'",
        (original_loan_id,),
    ).fetchone()
    if already_pending:
        raise ValueError("This loan already has a rollover request awaiting approval.")

    bal = loan_model.outstanding_balance(conn, original_loan_id)

    new_loan_data = dict(new_loan_data)
    new_loan_data["client_id"] = original["client_id"]
    new_loan_data["parent_loan_id"] = original_loan_id

    outstanding_principal = bal["principal"]
    outstanding_balance_total = bal["total"]
    rollover_rate = float(new_loan_data.get("interest_rate", 0))
    term_months = int(new_loan_data.get("term_months", 1))
    if term_months <= 0:
        term_months = 1

    # Calculate total interest for the new loan
    new_added_interest = round_cents(outstanding_balance_total * (rollover_rate / 100.0))
    old_arrears = outstanding_balance_total - outstanding_principal
    total_new_loan_interest = old_arrears + new_added_interest

    # Principal of the new loan = original outstanding principal (not total balance)
    new_loan_data["principal"] = outstanding_principal

    # Set effective interest rate so that total interest = total_new_loan_interest
    if outstanding_principal > 0:
        effective_rate = (total_new_loan_interest / outstanding_principal) * 100.0
    else:
        effective_rate = rollover_rate  # fallback

    new_loan_data["interest_rate"] = effective_rate
    new_loan_data["interest_method"] = "flat"
    new_loan_data["rate_period"] = "loan_term"
    new_loan_data.pop("approval_status", None)  # create_loan() always starts a loan as Pending

    # ---- Create the new loan as PENDING (both status and approval_status) ----
    # It will appear in the Approvals tab, just like a normal loan application.
    new_loan_id = loan_model.create_loan(conn, new_loan_data, user_id=requested_by)

    # ---- Record the pending rollover request ----
    # rollover_date here is just a placeholder (today, the request date) -
    # approve_rollover() overwrites it with the real approval date once this
    # request is actually approved.
    cur = conn.execute(
        """INSERT INTO rollovers (original_loan_id, new_loan_id, rollover_date, outstanding_balance,
                                  reason, status, rollover_fee)
           VALUES (?,?,?,?,?,'Pending',?)""",
        (original_loan_id, new_loan_id, date.today().isoformat(), outstanding_balance_total,
         reason, rollover_fee),
    )
    rollover_id = cur.lastrowid
    conn.commit()

    return {
        "rollover_id": rollover_id,
        "new_loan_id": new_loan_id,
        "rolled_balance": outstanding_balance_total,
        "rolled_principal": outstanding_principal,
        "rolled_interest": total_new_loan_interest,
        "rollover_fee_amount": rollover_fee,
    }


def approve_rollover(conn, rollover_id: int, approved_by=None, approval_date: str = None) -> dict:
    """
    Step 2 of 2: approve a pending rollover request.

    Whatever date this runs on (or approval_date, if given explicitly)
    becomes the official rollover_date - it's used as the new loan's
    disbursement date and as the date the original loan's schedule is
    closed out on. This is the ONLY place a rollover's date gets fixed.
    """
    rollover = conn.execute("SELECT * FROM rollovers WHERE id = ?", (rollover_id,)).fetchone()
    if rollover is None:
        raise ValueError("Rollover request not found.")
    if rollover["status"] != "Pending":
        raise ValueError(f"This rollover request has already been {rollover['status'].lower()}.")

    original_loan_id = rollover["original_loan_id"]
    new_loan_id = rollover["new_loan_id"]
    approval_date = approval_date or date.today().isoformat()

    original = conn.execute("SELECT * FROM loans WHERE id = ?", (original_loan_id,)).fetchone()
    if original is None:
        raise ValueError("Original loan not found.")
    if original["status"] != "Active":
        raise ValueError(
            f"Original loan {original['loan_no']} is no longer Active "
            f"(status={original['status']}) - this rollover can no longer be completed."
        )

    new_loan = conn.execute("SELECT * FROM loans WHERE id = ?", (new_loan_id,)).fetchone()
    if new_loan is None:
        raise ValueError("New loan not found.")

    # Force approval so it can be disbursed immediately below.
    conn.execute("UPDATE loans SET approval_status = 'Approved' WHERE id = ?", (new_loan_id,))

    # Disburse it as a rollover (is_rollover=True skips the cash outflow
    # journal entry and forces method='Rollover' regardless of anything else).
    disburse_loan(
        conn,
        loan_id=new_loan_id,
        amount=new_loan["principal"],
        disbursement_date=approval_date,
        method="Rollover",
        user_id=approved_by,
        is_rollover=True,
    )

    # ---- Close the old loan ----
    conn.execute(
        "UPDATE repayment_schedule SET principal_paid = principal_due, interest_paid = interest_due, "
        "penalty_paid = penalty_charged, status='Paid' WHERE loan_id = ?",
        (original_loan_id,),
    )
    conn.execute("UPDATE loans SET status='RolledOver' WHERE id = ?", (original_loan_id,))

    # ---- Finalize the rollover record with the real approval date ----
    conn.execute(
        "UPDATE rollovers SET status='Completed', rollover_date=?, approved_by=? WHERE id = ?",
        (approval_date, approved_by, rollover_id),
    )
    conn.commit()

    # ---- Charge rollover fee (if any) – posted once approved ----
    fee_id = None
    rollover_fee = rollover["rollover_fee"] or 0
    if rollover_fee > 0:
        fee_cur = conn.execute(
            "INSERT INTO fees (loan_id, fee_type, amount, date_charged, description, status) "
            "VALUES (?, 'Rollover', ?, ?, ?, 'Paid')",
            (new_loan_id, rollover_fee, approval_date,
             f"Rollover fee - Loan #{original['loan_no']} rolled into new loan"),
        )
        fee_id = fee_cur.lastrowid
        fee_row = conn.execute("SELECT * FROM fees WHERE id = ?", (fee_id,)).fetchone()
        accounting.post_fee_paid(conn, fee_row, approved_by)
        conn.commit()

    return {
        "rollover_id": rollover_id,
        "new_loan_id": new_loan_id,
        "rollover_fee_id": fee_id,
        "rollover_fee_amount": rollover_fee,
        "rolled_balance": rollover["outstanding_balance"],
        "rollover_date": approval_date,
    }


def reject_rollover(conn, rollover_id: int, rejected_by=None):
    """
    Decline a pending rollover request: the new loan becomes Declined/
    Rejected (same as a normal declined loan application) and the original
    loan is left completely untouched (still Active).
    """
    rollover = conn.execute("SELECT * FROM rollovers WHERE id = ?", (rollover_id,)).fetchone()
    if rollover is None:
        raise ValueError("Rollover request not found.")
    if rollover["status"] != "Pending":
        raise ValueError(f"This rollover request has already been {rollover['status'].lower()}.")

    conn.execute(
        "UPDATE loans SET approval_status='Declined', status='Rejected' WHERE id = ?",
        (rollover["new_loan_id"],),
    )
    conn.execute(
        "UPDATE rollovers SET status='Rejected', approved_by=? WHERE id = ?",
        (rejected_by, rollover_id),
    )
    conn.commit()


def list_pending_rollovers(conn):
    """Rollover requests awaiting approval - for the Approvals screen."""
    return conn.execute(
        """SELECT r.*, lo.loan_no as original_loan_no, ln.loan_no as new_loan_no,
                  c.first_name, c.last_name, c.client_no, c.location
           FROM rollovers r
           JOIN loans lo ON lo.id = r.original_loan_id
           JOIN loans ln ON ln.id = r.new_loan_id
           JOIN clients c ON c.id = lo.client_id
           WHERE r.status = 'Pending'
           ORDER BY r.created_at"""
    ).fetchall()


def pending_rollover_for_loan(conn, new_loan_id: int):
    """Look up the Pending rollover request (if any) that produced this loan."""
    return conn.execute(
        "SELECT * FROM rollovers WHERE new_loan_id = ? AND status = 'Pending'",
        (new_loan_id,),
    ).fetchone()


def get_rollover_chain(conn, loan_id):
    """
    Returns the ordered list of loan ids in the rollover chain that loan_id
    belongs to: from the earliest original loan, through every rollover, to
    the last loan in the chain (which may or may not be loan_id itself - a
    loan can be rolled over more than once). Returns [loan_id] unchanged if
    the loan was never part of a rollover in either direction.
    """
    row = conn.execute("SELECT id, parent_loan_id FROM loans WHERE id = ?", (loan_id,)).fetchone()
    if row is None:
        raise ValueError("Loan not found.")

    # Walk backward to the earliest (original) loan via parent_loan_id.
    root_id = row["id"]
    seen = {root_id}
    while True:
        parent_row = conn.execute(
            "SELECT parent_loan_id FROM loans WHERE id = ?", (root_id,)
        ).fetchone()
        parent_id = parent_row["parent_loan_id"] if parent_row else None
        if not parent_id or parent_id in seen:
            break
        root_id = parent_id
        seen.add(root_id)

    # Walk forward through the rollovers table from the root to the
    # current/final loan.
    chain = [root_id]
    current_id = root_id
    seen_forward = {root_id}
    while True:
        rollover = conn.execute(
            "SELECT new_loan_id FROM rollovers WHERE original_loan_id = ? AND status = 'Completed' "
            "ORDER BY rollover_date, id LIMIT 1",
            (current_id,)
        ).fetchone()
        if not rollover or rollover["new_loan_id"] in seen_forward:
            break
        chain.append(rollover["new_loan_id"])
        seen_forward.add(rollover["new_loan_id"])
        current_id = rollover["new_loan_id"]
    return chain


def list_rollovers(conn):
    """Completed rollovers only - pending requests live in the Approvals
    screen instead (see list_pending_rollovers), and rejected ones aren't a
    'rolled over loan' at all."""
    return conn.execute(
        """SELECT r.*, lo.loan_no as original_loan_no, ln.loan_no as new_loan_no,
                  c.first_name, c.last_name, c.client_no
           FROM rollovers r
           JOIN loans lo ON lo.id = r.original_loan_id
           JOIN loans ln ON ln.id = r.new_loan_id
           JOIN clients c ON c.id = lo.client_id
           WHERE r.status = 'Completed'
           ORDER BY r.rollover_date DESC""",
    ).fetchall()

def reverse_rollover(conn, rollover_id, user_id=None):
    """
    Undo a COMPLETED rollover:
    - Delete the rollover record first (removes FK reference to new loan).
    - Delete the new loan, its disbursement, fees, amortisation schedule, and journal entries.
    - Restore the original loan to Active.
    - Rebuild the original loan's amortisation schedule and re‑apply repayments made before the rollover.
    """
    rollover = conn.execute("SELECT * FROM rollovers WHERE id = ?", (rollover_id,)).fetchone()
    if not rollover:
        raise ValueError("Rollover record not found.")
    if rollover["status"] != "Completed":
        raise ValueError(
            f"This rollover is {rollover['status']}, not Completed - nothing to reverse. "
            "Pending requests can simply be declined from the Approvals screen instead."
        )

    original_loan_id = rollover["original_loan_id"]
    new_loan_id = rollover["new_loan_id"]
    rollover_date = rollover["rollover_date"]

    # ---- Check if the new loan has any repayments (excluding rollover fee) ----
    repayments = conn.execute(
        "SELECT * FROM repayments WHERE loan_id = ? AND payment_date != ?",
        (new_loan_id, rollover_date)
    ).fetchall()
    if repayments:
        raise ValueError(
            "Cannot reverse: the new loan has repayments after the rollover. "
            "Please delete them first or contact support."
        )

    try:
        # ---- Begin transaction ----
        cur = conn.cursor()

        # ---- 1. DELETE THE ROLLOVER RECORD FIRST (removes FK to new loan) ----
        conn.execute("DELETE FROM rollovers WHERE id = ?", (rollover_id,))

        # ---- 2. Delete journal entries and lines for fees of the new loan ----
        fees = conn.execute("SELECT id FROM fees WHERE loan_id = ?", (new_loan_id,)).fetchall()
        for fee in fees:
            conn.execute(
                "DELETE FROM journal_lines WHERE journal_entry_id IN "
                "(SELECT id FROM journal_entries WHERE source_type='fee' AND source_id=?)",
                (fee["id"],)
            )
            conn.execute(
                "DELETE FROM journal_entries WHERE source_type='fee' AND source_id=?",
                (fee["id"],)
            )
            conn.execute("DELETE FROM fees WHERE id = ?", (fee["id"],))

        # ---- 3. Delete disbursement record and its journal entry ----
        disb = conn.execute("SELECT id FROM disbursements WHERE loan_id = ?", (new_loan_id,)).fetchone()
        if disb:
            conn.execute(
                "DELETE FROM journal_lines WHERE journal_entry_id IN "
                "(SELECT id FROM journal_entries WHERE source_type='disbursement' AND source_id=?)",
                (disb["id"],)
            )
            conn.execute(
                "DELETE FROM journal_entries WHERE source_type='disbursement' AND source_id=?",
                (disb["id"],)
            )
            conn.execute("DELETE FROM disbursements WHERE id = ?", (disb["id"],))

        # ---- 4. Delete amortisation schedule of the new loan ----
        conn.execute("DELETE FROM repayment_schedule WHERE loan_id = ?", (new_loan_id,))

        # ---- 5. Clear parent_loan_id reference (if any) to avoid FK conflict ----
        conn.execute("UPDATE loans SET parent_loan_id = NULL WHERE id = ?", (new_loan_id,))

        # ---- 6. Delete the new loan itself ----
        conn.execute("DELETE FROM loans WHERE id = ?", (new_loan_id,))

        # ---- 7. Restore original loan to Active ----
        conn.execute("UPDATE loans SET status = 'Active' WHERE id = ?", (original_loan_id,))

        # ---- 8. Rebuild original loan's schedule and reapply repayments ----
        loan = conn.execute("SELECT * FROM loans WHERE id = ?", (original_loan_id,)).fetchone()
        if not loan:
            raise ValueError("Original loan not found.")

        # Delete old schedule (it was marked all paid)
        conn.execute("DELETE FROM repayment_schedule WHERE loan_id = ?", (original_loan_id,))

        # Recreate schedule using the original loan data
        from .loans import generate_amortisation_schedule
        generate_amortisation_schedule(conn, original_loan_id)

        # ---- 9. Re‑apply repayments made before the rollover ----
        repayments_before = conn.execute(
            "SELECT * FROM repayments WHERE loan_id = ? AND payment_date <= ? ORDER BY payment_date, id",
            (original_loan_id, rollover_date)
        ).fetchall()

        schedule = conn.execute(
            "SELECT * FROM repayment_schedule WHERE loan_id = ? ORDER BY due_date, installment_no",
            (original_loan_id,)
        ).fetchall()

        for repayment in repayments_before:
            amount = repayment["amount"]
            for row in schedule:
                if row["status"] == "Paid":
                    continue
                prin_rem = row["principal_due"] - row["principal_paid"]
                int_rem = row["interest_due"] - row["interest_paid"]
                pen_rem = row["penalty_charged"] - row["penalty_paid"]
                total_rem = prin_rem + int_rem + pen_rem
                if total_rem <= 0:
                    continue
                if amount <= 0:
                    break
                if pen_rem > 0:
                    pay = min(amount, pen_rem)
                    conn.execute(
                        "UPDATE repayment_schedule SET penalty_paid = penalty_paid + ? WHERE id = ?",
                        (pay, row["id"])
                    )
                    amount -= pay
                if amount > 0 and int_rem > 0:
                    pay = min(amount, int_rem)
                    conn.execute(
                        "UPDATE repayment_schedule SET interest_paid = interest_paid + ? WHERE id = ?",
                        (pay, row["id"])
                    )
                    amount -= pay
                if amount > 0 and prin_rem > 0:
                    pay = min(amount, prin_rem)
                    conn.execute(
                        "UPDATE repayment_schedule SET principal_paid = principal_paid + ? WHERE id = ?",
                        (pay, row["id"])
                    )
                    amount -= pay
                conn.execute("""
                    UPDATE repayment_schedule
                    SET status = 'Paid'
                    WHERE id = ? AND
                          principal_paid >= principal_due AND
                          interest_paid >= interest_due AND
                          penalty_paid >= penalty_charged
                """, (row["id"],))
        conn.commit()

        return {"success": True, "message": "Rollover reversed successfully."}

    except Exception as e:
        conn.rollback()
        raise e