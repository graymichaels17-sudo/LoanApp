import sqlite3

c = sqlite3.connect(r'C:\Users\HP\Documents\MicrofinanceManager\data\microfinance.db')
c.row_factory = sqlite3.Row

loan = c.execute(
    "SELECT id, loan_no, interest_method, term_months, repayment_frequency, "
    "phase2_term_months, phase2_frequency, disbursement_date "
    "FROM loans ORDER BY id DESC LIMIT 1"
).fetchone()
print(dict(loan))

sched = c.execute(
    "SELECT installment_no, due_date, principal_due, interest_due "
    "FROM repayment_schedule WHERE loan_id = ? ORDER BY installment_no",
    (loan["id"],)
).fetchall()
for row in sched:
    print(dict(row))