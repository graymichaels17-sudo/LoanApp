from ..database import get_connection
from .loans import get_loan_by_no
from .repayments import _recompute_loan_repayments

conn = get_connection()

loan = get_loan_by_no(conn, "LN-00169")
if loan is None:
    raise SystemExit("Loan LN-00169 not found")

_recompute_loan_repayments(conn, loan["id"])
conn.commit()
print(f"Recomputed loan {loan['loan_no']} (id={loan['id']})")
