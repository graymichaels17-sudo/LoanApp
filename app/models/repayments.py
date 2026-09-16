from ..money import round_cents, fmt
from datetime import date
from . import accounting
from .loans import (
    close_loan_if_settled, outstanding_balance,
    recalculate_interest_only_balloon_schedule, generate_amortisation_schedule,
)


def _delete_journal_entries(conn, source_type, source_id):
    rows = conn.execute(
        "SELECT id FROM journal_entries WHERE source_type = ? AND source_id = ?",
        (source_type, source_id),
    ).fetchall()
    for row in rows:
        conn.execute("DELETE FROM journal_lines WHERE journal_entry_id = ?", (row["id"],))
        conn.execute("DELETE FROM journal_entries WHERE id = ?", (row["id"],))


def _allocate_standard(conn, loan_id, amount):
    """
    Standard Penalty -> Interest -> Principal waterfall, applied to the
    oldest not-yet-Paid installment first, spilling into later installments
    if the payment covers more than one. Used for flat / reducing_balance /
    interest_over_tenure loans.
    Returns (principal_paid_total, interest_paid_total, penalty_paid_total, remaining).
    """
    remaining = round_cents(amount)
    principal_paid_total = interest_paid_total = penalty_paid_total = 0

    installments = conn.execute(
        "SELECT * FROM repayment_schedule WHERE loan_id = ? AND status != 'Paid' "
        "ORDER BY due_date, installment_no", (loan_id,)
    ).fetchall()

    for inst in installments:
        if remaining <= 0:
            break
        penalty_owed = round_cents(inst["penalty_charged"] - inst["penalty_paid"])
        interest_owed = round_cents(inst["interest_due"] - inst["interest_paid"])
        principal_owed = round_cents(inst["principal_due"] - inst["principal_paid"])

        pay_penalty = min(remaining, penalty_owed)
        remaining = round_cents(remaining - pay_penalty)
        pay_interest = min(remaining, interest_owed) if remaining > 0 else 0
        remaining = round_cents(remaining - pay_interest)
        pay_principal = min(remaining, principal_owed) if remaining > 0 else 0
        remaining = round_cents(remaining - pay_principal)

        new_penalty_paid = round_cents(inst["penalty_paid"] + pay_penalty)
        new_interest_paid = round_cents(inst["interest_paid"] + pay_interest)
        new_principal_paid = round_cents(inst["principal_paid"] + pay_principal)
        fully_paid = (
            new_principal_paid >= inst["principal_due"]
            and new_interest_paid >= inst["interest_due"]
            and new_penalty_paid >= inst["penalty_charged"]
        )
        new_status = "Paid" if fully_paid else (
            "PartiallyPaid" if (pay_penalty + pay_interest + pay_principal) > 0 else inst["status"]
        )
        conn.execute(
            "UPDATE repayment_schedule SET principal_paid=?, interest_paid=?, penalty_paid=?, status=? WHERE id=?",
            (new_principal_paid, new_interest_paid, new_penalty_paid, new_status, inst["id"]),
        )
        principal_paid_total += pay_principal
        interest_paid_total += pay_interest
        penalty_paid_total += pay_penalty

    return principal_paid_total, interest_paid_total, penalty_paid_total, remaining


def _allocate_interest_only_balloon(conn, loan_id, amount, payment_date: str = None):
    """
    Penalty -> Interest waterfall across every installment that has actually
    fallen due - not just the earliest one - so a client who has missed more
    than one period gets every genuine arrear cleared first. Only once all of
    those due arrears are settled does any leftover count as a true
    overpayment; that leftover is then treated as an early curtailment of
    principal (capped at what's actually still outstanding on the loan)
    rather than a prepayment of a future, not-yet-due period's interest -
    because future interest is recalculated off the reduced balance
    immediately after this call (recalculate_interest_only_balloon_schedule),
    so there's no fixed future amount to "prepay" in the first place, and
    because a not-yet-due period is not an arrear at all.
    Returns (principal_paid_total, interest_paid_total, penalty_paid_total, remaining).
    """
    payment_date = payment_date or date.today().isoformat()
    remaining = round_cents(amount)
    principal_paid_total = interest_paid_total = penalty_paid_total = 0

    installments = conn.execute(
        "SELECT * FROM repayment_schedule WHERE loan_id = ? AND status != 'Paid' "
        "ORDER BY installment_no", (loan_id,)
    ).fetchall()
    if not installments:
        return 0, 0, 0, remaining
    last_installment_no = installments[-1]["installment_no"]

    def _apply(inst, pay_penalty, pay_interest, pay_principal):
        nonlocal principal_paid_total, interest_paid_total, penalty_paid_total
        new_penalty_paid = round_cents(inst["penalty_paid"] + pay_penalty)
        new_interest_paid = round_cents(inst["interest_paid"] + pay_interest)
        new_principal_paid = round_cents(inst["principal_paid"] + pay_principal)
        fully_paid = (
            new_principal_paid >= inst["principal_due"]
            and new_interest_paid >= inst["interest_due"]
            and new_penalty_paid >= inst["penalty_charged"]
        )
        new_status = "Paid" if fully_paid else (
            "PartiallyPaid" if (pay_penalty + pay_interest + pay_principal) > 0 else inst["status"]
        )
        conn.execute(
            "UPDATE repayment_schedule SET principal_paid=?, interest_paid=?, penalty_paid=?, status=? WHERE id=?",
            (new_principal_paid, new_interest_paid, new_penalty_paid, new_status, inst["id"]),
        )
        principal_paid_total += pay_principal
        interest_paid_total += pay_interest
        penalty_paid_total += pay_penalty

    # Phase 1: clear penalty + interest (and, on the balloon row itself,
    # principal) on every installment that is genuinely due as of this
    # payment - i.e. already overdue/partially paid, or whose due date has
    # arrived - in due-date order. Installments are ordered oldest-first, so
    # the moment we reach one that isn't due yet, nothing after it can be due
    # either, and we stop rather than prepaying future interest.
    for idx, inst in enumerate(installments):
        if remaining <= 0:
            break
        is_last = inst["installment_no"] == last_installment_no
        # The first still-outstanding installment is always eligible, even if
        # its due_date hasn't arrived yet - it's the period currently
        # accruing, and a payment made a few days ahead of the due date is a
        # normal on-time (early) payment of that period's interest, not a
        # prepayment of some distant future period. Only installments beyond
        # the first genuinely need their due_date to have passed (or already
        # be Overdue/PartiallyPaid) before this payment can reach them -
        # otherwise a slightly-early payment was falling straight through to
        # Phase 2 and getting misfiled as a principal curtailment instead of
        # being credited against the interest it was actually meant to pay.
        is_due = (
            idx == 0
            or inst["status"] in ("Overdue", "PartiallyPaid")
            or inst["due_date"] <= payment_date
        )
        if not is_due:
            break

        penalty_owed = round_cents(inst["penalty_charged"] - inst["penalty_paid"])
        interest_owed = round_cents(inst["interest_due"] - inst["interest_paid"])

        pay_penalty = min(remaining, penalty_owed)
        remaining = round_cents(remaining - pay_penalty)
        pay_interest = min(remaining, interest_owed) if remaining > 0 else 0
        remaining = round_cents(remaining - pay_interest)

        pay_principal = 0
        if is_last:
            # The balloon period is itself due: extra clears the remaining
            # principal here, same as the standard waterfall.
            principal_owed = round_cents(inst["principal_due"] - inst["principal_paid"])
            pay_principal = min(remaining, principal_owed) if remaining > 0 else 0
            remaining = round_cents(remaining - pay_principal)

        _apply(inst, pay_penalty, pay_interest, pay_principal)

    # Phase 2: any amount still left over, after every due arrear above has
    # been fully settled, is a genuine overpayment - curtail principal early
    # against the first installment that still isn't fully paid, capped at
    # what's genuinely still outstanding (so a huge overpayment doesn't drive
    # the balance negative). Only one installment ever absorbs this, since
    # recalculate_interest_only_balloon_schedule() re-derives every later
    # period's interest from the new, lower balance right after this call.
    if remaining > 0:
        inst = conn.execute(
            "SELECT * FROM repayment_schedule WHERE loan_id = ? AND status != 'Paid' "
            "ORDER BY installment_no LIMIT 1", (loan_id,)
        ).fetchone()
        if inst is not None:
            is_last = inst["installment_no"] == last_installment_no
            if is_last:
                principal_owed = round_cents(inst["principal_due"] - inst["principal_paid"])
                pay_principal = min(remaining, principal_owed)
            else:
                outstanding_principal = outstanding_balance(conn, loan_id)["principal"]
                pay_principal = min(remaining, outstanding_principal)
            remaining = round_cents(remaining - pay_principal)
            _apply(inst, 0, 0, pay_principal)

    return principal_paid_total, interest_paid_total, penalty_paid_total, remaining


def _allocate_payment(conn, loan_id, amount, interest_method, payment_date=None):
    if interest_method == "interest_only_balloon":
        return _allocate_interest_only_balloon(conn, loan_id, amount, payment_date)
    return _allocate_standard(conn, loan_id, amount)


def _recompute_loan_repayments(conn, loan_id, user_id=None):
    """
    Fully recomputes a loan's repayment_schedule paid-amounts and every
    repayment's own principal/interest/penalty split, replaying all of the
    loan's remaining repayments in chronological order. Also re-posts each
    repayment's journal entry from scratch.

    Used after editing or deleting a repayment: a single payment's waterfall
    can span multiple installments, and nothing on disk records exactly which
    installment(s) it touched, so a full replay is the only way to keep the
    schedule, the repayments table, and the general ledger consistent.

    Note: admin-fee overpayment allocation is intentionally left untouched by
    this recompute (the "Unpaid" admin fee marked "Paid" from an overpayment
    is not reversed/reapplied here) - that's a rare edge case, and touching
    it risks also disturbing the admin fee that's charged and paid up-front
    at disbursement, which must never be reversed by this function.
    """
    loan_row = conn.execute("SELECT interest_method FROM loans WHERE id = ?", (loan_id,)).fetchone()
    interest_method = loan_row["interest_method"] if loan_row else None

    if interest_method == "interest_only_balloon":
        # Regenerate the schedule back to its pristine, no-payments-yet shape
        # (fixed interest_due each period off the full principal, balloon on
        # the last) before replaying. Just zeroing paid columns wouldn't be
        # enough here, because interest_due itself may already be sitting at
        # whatever a *previous* set of repayment amounts had reduced it to.
        generate_amortisation_schedule(conn, loan_id)
    else:
        conn.execute(
            "UPDATE repayment_schedule SET principal_paid = 0, interest_paid = 0, penalty_paid = 0, "
            "status = CASE WHEN due_date < date('now') THEN 'Overdue' ELSE 'Pending' END "
            "WHERE loan_id = ?", (loan_id,)
        )

    repayments = conn.execute(
        "SELECT * FROM repayments WHERE loan_id = ? ORDER BY payment_date, id", (loan_id,)
    ).fetchall()

    for rep in repayments:
        _delete_journal_entries(conn, "repayment", rep["id"])

        principal_paid_total, interest_paid_total, penalty_paid_total, remaining = _allocate_payment(
            conn, loan_id, rep["amount"], interest_method, payment_date=rep["payment_date"]
        )
        if interest_method == "interest_only_balloon":
            # Re-derive every later period's interest (and the balloon) from
            # the balance as it stands right after *this* historical
            # repayment, before replaying the next one in order.
            recalculate_interest_only_balloon_schedule(conn, loan_id)

        conn.execute(
            "UPDATE repayments SET principal_paid=?, interest_paid=?, penalty_paid=? WHERE id=?",
            (round_cents(principal_paid_total), round_cents(interest_paid_total), round_cents(penalty_paid_total), rep["id"]),
        )
        rep_row = conn.execute("SELECT * FROM repayments WHERE id = ?", (rep["id"],)).fetchone()
        accounting.post_repayment(conn, rep_row, user_id)

    # A deleted/reduced repayment can un-settle a loan that was auto-closed;
    # conversely an edited/increased one could newly settle it.
    bal = outstanding_balance(conn, loan_id)
    loan = conn.execute("SELECT status FROM loans WHERE id = ?", (loan_id,)).fetchone()
    if loan:
        if bal["total"] <= 0 and loan["status"] == "Active":
            conn.execute("UPDATE loans SET status='Closed' WHERE id = ?", (loan_id,))
        elif bal["total"] > 0 and loan["status"] == "Closed":
            conn.execute("UPDATE loans SET status='Active' WHERE id = ?", (loan_id,))


def update_repayment(conn, repayment_id: int, amount: int = None, payment_date: str = None,
                      method: str = None, reference: str = None, notes: str = None, user_id=None):
    rep = conn.execute("SELECT * FROM repayments WHERE id = ?", (repayment_id,)).fetchone()
    if rep is None:
        raise ValueError("Repayment not found.")
    if amount is not None and amount <= 0:
        raise ValueError("Amount must be positive.")

    fields = {}
    if amount is not None: fields["amount"] = round_cents(amount)
    if payment_date is not None: fields["payment_date"] = payment_date
    if method is not None: fields["method"] = method
    if reference is not None: fields["reference"] = reference
    if notes is not None: fields["notes"] = notes
    if fields:
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        conn.execute(f"UPDATE repayments SET {set_clause} WHERE id = ?", list(fields.values()) + [repayment_id])

    _recompute_loan_repayments(conn, rep["loan_id"], user_id=user_id)
    conn.commit()


def delete_repayment(conn, repayment_id: int, user_id=None):
    rep = conn.execute("SELECT * FROM repayments WHERE id = ?", (repayment_id,)).fetchone()
    if rep is None:
        raise ValueError("Repayment not found.")
    loan_id = rep["loan_id"]
    _delete_journal_entries(conn, "repayment", repayment_id)
    conn.execute("DELETE FROM repayments WHERE id = ?", (repayment_id,))
    _recompute_loan_repayments(conn, loan_id, user_id=user_id)
    conn.commit()


def record_repayment(conn, loan_id: int, amount: int, payment_date: str = None,
                      method: str = "Cash", reference: str = None, notes: str = None,
                      user_id=None) -> int:
    """
    Allocates the payment across outstanding installments using the waterfall:
    Penalty -> Interest -> Principal, oldest installment first. Any admin fee
    balance owed on the loan is settled last from the remainder, if any.
    """
    payment_date = payment_date or date.today().isoformat()

    loan_row = conn.execute("SELECT interest_method FROM loans WHERE id = ?", (loan_id,)).fetchone()
    if loan_row is None:
        raise ValueError("Loan not found.")
    interest_method = loan_row["interest_method"]

    principal_paid_total, interest_paid_total, penalty_paid_total, remaining = _allocate_payment(
        conn, loan_id, amount, interest_method, payment_date=payment_date
    )

    if interest_method == "interest_only_balloon":
        # Re-derive every remaining period's interest (and the balloon) from
        # the balance as it stands right after this payment - this is what
        # makes an overpayment actually lower future interest.
        recalculate_interest_only_balloon_schedule(conn, loan_id)

    # Any leftover after clearing the whole schedule is treated as an overpayment
    # sitting against admin/rollover fees owed, otherwise left as unapplied credit
    # (rare - flagged in notes). Admin and Rollover fees are tracked in separate
    # columns since they post to different income accounts.
    admin_fee_paid_total = 0
    rollover_fee_paid_total = 0
    if remaining > 0:
        unpaid_fees = conn.execute(
            "SELECT * FROM fees WHERE loan_id = ? AND fee_type IN ('Admin', 'Rollover') "
            "AND status='Unpaid' ORDER BY date_charged, id",
            (loan_id,),
        ).fetchall()
        for fee in unpaid_fees:
            if remaining <= 0:
                break
            pay = min(remaining, fee["amount"])
            conn.execute("UPDATE fees SET status='Paid' WHERE id = ?", (fee["id"],))
            if fee["fee_type"] == "Admin":
                admin_fee_paid_total += pay
            else:
                rollover_fee_paid_total += pay
            remaining = round_cents(remaining - pay)

    cur = conn.execute(
        """INSERT INTO repayments
           (loan_id, payment_date, amount, principal_paid, interest_paid, penalty_paid,
            admin_fee_paid, rollover_fee_paid, method, reference, received_by, notes)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (loan_id, payment_date, amount, principal_paid_total, interest_paid_total,
         penalty_paid_total, admin_fee_paid_total, rollover_fee_paid_total, method, reference, user_id,
         notes if remaining <= 0 else f"{notes or ''} (Unapplied overpayment: {fmt(remaining)})".strip()),
    )
    repayment_id = cur.lastrowid
    rep_row = conn.execute("SELECT * FROM repayments WHERE id = ?", (repayment_id,)).fetchone()
    accounting.post_repayment(conn, rep_row, user_id)

    close_loan_if_settled(conn, loan_id)
    conn.commit()
    return repayment_id


def list_repayments(conn, loan_id: int = None, date_from=None, date_to=None):
    query = """SELECT r.*, l.loan_no, c.first_name, c.last_name, c.client_no
               FROM repayments r
               JOIN loans l ON l.id = r.loan_id
               JOIN clients c ON c.id = l.client_id
               WHERE 1=1"""
    params = []
    if loan_id:
        query += " AND r.loan_id = ?"
        params.append(loan_id)
    if date_from:
        query += " AND r.payment_date >= ?"
        params.append(date_from)
    if date_to:
        query += " AND r.payment_date <= ?"
        params.append(date_to)
    query += " ORDER BY r.payment_date DESC, r.id DESC"
    return conn.execute(query, params).fetchall()


def loan_statement(conn, loan_id: int):
    """Full chronological statement for a single loan: disbursement, all charges and payments."""
    loan = conn.execute(
        """SELECT l.*, c.first_name, c.last_name, c.client_no, c.location, c.phone FROM loans l
           JOIN clients c ON c.id = l.client_id WHERE l.id = ?""", (loan_id,)
    ).fetchone()
    schedule = conn.execute(
        "SELECT * FROM repayment_schedule WHERE loan_id = ? ORDER BY installment_no", (loan_id,)
    ).fetchall()
    payments = list_repayments(conn, loan_id=loan_id)
    disbursements = conn.execute(
        "SELECT * FROM disbursements WHERE loan_id = ? ORDER BY disbursement_date", (loan_id,)
    ).fetchall()
    fees = conn.execute("SELECT * FROM fees WHERE loan_id = ? ORDER BY date_charged", (loan_id,)).fetchall()
    return {
        "loan": loan, "schedule": schedule, "payments": payments,
        "disbursements": disbursements, "fees": fees,
    }


def loan_statement_ledger(conn, loan_id: int):
    """
    A single, unified chronological ledger for one loan - opening balance, each installment's
    interest (and penalty, if charged) as it comes due, and each repayment received - with a
    running balance. This replaces showing the schedule and payments as two separate tables.
    """
    loan = conn.execute(
        """SELECT l.*, c.first_name, c.last_name, c.client_no, c.location, c.phone FROM loans l
           JOIN clients c ON c.id = l.client_id WHERE l.id = ?""", (loan_id,)
    ).fetchone()
    if loan is None:
        return {"loan": None, "rows": []}

    schedule = conn.execute(
        "SELECT * FROM repayment_schedule WHERE loan_id = ? ORDER BY installment_no", (loan_id,)
    ).fetchall()
    payments = list_repayments(conn, loan_id=loan_id)

    events = []
    if loan["disbursement_date"]:
        events.append({
            "sort_key": (loan["disbursement_date"], 0, 0),
            "date": loan["disbursement_date"], "description": "Loan Disbursed (Opening Balance)",
            "charge": loan["principal"], "payment": 0,
        })
    for s in schedule:
        if s["interest_due"]:
            events.append({
                "sort_key": (s["due_date"], 1, s["installment_no"]),
                "date": s["due_date"], "description": f"Installment {s['installment_no']} Interest Due",
                "charge": s["interest_due"], "payment": 0,
            })
        if s["penalty_charged"]:
            events.append({
                "sort_key": (s["due_date"], 2, s["installment_no"]),
                "date": s["due_date"], "description": f"Installment {s['installment_no']} Penalty Charged",
                "charge": s["penalty_charged"], "payment": 0,
            })
    for p in payments:
        events.append({
            "sort_key": (p["payment_date"], 3, p["id"]),
            "date": p["payment_date"], "description": f"Payment Received ({p['method']})",
            "charge": 0, "payment": p["amount"],
        })

    events.sort(key=lambda e: e["sort_key"])

    rows = []
    balance = 0
    for e in events:
        balance = round_cents(balance + e["charge"] - e["payment"])
        rows.append({
            "date": e["date"], "description": e["description"],
            "charge": round_cents(e["charge"]), "payment": round_cents(e["payment"]),
            "balance": balance,
        })
    return {"loan": loan, "rows": rows}
