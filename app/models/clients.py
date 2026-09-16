from datetime import date
from ..database import next_sequence_number
from ..money import round_cents

FIELDS = [
    "first_name", "last_name", "national_id", "gender", "location", "phone",
    "address", "occupation", "average_income", "guarantor", "guarantor_phone",
    "status", "notes",
]


def create_client(conn, data: dict, user_id=None) -> int:
    client_no = next_sequence_number(conn, "clients", "client_no", "CLI")
    cur = conn.execute(
        """INSERT INTO clients
           (client_no, first_name, last_name, national_id, gender, location, phone,
            address, occupation, average_income, guarantor, guarantor_phone,
            date_registered, status, notes, created_by)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,COALESCE(?, date('now')),?,?,?)""",
        (
            client_no, data["first_name"], data["last_name"], data.get("national_id"),
            data.get("gender"), data.get("location"), data.get("phone"),
            data.get("address"), data.get("occupation"), data.get("average_income"),
            data.get("guarantor"), data.get("guarantor_phone"),
            data.get("date_registered"), data.get("status", "Active"),
            data.get("notes"), user_id,
        ),
    )
    conn.commit()
    return cur.lastrowid


def update_client(conn, client_id: int, data: dict):
    set_clause = ", ".join(f"{f} = ?" for f in FIELDS if f in data)
    values = [data[f] for f in FIELDS if f in data]
    if not set_clause:
        return
    values.append(client_id)
    conn.execute(f"UPDATE clients SET {set_clause} WHERE id = ?", values)
    conn.commit()


def get_client(conn, client_id: int):
    return conn.execute("SELECT * FROM clients WHERE id = ?", (client_id,)).fetchone()


def list_clients(conn, search: str = "", status: str = None):
    query = "SELECT * FROM clients WHERE 1=1"
    params = []
    if search:
        query += (" AND (first_name LIKE ? OR last_name LIKE ? OR client_no LIKE ? OR national_id LIKE ? "
                   "OR phone LIKE ? OR location LIKE ?)")
        like = f"%{search}%"
        params += [like, like, like, like, like, like]
    if status:
        query += " AND status = ?"
        params.append(status)
    query += " ORDER BY id DESC"
    return conn.execute(query, params).fetchall()


def delete_client(conn, client_id: int):
    active_loans = conn.execute(
        "SELECT COUNT(*) c FROM loans WHERE client_id = ? AND status IN ('Active','Pending')",
        (client_id,),
    ).fetchone()["c"]
    if active_loans:
        raise ValueError("Cannot delete a client with active or pending loans.")
    conn.execute("DELETE FROM clients WHERE id = ?", (client_id,))
    conn.commit()


def client_loan_history(conn, client_id: int):
    return conn.execute(
        "SELECT * FROM loans WHERE client_id = ? ORDER BY id DESC", (client_id,)
    ).fetchall()


def get_client_by_no(conn, client_no: str):
    """Used by bulk loan upload to resolve a CSV row's client_no to a client."""
    return conn.execute("SELECT * FROM clients WHERE client_no = ?", (client_no.strip(),)).fetchone()


def client_payment_behavior(conn, client_id: int):
    """
    Builds an installment-level payment history across every loan this client
    has ever had - each due installment matched against the repayment(s) that
    covered it - plus summary stats (on-time rate, average days late, typical
    payment size) so a loan officer can judge whether this client pays on
    time and how large a repayment they can comfortably manage, before
    deciding on the next disbursement.

    Matching approach: installments are walked in due-date order and
    repayments in chronological order, and an installment is credited as
    "paid on" the date the running total of repayments first reaches its
    cumulative amount due. This mirrors exactly how the app itself allocates
    payments (oldest installment first, penalty -> interest -> principal) for
    flat and reducing-balance loans. For interest-only-balloon loans - where
    future installments get recalculated after every payment - the paid-date
    match is a best-effort approximation rather than an exact replay.
    """
    loans = client_loan_history(conn, client_id)

    all_installments = []
    payment_amounts = []  # every repayment transaction amount, for "typical payment size"

    for loan in loans:
        schedule = conn.execute(
            "SELECT * FROM repayment_schedule WHERE loan_id = ? ORDER BY due_date, installment_no",
            (loan["id"],),
        ).fetchall()
        repayments = conn.execute(
            "SELECT * FROM repayments WHERE loan_id = ? ORDER BY payment_date, id",
            (loan["id"],),
        ).fetchall()

        for r in repayments:
            payment_amounts.append(r["amount"])

        cum_paid_by_date = []
        running = 0
        for r in repayments:
            running += r["amount"]
            cum_paid_by_date.append((running, r["payment_date"]))

        cum_due = 0
        for inst in schedule:
            total_due = inst["principal_due"] + inst["interest_due"] + inst["penalty_charged"]
            amount_paid = inst["principal_paid"] + inst["interest_paid"] + inst["penalty_paid"]
            cum_due += total_due

            paid_date = None
            if inst["status"] == "Paid":
                for cum_paid, pdate in cum_paid_by_date:
                    if cum_paid >= cum_due:
                        paid_date = pdate
                        break
            elif inst["status"] == "PartiallyPaid" and repayments:
                paid_date = repayments[-1]["payment_date"]  # most recent activity touching this loan

            days_late = None
            if paid_date:
                days_late = (date.fromisoformat(paid_date) - date.fromisoformat(inst["due_date"])).days

            all_installments.append({
                "loan_id": loan["id"],
                "loan_no": loan["loan_no"],
                "installment_no": inst["installment_no"],
                "due_date": inst["due_date"],
                "amount_due": round_cents(total_due),
                "amount_paid": round_cents(amount_paid),
                "paid_date": paid_date,
                "days_late": days_late,
                "status": inst["status"],
            })

    settled = [i for i in all_installments if i["status"] == "Paid" and i["days_late"] is not None]
    on_time_count = sum(1 for i in settled if i["days_late"] <= 0)
    late_count = sum(1 for i in settled if i["days_late"] > 0)
    late_days = [i["days_late"] for i in settled if i["days_late"] > 0]

    summary = {
        "total_settled": len(settled),
        "on_time_count": on_time_count,
        "late_count": late_count,
        "on_time_rate": round(100 * on_time_count / len(settled), 1) if settled else None,
        "avg_days_late": round(sum(late_days) / len(late_days), 1) if late_days else 0,
        "avg_payment_amount": round_cents(sum(payment_amounts) / len(payment_amounts)) if payment_amounts else 0,
        "largest_payment": max(payment_amounts) if payment_amounts else 0,
        "smallest_payment": min(payment_amounts) if payment_amounts else 0,
        "total_payments": len(payment_amounts),
    }

    return {"installments": all_installments, "summary": summary}
