from app import config       # use the actual package name your project uses instead of "app"
import sqlite3

conn = sqlite3.connect(config.DB_PATH)
conn.row_factory = sqlite3.Row

rows = conn.execute(
    "SELECT id, name, interest_method FROM loan_products "
    "WHERE interest_method NOT IN ('flat','reducing_balance','interest_over_tenure')"
).fetchall()
print([dict(r) for r in rows])
conn.close()
