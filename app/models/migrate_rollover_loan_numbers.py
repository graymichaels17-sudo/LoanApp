"""
One-off migration: renumber all existing rollover-originated loans from
their old LN-xxxxx numbers onto the new RN-xxxxx series, and backfill
parent_loan_id for them (which was previously being silently dropped by
create_loan(), before that was fixed).

Why this is safe / all that's needed:
    Repayments, disbursements, fees, and the repayment_schedule all
    reference a loan by its numeric loan_id (a foreign key) - never by
    loan_no text. Every place that displays loan_no (statements, reports,
    the repayments list, etc.) fetches it fresh via a JOIN back to `loans`.
    So the only column that actually needs updating is loans.loan_no
    itself; every screen and report will pick up the new number
    automatically the next time it queries.

How rollover loans are identified:
    The `rollovers` table's new_loan_id column was always written directly
    with a real value (that INSERT never went through create_loan()'s
    allowed-fields list), so it reliably identifies every rollover loan
    ever created - even ones from before parent_loan_id was fixed.

Usage:
    python migrate_rollover_loan_numbers.py path/to/your.db --dry-run   # preview only
    python migrate_rollover_loan_numbers.py path/to/your.db             # apply

Back up your database file before running this for real.
"""
import sqlite3
import sys


def migrate(db_path, dry_run=False):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        """SELECT r.new_loan_id, r.original_loan_id, r.rollover_date, l.loan_no
           FROM rollovers r
           JOIN loans l ON l.id = r.new_loan_id
           WHERE l.loan_no NOT LIKE 'RN-%'
           ORDER BY r.rollover_date, r.id"""
    ).fetchall()

    if not rows:
        print("No rollover-originated loans need renumbering - nothing to do.")
        conn.close()
        return

    # Continue the RN- series after any that already exist (e.g. rollovers
    # created since the RN- prefix was introduced), rather than restarting
    # from 1 and risking a collision.
    existing_max = conn.execute(
        "SELECT MAX(CAST(SUBSTR(loan_no, 4) AS INTEGER)) FROM loans WHERE loan_no LIKE 'RN-%'"
    ).fetchone()[0] or 0
    next_no = existing_max + 1

    print(f"{len(rows)} rollover loan(s) to renumber, starting at RN-{next_no:05d}:\n")

    for row in rows:
        new_loan_no = f"RN-{next_no:05d}"
        print(f"  loan id {row['new_loan_id']:>6}: {row['loan_no']:<10} -> {new_loan_no}   "
              f"(rolled from loan id {row['original_loan_id']}, on {row['rollover_date']})")
        if not dry_run:
            conn.execute(
                "UPDATE loans SET loan_no = ?, parent_loan_id = ? WHERE id = ?",
                (new_loan_no, row["original_loan_id"], row["new_loan_id"]),
            )
        next_no += 1

    if dry_run:
        print("\nDry run only - no changes written. Re-run without --dry-run to apply.")
    else:
        conn.commit()
        print(f"\nDone. {len(rows)} loan(s) renumbered and parent_loan_id backfilled.")

    conn.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python migrate_rollover_loan_numbers.py path/to/your.db [--dry-run]")
        sys.exit(1)
    migrate(sys.argv[1], dry_run="--dry-run" in sys.argv)
