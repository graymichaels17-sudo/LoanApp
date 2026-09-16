import calendar
import sqlite3
from datetime import date, timedelta
from ..database import next_sequence_number
from ..money import round_cents


def generate_loan_no(conn, is_rollover: bool = False):
    """
    Generate a new loan number. Normal loans get LN-00001, LN-00002, ...
    Rollover-originated loans get their own RN-00001, RN-00002, ... series,
    so they're visually distinguishable from regular new loans at a glance.
    Each series is numbered independently off its own existing rows, not
    off the loans table's row id, so neither series has gaps because of
    the other one.
    """
    prefix = "RN" if is_rollover else "LN"
    row = conn.execute(
        "SELECT MAX(CAST(SUBSTR(loan_no, 4) AS INTEGER)) FROM loans WHERE loan_no LIKE ?",
        (f"{prefix}-%",),
    ).fetchone()
    next_id = (row[0] + 1) if row and row[0] else 1
    return f"{prefix}-{next_id:05d}"


def is_new_client(conn, client_id: int) -> bool:
    """
    True if this client has never had a loan of any kind (pending, active,
    closed, rejected, etc.) before now. Used to decide whether the New Loan
    form should auto-apply a loan product's new-client application fee -
    once a client has any loan on file, they're no longer "new".
    """
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM loans WHERE client_id = ?", (client_id,)
    ).fetchone()
    return row["c"] == 0


def _add_months(d: date, months: int) -> date:
    total_month_index = d.month - 1 + months
    year = d.year + total_month_index // 12
    month = total_month_index % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _add_period(d: date, frequency: str, n: int = 1) -> date:
    if frequency == "weekly":
        return d + timedelta(weeks=n)
    if frequency == "biweekly":
        return d + timedelta(weeks=2 * n)
    return _add_months(d, n)


def next_due_date(disbursement_date: str, frequency: str) -> str:
    """Public helper: first installment due date, one period after disbursement."""
    d = date.fromisoformat(disbursement_date)
    return _add_period(d, frequency, 1).isoformat()


def _monthly_rate(interest_rate: float, rate_period: str, term_months: int) -> float:
    """Normalize whatever rate_period was configured into an effective per-installment rate (decimal)."""
    r = interest_rate / 100.0
    if rate_period == "year":
        return r / 12.0
    if rate_period == "loan_term":
        return r  # rate already applies to the whole term as a single lump percentage
    return r  # 'month' - rate already per period


def build_schedule(principal: float, interest_rate: float, interest_method: str,
                    rate_period: str, term_months: int, first_due_date: str,
                    frequency: str = "monthly",
                    phase2_term_months: int = None, phase2_frequency: str = None):
    """Returns a list of dicts: installment_no, due_date, principal_due, interest_due, total_due."""
    schedule = []
    start = date.fromisoformat(first_due_date)

    if interest_method == "flat":
        if rate_period == "loan_term":
            total_interest = principal * (interest_rate / 100.0)
        elif rate_period == "year":
            total_interest = principal * (interest_rate / 100.0) * (term_months / 12.0)
        else:  # per month flat on original principal
            total_interest = principal * (interest_rate / 100.0) * term_months
        principal_per_period = round_cents(principal / term_months)
        interest_per_period = round_cents(total_interest / term_months)
        running_principal = 0
        running_interest = 0
        for i in range(1, term_months + 1):
            due_date = _add_period(start, frequency, i - 1)
            p = principal_per_period
            it = interest_per_period
            if i == term_months:  # mop up rounding on the final installment
                p = round_cents(principal - running_principal)
                it = round_cents(total_interest - running_interest)
            running_principal += p
            running_interest += it
            schedule.append({
                "installment_no": i, "due_date": due_date.isoformat(),
                "principal_due": p, "interest_due": it, "total_due": round_cents(p + it),
            })
    elif interest_method == "interest_only_balloon":
        # Every period: interest only, charged on the outstanding principal balance.
        # Principal is due in full only on the final period (the "balloon").
        # If the person overpays in an earlier period, the excess reduces the
        # balance and lowers interest in later periods - see
        # recalculate_interest_only_balloon_schedule(), which re-derives this
        # same shape from the current outstanding balance after each repayment.
        monthly_rate = interest_rate / 100.0
        balance = principal
        for i in range(1, term_months + 1):
            due_date = _add_period(start, frequency, i - 1)
            interest_this = round_cents(balance * monthly_rate)
            principal_this = balance if i == term_months else 0
            schedule.append({
                "installment_no": i, "due_date": due_date.isoformat(),
                "principal_due": round_cents(principal_this), "interest_due": interest_this,
                "total_due": round_cents(principal_this + interest_this),
            })
    elif interest_method == "interest_only_then_flat":
        # Two-phase product: Phase 1 is interest-only (principal fully
        # deferred) for `term_months` periods at `frequency`. Once phase 1
        # completes, the *entire, untouched* principal is "reinvested" -
        # re-amortised flat, at the same interest_rate, over its own
        # `phase2_term_months` periods at `phase2_frequency`.
        # e.g. $5,000 @ 20%: 1 month interest-only ($1,000), then the
        # $5,000 capital re-amortised at 20% over 6 weeks biweekly
        # (3 installments of $1,666.67 principal + $333.33 interest = $2,000).
        # Both phases price their interest the same way flat/loan_term does
        # (principal x rate%, once, for the whole phase) since a phase's
        # rate is a lump percentage over that phase's term, not a per-period
        # rate - that's what makes the "$1,000 then $2,000/installment" math
        # in the product spec come out exactly.
        if not phase2_term_months or phase2_term_months <= 0:
            raise ValueError("phase2_term_months is required for interest_only_then_flat loans")
        phase2_frequency = phase2_frequency or frequency

        # ---- Phase 1: interest-only, principal deferred ----
        phase1_total_interest = round_cents(principal * (interest_rate / 100.0))
        phase1_interest_per_period = round_cents(phase1_total_interest / term_months)
        running_interest = 0
        for i in range(1, term_months + 1):
            due_date = _add_period(start, frequency, i - 1)
            it = phase1_interest_per_period
            if i == term_months:  # mop up rounding on the last phase-1 installment
                it = round_cents(phase1_total_interest - running_interest)
            running_interest += it
            schedule.append({
                "installment_no": i, "due_date": due_date.isoformat(),
                "principal_due": 0, "interest_due": it, "total_due": round_cents(it),
                "phase": 1,
            })

        # ---- Phase 2: full principal re-amortised flat over its own term ----
        phase2_total_interest = round_cents(principal * (interest_rate / 100.0))
        phase2_principal_per_period = round_cents(principal / phase2_term_months)
        phase2_interest_per_period = round_cents(phase2_total_interest / phase2_term_months)
        phase2_start = date.fromisoformat(schedule[-1]["due_date"])
        running_principal = 0
        running_interest2 = 0
        for i in range(1, phase2_term_months + 1):
            due_date = _add_period(phase2_start, phase2_frequency, i)
            p = phase2_principal_per_period
            it = phase2_interest_per_period
            if i == phase2_term_months:  # mop up rounding on the final installment
                p = round_cents(principal - running_principal)
                it = round_cents(phase2_total_interest - running_interest2)
            running_principal += p
            running_interest2 += it
            schedule.append({
                "installment_no": term_months + i, "due_date": due_date.isoformat(),
                "principal_due": p, "interest_due": it, "total_due": round_cents(p + it),
                "phase": 2,
            })
    else:  # reducing_balance - equal installment (amortizing / EMI style)
        r = _monthly_rate(interest_rate, rate_period, term_months)
        if r == 0:
            emi = round_cents(principal / term_months)
        else:
            emi = principal * r * (1 + r) ** term_months / ((1 + r) ** term_months - 1)
        balance = principal
        running_principal = 0
        for i in range(1, term_months + 1):
            due_date = _add_period(start, frequency, i - 1)
            interest_component = round_cents(balance * r)
            principal_component = round_cents(emi - interest_component)
            if i == term_months:  # final installment clears exact remaining balance
                principal_component = round_cents(principal - running_principal)
            balance = round_cents(balance - principal_component)
            running_principal += principal_component
            schedule.append({
                "installment_no": i, "due_date": due_date.isoformat(),
                "principal_due": principal_component, "interest_due": interest_component,
                "total_due": round_cents(principal_component + interest_component),
            })
    return schedule


def create_loan(conn, data, user_id: int = None):
    from datetime import date

    # Generate loan number - rollover-originated loans (identified by
    # parent_loan_id being set) get an RN- series instead of LN-, so they're
    # visually distinguishable in loan lists, statements, and reports.
    is_rollover = bool(data.get("parent_loan_id"))
    loan_no = generate_loan_no(conn, is_rollover=is_rollover)

    allowed_fields = [
        "client_id", "product_id", "principal", "interest_rate", "interest_method", "rate_period",
        "term_months", "repayment_frequency", "admin_fee", "purpose",
        "collateral", "disbursement_date", "parent_loan_id",
        "phase2_term_months", "phase2_frequency",
    ]
    fields = ["loan_no"]   # <-- include loan_no
    placeholders = ["?"]
    values = [loan_no]

    for key in allowed_fields:
        if key in data and data[key] is not None:
            fields.append(key)
            placeholders.append("?")
            values.append(data[key])

    fields.append("application_date")
    placeholders.append("?")
    values.append(date.today().isoformat())

    fields.append("created_by")
    placeholders.append("?")
    values.append(user_id)

    fields.append("status")
    placeholders.append("?")
    values.append("Pending")

    fields.append("approval_status")
    placeholders.append("?")
    values.append("Pending")

    cur = conn.execute(
        f"INSERT INTO loans ({', '.join(fields)}) VALUES ({', '.join(placeholders)})",
        values
    )
    conn.commit()
    return cur.lastrowid


def set_approval_status(conn, loan_id: int, new_status: str, approved_by=None):
    """Approve or decline a Pending loan application. new_status: 'Approved' or 'Declined'."""
    if new_status not in ("Approved", "Declined"):
        raise ValueError("new_status must be 'Approved' or 'Declined'.")
    loan = conn.execute("SELECT * FROM loans WHERE id = ?", (loan_id,)).fetchone()
    if loan is None:
        raise ValueError("Loan not found.")
    if loan["approval_status"] != "Pending":
        raise ValueError(f"Loan {loan['loan_no']} has already been {loan['approval_status'].lower()}.")
    from datetime import datetime
    conn.execute(
        "UPDATE loans SET approval_status = ?, approved_by = ?, approved_at = ? WHERE id = ?",
        (new_status, approved_by, datetime.now().isoformat(timespec="seconds"), loan_id),
    )
    if new_status == "Declined":
        conn.execute("UPDATE loans SET status = 'Rejected' WHERE id = ?", (loan_id,))
    conn.commit()


def update_pending_loan(conn, loan_id: int, data: dict):
    """Edit terms of a loan that has not yet been approved/disbursed."""
    loan = conn.execute("SELECT * FROM loans WHERE id = ?", (loan_id,)).fetchone()
    if loan is None:
        raise ValueError("Loan not found.")
    if loan["status"] != "Pending" or loan["approval_status"] != "Pending":
        raise ValueError("Only a loan that is still Pending approval can be edited.")
    fields = ["principal", "interest_rate", "interest_method", "rate_period", "term_months",
              "repayment_frequency", "admin_fee", "purpose", "collateral",
              "phase2_term_months", "phase2_frequency"]
    set_clause = ", ".join(f"{f} = ?" for f in fields if f in data)
    values = [data[f] for f in fields if f in data]
    if not set_clause:
        return
    values.append(loan_id)
    conn.execute(f"UPDATE loans SET {set_clause} WHERE id = ?", values)
    conn.commit()


def delete_loan(conn, loan_id: int):
    """Deletes a loan that has never been disbursed (no accounting entries exist for it yet)."""
    loan = conn.execute("SELECT * FROM loans WHERE id = ?", (loan_id,)).fetchone()
    if loan is None:
        raise ValueError("Loan not found.")
    if loan["status"] != "Pending":
        raise ValueError(
            f"Cannot delete loan {loan['loan_no']} - it has already been disbursed/actioned "
            f"(status={loan['status']}). Write it off or close it instead."
        )

    # A Pending loan can still be referenced elsewhere - most commonly it's
    # the "new" loan a rollover created (rollovers.new_loan_id). A still-
    # Pending rollover request should be Declined from the Approvals tab
    # instead (that also puts the new loan into Rejected state cleanly); a
    # Completed one needs reverse_rollover(), since that also restores the
    # original loan back to Active. Check for that specifically so we can
    # point to the right fix instead of a bare FK error.
    rollover_row = conn.execute(
        "SELECT id, status FROM rollovers WHERE new_loan_id = ?", (loan_id,)
    ).fetchone()
    if rollover_row:
        if rollover_row["status"] == "Pending":
            raise ValueError(
                f"Cannot delete loan {loan['loan_no']} - it's a pending rollover request "
                f"(rollover id={rollover_row['id']}). Decline it from the Approvals tab instead."
            )
        raise ValueError(
            f"Cannot delete loan {loan['loan_no']} - it was created by a rollover "
            f"(rollover id={rollover_row['id']}). Use 'Reverse Rollover' instead, which "
            f"will also restore the original loan back to Active."
        )

    try:
        conn.execute("DELETE FROM loans WHERE id = ?", (loan_id,))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.rollback()
        # Something else still references this loan - find what, so the
        # error is actionable instead of a bare "FOREIGN KEY constraint failed".
        blockers = []
        for label, query in [
            ("repayment schedule rows", "SELECT COUNT(*) c FROM repayment_schedule WHERE loan_id = ?"),
            ("fees", "SELECT COUNT(*) c FROM fees WHERE loan_id = ?"),
            ("disbursements", "SELECT COUNT(*) c FROM disbursements WHERE loan_id = ?"),
            ("repayments", "SELECT COUNT(*) c FROM repayments WHERE loan_id = ?"),
            ("rollovers (as original loan)", "SELECT COUNT(*) c FROM rollovers WHERE original_loan_id = ?"),
            ("other loans referencing it as parent", "SELECT COUNT(*) c FROM loans WHERE parent_loan_id = ?"),
        ]:
            count = conn.execute(query, (loan_id,)).fetchone()["c"]
            if count:
                blockers.append(f"{count} {label}")
        detail = "; ".join(blockers) if blockers else "an unidentified related record"
        raise ValueError(
            f"Cannot delete loan {loan['loan_no']} - it is still referenced by: {detail}. "
            f"Remove or reassign those first."
        )


def activate_and_schedule(conn, loan_id: int, disbursement_date: str, first_due_date: str):
    """Marks a loan Active and (re)generates its repayment schedule. Call once, at disbursement."""
    loan = conn.execute("SELECT * FROM loans WHERE id = ?", (loan_id,)).fetchone()
    if loan is None:
        raise ValueError("Loan not found.")
    schedule = build_schedule(
        principal=loan["principal"], interest_rate=loan["interest_rate"],
        interest_method=loan["interest_method"],
        rate_period=loan["rate_period"] if "rate_period" in loan.keys() else "month",
        term_months=loan["term_months"], first_due_date=first_due_date,
        frequency=loan["repayment_frequency"],
        phase2_term_months=loan["phase2_term_months"] if "phase2_term_months" in loan.keys() else None,
        phase2_frequency=loan["phase2_frequency"] if "phase2_frequency" in loan.keys() else None,
    )
    conn.execute("DELETE FROM repayment_schedule WHERE loan_id = ?", (loan_id,))
    for row in schedule:
        conn.execute(
            """INSERT INTO repayment_schedule
               (loan_id, installment_no, due_date, principal_due, interest_due, total_due, 
                principal_paid, interest_paid, penalty_charged, penalty_paid, status)
               VALUES (?,?,?,?,?,?, 0, 0, 0, 0, 'Pending')""",
            (loan_id, row["installment_no"], row["due_date"], row["principal_due"],
             row["interest_due"], row["total_due"]),
        )


    maturity = schedule[-1]["due_date"] if schedule else first_due_date
    conn.execute(
        "UPDATE loans SET status='Active', disbursement_date=?, first_due_date=?, maturity_date=? WHERE id=?",
        (disbursement_date, first_due_date, maturity, loan_id),
    )
    conn.commit()


def get_loan(conn, loan_id: int):
    return conn.execute(
        """SELECT l.*, c.first_name, c.last_name, c.client_no, c.location, c.phone
           FROM loans l JOIN clients c ON c.id = l.client_id WHERE l.id = ?""",
        (loan_id,),
    ).fetchone()


def list_loans(conn, status=None, approval_status=None, only_with_balance: bool = False):
    """
    Return all loans, optionally filtered by loan status and/or approval status.
    Each row includes loan fields plus client details: first_name, last_name,
    location, phone, and client_no.

    only_with_balance: if True, also excludes loans whose outstanding balance
    (principal + interest + penalty remaining across the schedule) is at or
    near zero - e.g. a loan stuck at status='Active' that's actually fully
    paid off. Defaults to False so existing callers keep their current
    behaviour; pass True for pickers where selecting a fully-paid loan
    wouldn't make sense (rollovers, bad debt write-off, schedule viewer).
    """
    query = """
        SELECT
            l.*,
            c.first_name,
            c.last_name,
            c.location,
            c.phone,
            c.client_no
        FROM loans l
        JOIN clients c ON c.id = l.client_id
        WHERE 1=1
    """
    params = []
    if status is not None:
        query += " AND l.status = ?"
        params.append(status)
    if approval_status is not None:
        query += " AND l.approval_status = ?"
        params.append(approval_status)
    if only_with_balance:
        query += """ AND (
            SELECT COALESCE(SUM(
                (rs.principal_due - rs.principal_paid) +
                (rs.interest_due - rs.interest_paid) +
                (rs.penalty_charged - rs.penalty_paid)
            ), 0)
            FROM repayment_schedule rs WHERE rs.loan_id = l.id
        ) > 0"""
    query += " ORDER BY l.id DESC"
    return conn.execute(query, params).fetchall()


def get_schedule(conn, loan_id: int):
    return conn.execute(
        "SELECT * FROM repayment_schedule WHERE loan_id = ? ORDER BY installment_no", (loan_id,)
    ).fetchall()


def outstanding_balance(conn, loan_id: int) -> dict:
    row = conn.execute(
        """SELECT COALESCE(SUM(COALESCE(principal_due, 0) - COALESCE(principal_paid, 0)), 0) as principal,
                  COALESCE(SUM(COALESCE(interest_due, 0) - COALESCE(interest_paid, 0)), 0) as interest,
                  COALESCE(SUM(COALESCE(penalty_charged, 0) - COALESCE(penalty_paid, 0)), 0) as penalty
           FROM repayment_schedule WHERE loan_id = ?""",
        (loan_id,),
    ).fetchone()
    return {
        "principal": round_cents(row["principal"]),
        "interest": round_cents(row["interest"]),
        "penalty": round_cents(row["penalty"]),
        "total": round_cents(row["principal"] + row["interest"] + row["penalty"]),
    }


def recalculate_interest_only_balloon_schedule(conn, loan_id: int):
    """
    Call this immediately after recording a repayment against a loan whose
    interest_method is 'interest_only_balloon'. It re-derives interest_due
    (and the final balloon's principal_due) for every installment that isn't
    already fully Paid, based on the outstanding balance actually remaining
    after real payments so far - so an early overpayment correctly lowers
    interest on every period after it. Installments already fully paid are
    left untouched.

    No-op for loans using any other interest_method.
    """
    loan = conn.execute("SELECT * FROM loans WHERE id = ?", (loan_id,)).fetchone()
    if loan is None:
        raise ValueError("Loan not found.")
    if loan["interest_method"] != "interest_only_balloon":
        return

    monthly_rate = loan["interest_rate"] / 100.0
    rows = conn.execute(
        "SELECT * FROM repayment_schedule WHERE loan_id = ? ORDER BY installment_no",
        (loan_id,),
    ).fetchall()
    if not rows:
        return

    last_installment_no = rows[-1]["installment_no"]
    balance = loan["principal"]

    for row in rows:
        is_last = row["installment_no"] == last_installment_no

        if row["status"] == "Paid":
            # Interest is frozen at whatever it was when this row got paid
            # off - don't rewrite that history. But a non-final row's
            # principal_due still needs the same correction as below: if an
            # early curtailment was recorded on it, principal_due must match
            # principal_paid (remainder 0) rather than staying pinned at 0 -
            # otherwise that same curtailment amount is double-subtracted
            # everywhere the schedule's principal_due minus principal_paid
            # gets summed, understating the true outstanding balance. This
            # row is skipped by every later pass of this function (since it
            # stays "Paid"), so if it isn't corrected here, right now, it
            # never gets corrected at all.
            if not is_last and round_cents(row["principal_paid"]) != round_cents(row["principal_due"]):
                corrected_principal_due = round_cents(row["principal_paid"])
                conn.execute(
                    "UPDATE repayment_schedule SET principal_due = ?, total_due = ? WHERE id = ?",
                    (corrected_principal_due, round_cents(corrected_principal_due + row["interest_due"]), row["id"]),
                )
            balance -= row["principal_paid"]
            continue

        # Only the final (balloon) row genuinely carries outstanding
        # principal. A non-final row can still have principal_paid > 0 - an
        # early curtailment recorded against that period - and that amount
        # is already reflected in the reduced "balance" (and therefore the
        # reduced balloon principal_due) carried forward. Leaving this row's
        # principal_due pinned at 0 while principal_paid sits above it made
        # every outstanding-balance total across the whole schedule
        # (principal_due - principal_paid, summed) subtract that same
        # curtailment a SECOND time, understating what's actually still
        # owed by the total amount ever curtailed early. Setting this row's
        # principal_due to match what was actually paid on it keeps its own
        # remainder at exactly 0, so the curtailment is only ever accounted
        # for once - on the balloon row where the balance reduction lives.
        # Interest for this row is charged on the balance net of any
        # curtailment already recorded against THIS row - not the balance
        # from before that curtailment. Phase 2 of the repayment waterfall
        # assigns early overpayments to the first still-open installment, so
        # that curtailment has already been received by the time this row's
        # interest is (re)computed; charging interest as if it hadn't
        # happened yet pushed the benefit one installment later than it
        # actually occurred (e.g. a curtailment recorded against "this"
        # period only ever showed up lowering "next" period's interest).
        principal_due = round_cents(balance) if is_last else round_cents(row["principal_paid"])
        interest_due = round_cents((balance - row["principal_paid"]) * monthly_rate)
        # Never recompute interest_due below what's already been recorded as
        # interest_paid on this row. Without this floor, a big curtailment
        # arriving after a partial payment shrinks the balance (and so this
        # freshly-recomputed interest_due) below the interest_paid already
        # locked in from that earlier partial payment - producing a negative
        # "interest remaining" on this row that then poisons
        # outstanding_balance(), rollover arrears calculations, etc.
        interest_due = max(interest_due, row["interest_paid"])
        total_due = round_cents(principal_due + interest_due)

        # If the balance has already hit zero (an earlier curtailment paid
        # the loan off early), there's nothing left owed on this period -
        # close it out rather than leaving a live $0 installment sitting as
        # Pending/Overdue.
        new_status = row["status"]
        if total_due <= 0 and row["interest_paid"] >= interest_due:
            new_status = "Paid"

        conn.execute(
            "UPDATE repayment_schedule SET interest_due = ?, principal_due = ?, total_due = ?, status = ? "
            "WHERE id = ?",
            (interest_due, principal_due, total_due, new_status, row["id"]),
        )
        # Any principal already paid on this not-yet-fully-paid row (i.e. an
        # overpayment beyond the interest due) still reduces the balance
        # carried into the next period.
        balance -= row["principal_paid"]

    conn.commit()


def close_loan_if_settled(conn, loan_id: int):
    bal = outstanding_balance(conn, loan_id)
    if bal["total"] <= 0:
        conn.execute("UPDATE loans SET status='Closed' WHERE id = ? AND status = 'Active'", (loan_id,))
        conn.commit()
        return True
    return False

def get_loan_cleared_date(conn, loan_id: int):
    """Fetches the date of the final repayment for a settled loan."""
    row = conn.execute(
        "SELECT MAX(payment_date) as cleared_date FROM repayments WHERE loan_id = ?", 
        (loan_id,)
    ).fetchone()
    
    return row["cleared_date"] if row and row["cleared_date"] else "N/A"



def get_amortisation_schedule(conn, loan_id: int) -> list:
    """
    Returns the amortisation schedule with opening balance and running balance for each installment.
    Opening and running balances include both principal and interest components.
    Columns: installment_no, due_date, opening_balance, principal_due, interest_due, 
             principal_paid, interest_paid, received, running_balance
    """
    schedule = conn.execute(
        """SELECT installment_no, due_date, principal_due, interest_due, 
                  principal_paid, interest_paid, penalty_charged, penalty_paid, status
           FROM repayment_schedule 
           WHERE loan_id = ? 
           ORDER BY installment_no""",
        (loan_id,)
    ).fetchall()
    
    if not schedule:
        return []
    
    loan = conn.execute("SELECT principal FROM loans WHERE id = ?", (loan_id,)).fetchone()
    if not loan:
        return []
    
    result = []
    
    # OPTIMIZATION: Calculate total starting liability once.
    # We include penalties here for mathematical completeness, as they increase the total debt.
    total_principal_due = sum(r["principal_due"] for r in schedule)
    total_interest_due = sum(r["interest_due"] for r in schedule)
    total_penalties = sum(r["penalty_charged"] for r in schedule)
    
    # The starting balance for Installment 1 is the total amount expected over the life of the loan
    opening_balance = round_cents(total_principal_due + total_interest_due + total_penalties)
    
    for row in schedule:
        # Amount received in this period (adding penalty_paid for accurate balance reduction)
        received = round_cents(row["principal_paid"] + row["interest_paid"] + row["penalty_paid"])
        
        # Running balance: what was owed minus what was just received
        running_balance = round_cents(opening_balance - received)
        
        result.append({
            "installment_no": row["installment_no"],
            "due_date": row["due_date"],
            "opening_balance": opening_balance,
            "principal_due": row["principal_due"],
            "interest_due": row["interest_due"],
            "principal_paid": row["principal_paid"],
            "interest_paid": row["interest_paid"],
            "received": received,
            "running_balance": running_balance,
            "status": row["status"],
        })
        
        # The running balance at the end of this period becomes the opening balance for the next
        # This guarantees that underpayments (arrears) naturally roll forward.
        opening_balance = running_balance
    
    return result

def get_loan_by_no(conn, loan_no: str):
    """Used by bulk repayment upload to resolve a CSV row's loan_no to a loan."""
    return conn.execute(
        """SELECT l.*, c.first_name, c.last_name, c.client_no
           FROM loans l JOIN clients c ON c.id = l.client_id WHERE l.loan_no = ?""",
        (loan_no.strip(),),
    ).fetchone()

def rebuild_schedule_and_reapply_repayments(conn, loan_id: int, new_data: dict):
    loan = conn.execute("SELECT * FROM loans WHERE id = ?", (loan_id,)).fetchone()
    if not loan:
        raise ValueError("Loan not found")

    allowed = {"principal", "interest_rate", "interest_method", "rate_period", "term_months",
               "repayment_frequency", "admin_fee", "disbursement_date",
               "phase2_term_months", "phase2_frequency"}
    update_fields = []
    update_values = []
    for key, value in new_data.items():
        if key in allowed:
            update_fields.append(f"{key} = ?")
            update_values.append(value)
    if update_fields:
        update_values.append(loan_id)
        conn.execute(
            f"UPDATE loans SET {', '.join(update_fields)} WHERE id = ?",
            update_values
        )
        conn.commit()
        loan = conn.execute("SELECT * FROM loans WHERE id = ?", (loan_id,)).fetchone()

        # The disbursements table (what the Disbursement Report and the
        # linked GL journal entry actually read from) is a separate record
        # of what happened at disbursement time - it does NOT auto-follow
        # loans.principal/disbursement_date. Without this, editing a
        # disbursed loan's principal or disbursement date leaves the
        # Disbursement Report (and the Dr 1100/Cr 1000 journal entry backing
        # it) permanently showing the old, pre-edit figures.
        if "principal" in new_data or "disbursement_date" in new_data:
            disb = conn.execute(
                "SELECT * FROM disbursements WHERE loan_id = ?", (loan_id,)
            ).fetchone()
            if disb:
                conn.execute(
                    "UPDATE disbursements SET amount = ?, disbursement_date = ? WHERE id = ?",
                    (loan["principal"], loan["disbursement_date"], disb["id"]),
                )
                je = conn.execute(
                    "SELECT id FROM journal_entries WHERE source_type = 'disbursement' AND source_id = ?",
                    (disb["id"],),
                ).fetchone()
                if je:
                    conn.execute(
                        "UPDATE journal_entries SET entry_date = ? WHERE id = ?",
                        (loan["disbursement_date"], je["id"]),
                    )
                    # Disbursement journal lines are always exactly Dr 1100 /
                    # Cr 1000 for the disbursed amount (see
                    # accounting.post_disbursement) - rewrite whichever side
                    # is non-zero on each line to the new amount.
                    conn.execute(
                        """UPDATE journal_lines
                           SET debit = CASE WHEN debit > 0 THEN ? ELSE 0 END,
                               credit = CASE WHEN credit > 0 THEN ? ELSE 0 END
                           WHERE journal_entry_id = ?""",
                        (loan["principal"], loan["principal"], je["id"]),
                    )
                conn.commit()

    repayments = conn.execute(
        "SELECT * FROM repayments WHERE loan_id = ? ORDER BY payment_date, id",
        (loan_id,)
    ).fetchall()

    generate_amortisation_schedule(conn, loan_id)

    if loan["interest_method"] == "interest_only_balloon":
        # Replay each historical repayment through the same curtailment-aware
        # waterfall (and the same post-payment interest recalculation) used
        # for real-time repayments via record_repayment(), so replaying
        # history reproduces the same economics - an early overpayment
        # lowering every later period's interest - instead of the generic
        # waterfall below, which would just prepay future periods' interest
        # one by one and never touch principal until the final balloon row.
        from .repayments import _allocate_interest_only_balloon
        for repayment in repayments:
            _allocate_interest_only_balloon(conn, loan_id, repayment["amount"], repayment["payment_date"])
            recalculate_interest_only_balloon_schedule(conn, loan_id)
    else:
        schedule = conn.execute(
            "SELECT * FROM repayment_schedule WHERE loan_id = ? ORDER BY due_date, installment_no",
            (loan_id,)
        ).fetchall()
        # Mutable copies of each row, updated in memory alongside every DB
        # write below. The old version of this loop re-read remaining
        # amounts from this same one-time fetch on every repayment instead
        # of the running totals left by repayments replayed earlier in this
        # loop - so the 2nd, 3rd, etc. repayment always saw installment 1 as
        # still fully unpaid and re-paid its interest/principal a second
        # time, silently swallowing real payment amounts that should have
        # gone toward later, genuinely-outstanding installments. That's what
        # let interest_paid exceed interest_due on already-settled rows while
        # later overdue installments stayed uncredited - producing a negative
        # "interest accrued" total alongside arrears bigger than the actual
        # outstanding balance.
        state = [dict(row) for row in schedule]

        for repayment in repayments:
            amount = repayment["amount"]
            for row in state:
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
                    row["penalty_paid"] += pay
                    amount -= pay
                if amount > 0 and int_rem > 0:
                    pay = min(amount, int_rem)
                    row["interest_paid"] += pay
                    amount -= pay
                if amount > 0 and prin_rem > 0:
                    pay = min(amount, prin_rem)
                    row["principal_paid"] += pay
                    amount -= pay
                if (row["principal_paid"] >= row["principal_due"]
                        and row["interest_paid"] >= row["interest_due"]
                        and row["penalty_paid"] >= row["penalty_charged"]):
                    row["status"] = "Paid"
                elif row["principal_paid"] or row["interest_paid"] or row["penalty_paid"]:
                    row["status"] = "PartiallyPaid"

        # OPTIMIZATION: Prepare the updated state rows for a single batch database update
        batch_updates = [
            (row["principal_paid"], row["interest_paid"], row["penalty_paid"], row["status"], row["id"])
            for row in state
        ]

        # Execute all row updates simultaneously
        conn.executemany(
            "UPDATE repayment_schedule SET principal_paid=?, interest_paid=?, penalty_paid=?, status=? WHERE id=?",
            batch_updates
        )

    # Refresh the "capitalized at disbursement" snapshot to match the new
    # terms/schedule. Left untouched, it kept showing the OLD principal/
    # rate/term's total interest forever after an edit - the statement's
    # ledger (which uses this frozen snapshot) then permanently disagreed
    # with the live, recalculated Total Outstanding Balance.
    fresh_schedule = get_amortisation_schedule(conn, loan_id)
    capitalized_interest = round_cents(sum(s["interest_due"] for s in fresh_schedule))
    conn.execute(
        "UPDATE loans SET capitalized_interest = ? WHERE id = ?",
        (capitalized_interest, loan_id),
    )

    conn.commit()

def update_loan(conn, loan_id: int, data: dict):
    """Update non‑disbursed loan fields. Safe for pending/approved loans."""
    allowed = {"principal", "interest_rate", "interest_method", "rate_period", "term_months",
               "repayment_frequency", "admin_fee", "purpose", "collateral",
               "phase2_term_months", "phase2_frequency"}
    fields = []
    values = []
    for key, value in data.items():
        if key in allowed:
            fields.append(f"{key} = ?")
            values.append(value)
    if not fields:
        return
    values.append(loan_id)
    conn.execute(f"UPDATE loans SET {', '.join(fields)} WHERE id = ?", values)
    conn.commit()

def generate_amortisation_schedule(conn, loan_id: int):
    loan = conn.execute("SELECT * FROM loans WHERE id = ?", (loan_id,)).fetchone()
    if not loan:
        raise ValueError("Loan not found")
    if not loan["disbursement_date"]:
        raise ValueError("Loan not disbursed")

    # 1. Extract parameters 
    principal = loan["principal"]
    interest_rate = loan["interest_rate"] # Passed as raw %, build_schedule handles / 100.0
    term_months = loan["term_months"]
    freq = loan["repayment_frequency"]
    method = loan["interest_method"]
    rate_period = loan["rate_period"] if "rate_period" in loan.keys() else "month"
    disbursement_date = loan["disbursement_date"]
    
    phase2_term = loan["phase2_term_months"] if "phase2_term_months" in loan.keys() else None
    phase2_frequency = loan["phase2_frequency"] if "phase2_frequency" in loan.keys() else None

    # 2. Clear old schedule
    conn.execute("DELETE FROM repayment_schedule WHERE loan_id = ?", (loan_id,))

    # 3. Centralize ALL mathematical logic through build_schedule
    # This ensures "flat", "reducing_balance", and "interest_only" shapes 
    # match the quoting engine perfectly.
    sched = build_schedule(
        principal=principal, 
        interest_rate=interest_rate,
        interest_method=method, 
        rate_period=rate_period,
        term_months=term_months, 
        first_due_date=next_due_date(disbursement_date, freq),
        frequency=freq, 
        phase2_term_months=phase2_term, 
        phase2_frequency=phase2_frequency,
    )

    # 4. Batch insert the unified schedule to the database
    batch_data = [
        (
            loan_id, row["installment_no"], row["due_date"],
            row["principal_due"], row["interest_due"], row["total_due"]
        )
        for row in sched
    ]
    
    conn.executemany(
        """INSERT INTO repayment_schedule
           (loan_id, installment_no, due_date, principal_due, interest_due, total_due,
            principal_paid, interest_paid, penalty_charged, penalty_paid, status)
           VALUES (?,?,?,?,?,?, 0, 0, 0, 0, 'Pending')""",
        batch_data
    )

    # 5. Update the maturity date on the main loan record
    # Note: no conn.commit() here - this function is meant to run as part of
    # its caller's transaction.
    last_sched = conn.execute(
        "SELECT due_date FROM repayment_schedule WHERE loan_id = ? ORDER BY due_date DESC LIMIT 1",
        (loan_id,)
    ).fetchone()
    if last_sched:
        conn.execute(
            "UPDATE loans SET maturity_date = ? WHERE id = ?",
            (last_sched["due_date"], loan_id)
        )