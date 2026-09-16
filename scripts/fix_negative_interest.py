"""
One-off correction script for the negative-interest bug
(recalculate_interest_only_balloon_schedule() recomputing interest_due
below already-recorded interest_paid).

This is NOT part of the app package - it's a standalone maintenance script.
Run it once, from your project root, with the app package importable
(i.e. run as `python -m scripts.fix_negative_interest` if you drop it in a
`scripts/` folder at the project root, next to the `app/` package - see
notes at the bottom of this file for exactly where to put it).

BEFORE RUNNING: back up your database file. This writes to the DB.
"""

import argparse
import shutil
import sqlite3
import tempfile
from pathlib import Path

from app import config, database
from app.models.loans import close_loan_if_settled, outstanding_balance, update_loan
from app.models.loans import rebuild_schedule_and_reapply_repayments


# No more hardcoded loan list - Section 3 now discovers and fixes every
# broken row find_broken_rows() turns up, whatever loan it belongs to.
# (The original hardcoded list of 140/179/182 turned out to be incomplete -
# a live run found 8 broken rows, not 3.)


def find_broken_rows(conn):
    print("=== Section 1: rows where interest_due < interest_paid ===")
    rows = conn.execute(
        """SELECT rs.loan_id, l.loan_no, rs.installment_no, rs.interest_due, rs.interest_paid
           FROM repayment_schedule rs
           JOIN loans l ON l.id = rs.loan_id
           WHERE rs.interest_due < rs.interest_paid
           ORDER BY rs.loan_id, rs.installment_no"""
    ).fetchall()
    for r in rows:
        print(dict(r))
    return rows


def find_rollover_parent(conn, new_loan_id):
    print(f"\n=== Section 2: rollover parent of loan {new_loan_id} ===")
    row = conn.execute(
        """SELECT r.id AS rollover_id, r.original_loan_id, lo.loan_no AS original_loan_no,
                  r.new_loan_id, ln.loan_no AS new_loan_no, r.rollover_date, r.status
           FROM rollovers r
           JOIN loans lo ON lo.id = r.original_loan_id
           JOIN loans ln ON ln.id = r.new_loan_id
           WHERE r.new_loan_id = ?""",
        (new_loan_id,),
    ).fetchone()
    if row:
        print(dict(row))
    else:
        print(f"No rollover record found with new_loan_id = {new_loan_id}")
    return row


def fix_broken_row(conn, loan_id, installment_no):
    """
    Correct one broken schedule row (interest_due < interest_paid).
    Sets interest_due = interest_paid (true remaining interest is $0, since
    the balance really was paid down by a curtailment/overpayment),
    recomputes total_due, and lets status settle based on principal/penalty
    too. Safe to apply to ANY loan with this symptom - LN or RN alike; this
    is a row-level data repair, not specific to any one loan's rollover
    history.
    """
    row = conn.execute(
        "SELECT * FROM repayment_schedule WHERE loan_id = ? AND installment_no = ?",
        (loan_id, installment_no),
    ).fetchone()
    if row is None:
        print(f"  loan {loan_id} installment {installment_no}: not found, skipping")
        return

    new_interest_due = row["interest_paid"]
    new_total_due = round(row["principal_due"] + new_interest_due, 2)
    fully_paid = (
        row["principal_paid"] >= row["principal_due"] - 0.01
        and row["penalty_paid"] >= row["penalty_charged"] - 0.01
        # interest is always "fully paid" now, since due == paid by construction
    )
    new_status = "Paid" if fully_paid else "PartiallyPaid"

    conn.execute(
        "UPDATE repayment_schedule SET interest_due = ?, total_due = ?, status = ? WHERE id = ?",
        (new_interest_due, new_total_due, new_status, row["id"]),
    )
    print(f"  loan {loan_id} installment {installment_no}: interest_due -> {new_interest_due}, "
          f"total_due -> {new_total_due}, status -> {new_status}")


def fix_rollover_loan(conn, rollover_loan_id, rollover_row, rollover_rate_originally_entered):
    """
    Section 4: fix RN-00031 (or whichever loan is the rollover product)
    after its source loan has been corrected.

    rollover_rate_originally_entered: the interest rate the loan officer
    actually typed into the rollover form at the time (the `rollover_rate`
    used in request_rollover - NOT the corrupted effective_rate that ended
    up stored on the loan). You'll need to know or recall this figure;
    it isn't stored anywhere separately once request_rollover() overwrites
    new_loan_data["interest_rate"] with the derived effective_rate.
    """
    print(f"\n=== Section 4: fixing rollover loan {rollover_loan_id} ===")

    has_repayments = conn.execute(
        "SELECT COUNT(*) c FROM repayments WHERE loan_id = ?", (rollover_loan_id,)
    ).fetchone()["c"]

    original_loan_id = rollover_row["original_loan_id"]
    bal = outstanding_balance(conn, original_loan_id)
    old_arrears_corrected = round(bal["interest"] + bal["penalty"], 2)
    outstanding_principal = bal["principal"]

    if has_repayments == 0:
        print("  No repayments on the rollover loan yet - recommend reverse_rollover() "
              "then redoing the rollover from scratch so approve_rollover() recomputes "
              "everything cleanly with the corrected source-loan numbers.")
        print("  from app.models.rollovers import reverse_rollover")
        print(f"  reverse_rollover(conn, rollover_id={rollover_row['rollover_id']})")
        print("  # ... then re-run request_rollover() + approve_rollover() as normal")
        return

    print(f"  Rollover loan already has {has_repayments} repayment(s) - reversing is blocked.")
    print("  Manually recomputing the correct effective_rate instead:")

    new_added_interest = outstanding_principal * (rollover_rate_originally_entered / 100.0)
    total_new_loan_interest = old_arrears_corrected + new_added_interest
    if outstanding_principal > 0:
        corrected_rate = (total_new_loan_interest / outstanding_principal) * 100.0
    else:
        corrected_rate = rollover_rate_originally_entered

    print(f"  corrected old_arrears      = {old_arrears_corrected}")
    print(f"  outstanding_principal      = {outstanding_principal}")
    print(f"  total_new_loan_interest    = {total_new_loan_interest}")
    print(f"  corrected effective_rate   = {corrected_rate}")

    update_loan(conn, rollover_loan_id, {"interest_rate": corrected_rate})
    rebuild_schedule_and_reapply_repayments(conn, rollover_loan_id, {})
    print(f"  Applied corrected_rate to loan {rollover_loan_id} and rebuilt its schedule.")


def get_connection_for(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def run_corrections(conn, rollover_loan_id=None, rollover_rate_originally_entered=None):
    """Runs against whatever connection it's given. Called against the real
    live DB, or against a throwaway copy for --dry-run.

    rollover_loan_id: pass this (via --fix-rollover-loan) ONLY once you've
    confirmed via the rollovers table which loan is genuinely the rollover
    product you want corrected, and with what rate was actually entered at
    the time (--rollover-rate). Left as None, Section 4 is skipped entirely -
    which is the safe default right now, since loan 285's rollover parentage
    hasn't been confirmed yet (Section 2 found no matching rollovers row)."""
    broken_rows = find_broken_rows(conn)

    print("\n=== Section 3: correcting every broken row found above ===")
    for row in broken_rows:
        fix_broken_row(conn, row["loan_id"], row["installment_no"])
    conn.commit()

    affected_loan_ids = sorted({row["loan_id"] for row in broken_rows})
    for loan_id in affected_loan_ids:
        closed = close_loan_if_settled(conn, loan_id)
        print(f"  close_loan_if_settled(loan_id={loan_id}) -> {closed}")

    if rollover_loan_id is not None:
        rollover_row = find_rollover_parent(conn, rollover_loan_id)
        if rollover_row is not None and rollover_rate_originally_entered is not None:
            fix_rollover_loan(conn, rollover_loan_id, rollover_row, rollover_rate_originally_entered)
        elif rollover_row is None:
            print(f"\n[SKIPPED] No rollovers row found with new_loan_id={rollover_loan_id} - "
                  f"can't safely apply Section 4. Investigate this loan manually first.")
        else:
            print(f"\n[SKIPPED] --fix-rollover-loan given without --rollover-rate - "
                  f"need the originally-entered rate to recompute correctly.")

    print("\n=== Post-fix state (should be empty if everything was corrected) ===")
    find_broken_rows(conn)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Run every fix against a throwaway COPY of the database and print "
             "the results, without touching the real database at all. Several "
             "app functions used here (close_loan_if_settled, update_loan, "
             "rebuild_schedule_and_reapply_repayments) commit internally, so a "
             "plain rollback can't undo them once run - copying the file first "
             "is the only way to preview safely.",
    )
    parser.add_argument(
        "--fix-rollover-loan", type=int, default=None, metavar="LOAN_ID",
        help="Also recompute the rollover interest_rate for this loan_id "
             "(Section 4), once you've confirmed via the rollovers table "
             "which loan this actually is. Requires --rollover-rate too.",
    )
    parser.add_argument(
        "--rollover-rate", type=float, default=None, metavar="PERCENT",
        help="The interest rate that was actually entered on the rollover "
             "request form at the time, for use with --fix-rollover-loan.",
    )
    args = parser.parse_args()

    if args.dry_run:
        real_db_path = Path(config.DB_PATH)
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_db_path = Path(tmp_dir) / real_db_path.name
            shutil.copy2(real_db_path, tmp_db_path)
            print(f"[DRY RUN] Working against a throwaway copy at {tmp_db_path}")
            print(f"[DRY RUN] Real database at {real_db_path} will NOT be modified.\n")

            conn = get_connection_for(tmp_db_path)
            run_corrections(conn, args.fix_rollover_loan, args.rollover_rate)
            conn.close()
        print("\n[DRY RUN] Complete. The copy above has been discarded - "
              "nothing was written to your real database. Re-run without "
              "--dry-run to apply for real.")
    else:
        conn = database.get_connection()
        conn.row_factory = sqlite3.Row
        run_corrections(conn, args.fix_rollover_loan, args.rollover_rate)
        conn.close()
        print("\nDone. Spot-check the affected loans' statements before considering this closed.")


if __name__ == "__main__":
    main()
