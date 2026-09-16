"""
One-off backfill: fills in loans.capitalized_interest for loans that were
already disbursed BEFORE the disbursements.py fix existed (so the column is
currently NULL for them).

Rather than summing today's repayment_schedule (which may have been
recalculated after repayments - see recalculate_interest_only_balloon_schedule
in loans.py, and which is exactly what caused the original bug), this
re-derives the ORIGINAL interest total directly from the loan's stored
principal / interest_rate / interest_method / rate_period / term_months,
mirroring build_schedule()'s formulas exactly. That reconstructs what would
have been capitalized at disbursement time, regardless of what has happened
to the schedule since.

Run this once, AFTER applying the disbursements.py and main_window.py fixes:
    python backfill_capitalized_interest.py /path/to/your.db
    (add --dry-run to preview without writing changes)
"""
import sqlite3
import sys


def _compute_original_total_interest(loan) -> float:
    principal = loan["principal"]
    interest_rate = loan["interest_rate"]
    interest_method = loan["interest_method"]
    term_months = loan["term_months"]
    rate_period = loan["rate_period"] if "rate_period" in loan.keys() and loan["rate_period"] else "month"

    if interest_method == "flat":
        if rate_period == "loan_term":
            total_interest = principal * (interest_rate / 100.0)
        elif rate_period == "year":
            total_interest = principal * (interest_rate / 100.0) * (term_months / 12.0)
        else:  # 'month'
            total_interest = principal * (interest_rate / 100.0) * term_months
        return round(total_interest, 2)

    elif interest_method == "interest_only_balloon":
        # Same shape as build_schedule(): every period charges interest on
        # the ORIGINAL principal (balance never drops before the balloon),
        # regardless of what later repayments/recalculations did to it.
        monthly_rate = interest_rate / 100.0
        return round(principal * monthly_rate * term_months, 2)

    else:  # reducing_balance
        r = interest_rate / 100.0
        if rate_period == "year":
            r = r / 12.0
        if r == 0:
            emi = round(principal / term_months, 2)
        else:
            emi = principal * r * (1 + r) ** term_months / ((1 + r) ** term_months - 1)
        balance = principal
        running_principal = 0.0
        total_interest = 0.0
        for i in range(1, term_months + 1):
            interest_component = round(balance * r, 2)
            principal_component = round(emi - interest_component, 2)
            if i == term_months:
                principal_component = round(principal - running_principal, 2)
            balance = round(balance - principal_component, 2)
            running_principal += principal_component
            total_interest += interest_component
        return round(total_interest, 2)


def backfill(db_path: str, dry_run: bool = False):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    loans = conn.execute(
        """SELECT id, loan_no, principal, interest_rate, interest_method,
                  rate_period, term_months, disbursement_date
           FROM loans
           WHERE disbursement_date IS NOT NULL
             AND capitalized_interest IS NULL"""
    ).fetchall()

    print(f"Found {len(loans)} disbursed loan(s) missing capitalized_interest.\n")

    for loan in loans:
        try:
            amount = _compute_original_total_interest(loan)
        except Exception as e:
            print(f"  SKIPPED loan {loan['loan_no']} (id={loan['id']}): {e}")
            continue

        print(f"  Loan {loan['loan_no']} (id={loan['id']}): "
              f"principal={loan['principal']}, rate={loan['interest_rate']}%, "
              f"method={loan['interest_method']}, term={loan['term_months']}mo "
              f"-> capitalized_interest = {amount}")

        if not dry_run:
            conn.execute(
                "UPDATE loans SET capitalized_interest = ? WHERE id = ?",
                (amount, loan["id"]),
            )

    if dry_run:
        print("\nDry run only - no changes written. Re-run without --dry-run to apply.")
    else:
        conn.commit()
        print(f"\nDone. Backfilled {len(loans)} loan(s).")

    conn.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python backfill_capitalized_interest.py /path/to/your.db [--dry-run]")
        sys.exit(1)
    dry_run = "--dry-run" in sys.argv
    backfill(sys.argv[1], dry_run=dry_run)
