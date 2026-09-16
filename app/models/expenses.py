from datetime import date
from . import accounting


def create_category(conn, name: str, description: str = None) -> int:
    cur = conn.execute(
        "INSERT OR IGNORE INTO expense_categories (name, description) VALUES (?,?)", (name, description)
    )
    conn.commit()
    row = conn.execute("SELECT id FROM expense_categories WHERE name = ?", (name,)).fetchone()
    return row["id"]


def list_categories(conn):
    return conn.execute("SELECT * FROM expense_categories ORDER BY name").fetchall()


def record_expense(conn, category_id: int, amount: float, expense_date: str = None,
                    paid_to: str = None, description: str = None, reference: str = None,
                    user_id=None) -> int:
    expense_date = expense_date or date.today().isoformat()
    cur = conn.execute(
        """INSERT INTO expenses (category_id, expense_date, amount, paid_to, description, reference, recorded_by)
           VALUES (?,?,?,?,?,?,?)""",
        (category_id, expense_date, amount, paid_to, description, reference, user_id),
    )
    expense_id = cur.lastrowid
    category = conn.execute("SELECT name FROM expense_categories WHERE id = ?", (category_id,)).fetchone()
    exp_row = conn.execute("SELECT * FROM expenses WHERE id = ?", (expense_id,)).fetchone()
    accounting.post_expense(conn, exp_row, category["name"], user_id)
    conn.commit()
    return expense_id


def list_expenses(conn, category_id: int = None, date_from=None, date_to=None):
    query = """SELECT e.*, ec.name as category_name FROM expenses e
               JOIN expense_categories ec ON ec.id = e.category_id WHERE 1=1"""
    params = []
    if category_id:
        query += " AND e.category_id = ?"
        params.append(category_id)
    if date_from:
        query += " AND e.expense_date >= ?"
        params.append(date_from)
    if date_to:
        query += " AND e.expense_date <= ?"
        params.append(date_to)
    query += " ORDER BY e.expense_date DESC, e.id DESC"
    return conn.execute(query, params).fetchall()


def expenses_by_category(conn, date_from=None, date_to=None):
    query = """SELECT ec.name as category, COALESCE(SUM(e.amount),0) as total
               FROM expense_categories ec LEFT JOIN expenses e ON e.category_id = ec.id"""
    params = []
    where = []
    if date_from:
        where.append("e.expense_date >= ?")
        params.append(date_from)
    if date_to:
        where.append("e.expense_date <= ?")
        params.append(date_to)
    if where:
        query += " AND " + " AND ".join(where)
    query += " GROUP BY ec.id ORDER BY total DESC"
    return conn.execute(query, params).fetchall()
