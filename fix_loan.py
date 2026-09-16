import sqlite3
from app.models.loans import rebuild_schedule_and_reapply_repayments

# Note: Update this path to exactly where your database file is located 
# relative to the main folder (e.g., "app/database.db" or just "database.db")
conn = sqlite3.connect("app/microfinance.db")
conn.row_factory = sqlite3.Row

# Verify this is the correct integer ID for LN-00169 in your database
target_loan_id = 169 

rebuild_schedule_and_reapply_repayments(
    conn, 
    target_loan_id, 
    {"interest_method": "interest_only_balloon"}
)

print("Loan LN-00169 successfully updated and payments reallocated.")