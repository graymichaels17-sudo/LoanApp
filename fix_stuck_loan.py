"""
One-off repair script for a loan stuck exactly like LN-00152: it already has
a disbursement record and a repayment schedule (so it genuinely was
disbursed), but an error partway through the old disburse_loan() left it
stuck at status='Pending' with the admin fee never charged and the
capitalized_interest snapshot never taken.

This script finishes the job the old code didn't:
  1. Verifies the loan is actually in this exact broken state (safety check
     - refuses to touch anything that doesn't match, so it can't misfire on
     a normal Pending loan or an already-Active one).
  2. Charges the admin fee (if the loan has one and it hasn't been charged
     already) and posts its journal entry, exactly like charge_fee() does.
  3. Backfills capitalized_interest from the schedule (safe here because
     the loan never went Active, so no repayment has touched the schedule
     yet - the current interest_due values are still the untouched originals).
  4. Sets status = 'Active'.

Delete this file once you've confirmed the loan looks right afterward - it's
a one-time fix, not something to run again.

Usage:
    python fix_stuck_loan.py /path/to/your.db LN-00152
    (add --dry-run to preview without writing anything)
"""
import sqlite3
import sys
from datetime import date


def get_account_id(conn, code: str) -> int:
    row = conn.execute("SELECT id FROM accounts WHERE code = ?", (code,)).fetchone()
    if row is None:
        raise ValueError(f"Account code {code} not found - check your chart of accounts.")
    return row["id"]


def ensure_capitalized_interest_column(conn, dry_run: bool):
    cols = [row["name"] for row in conn.execute("PRAGMA table_info(loans)").fetchall()]
    if "capitalized_interest" not in cols:
        if dry_run:
            print("  (loans.capitalized_interest column is missing - would be added)")
            return False
        conn.execute("ALTER TABLE loans ADD COLUMN capitalized_interest REAL")
        conn.commit()
        print("  (added missing loans.capitalized_interest column)")
    return True


def fix_stuck_loan(db_path: str, loan_no: str, dry_run: bool = False):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")

    column_exists = ensure_capitalized_interest_column(conn, dry_run)

    loan = conn.execute("SELECT * FROM loans WHERE loan_no = ?", (loan_no,)).fetchone()
    if loan is None:
        print(f"No loan found with loan_no = {loan_no}. Nothing done.")
        conn.close()
        return

    # ---- Safety checks: only proceed if this loan matches the exact broken state ----
    if loan["status"] != "Pending":
        print(f"Loan {loan_no} has status='{loan['status']}', not 'Pending' - "
              f"this doesn't look like the stuck state. Refusing to touch it.")
        conn.close()
        return

    disb_count = conn.execute(
        "SELECT COUNT(*) c FROM disbursements WHERE loan_id = ?", (loan["id"],)
    ).fetchone()["c"]
    sched_count = conn.execute(
        "SELECT COUNT(*) c FROM repayment_schedule WHERE loan_id = ?", (loan["id"],)
    ).fetchone()["c"]

    if disb_count == 0 or sched_count == 0:
        print(f"Loan {loan_no} is Pending but has no disbursement/schedule rows - "
              f"this is a normal not-yet-disbursed loan, not the stuck state. Refusing to touch it.")
        conn.close()
        return

    print(f"Loan {loan_no} (id={loan['id']}): status=Pending, "
          f"{disb_count} disbursement(s), {sched_count} schedule row(s) - matches the stuck state.")

    disbursement_date = loan["disbursement_date"] or date.today().isoformat()

    # ---- Step 1: charge admin fee, if applicable and not already charged ----
    admin_fee = loan["admin_fee"] or 0
    existing_fee = conn.execute(
        "SELECT id FROM fees WHERE loan_id = ? AND fee_type = 'Admin'", (loan["id"],)
    ).fetchone()

    if admin_fee > 0 and existing_fee is None:
        print(f"  Charging admin fee: {admin_fee}")
        if not dry_run:
            cur = conn.execute(
                "INSERT INTO fees (loan_id, fee_type, amount, date_charged, description, status) "
                "VALUES (?,?,?,?,?,?)",
                (loan["id"], "Admin", admin_fee, disbursement_date, "Admin fee", "Paid"),
            )
            fee_id = cur.lastrowid

            cash_id = get_account_id(conn, "1000")
            income_id = get_account_id(conn, "4100")
            je_cur = conn.execute(
                "INSERT INTO journal_entries (entry_date, reference, source_type, source_id, description, created_by) "
                "VALUES (?,?,?,?,?,?)",
                (disbursement_date, f"FEE-{fee_id:06d}", "fee", fee_id,
                 f"Admin fee collected - Loan #{loan['id']}", None),
            )
            journal_id = je_cur.lastrowid
            conn.execute(
                "INSERT INTO journal_lines (journal_entry_id, account_id, debit, credit, memo) VALUES (?,?,?,?,?)",
                (journal_id, cash_id, admin_fee, 0, None),
            )
            conn.execute(
                "INSERT INTO journal_lines (journal_entry_id, account_id, debit, credit, memo) VALUES (?,?,?,?,?)",
                (journal_id, income_id, 0, admin_fee, None),
            )
    elif existing_fee is not None:
        print("  Admin fee already exists for this loan - skipping (not double-charging).")
    else:
        print("  No admin fee on this loan - nothing to charge.")

    # ---- Step 2: backfill capitalized_interest ----
    # Safe to sum the schedule directly here: the loan never went Active, so
    # no repayment has ever touched/recalculated these interest_due values.
    existing_capitalized_interest = loan["capitalized_interest"] if column_exists else None
    if existing_capitalized_interest is None:
        schedule = conn.execute(
            "SELECT interest_due FROM repayment_schedule WHERE loan_id = ?", (loan["id"],)
        ).fetchall()
        capitalized_interest = round(sum(r["interest_due"] for r in schedule), 2)
        print(f"  Setting capitalized_interest = {capitalized_interest}")
        if not dry_run:
            conn.execute(
                "UPDATE loans SET capitalized_interest = ? WHERE id = ?",
                (capitalized_interest, loan["id"]),
            )
    else:
        print(f"  capitalized_interest already set ({existing_capitalized_interest}) - leaving as is.")

    # ---- Step 3: activate the loan ----
    print("  Setting status = 'Active'")
    if not dry_run:
        conn.execute("UPDATE loans SET status = 'Active' WHERE id = ?", (loan["id"],))
        conn.commit()
        print(f"\nDone. Loan {loan_no} is now Active.")
    else:
        print("\nDry run only - no changes written. Re-run without --dry-run to apply.")

    conn.close()


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python fix_stuck_loan.py /path/to/your.db LN-00152 [--dry-run]")
        sys.exit(1)
    dry_run = "--dry-run" in sys.argv
    fix_stuck_loan(sys.argv[1], sys.argv[2], dry_run=dry_run)
