"""
One-off migration: adds loans.capitalized_interest (nullable REAL).

Run this once against your existing database file, e.g.:
    python migrate_add_capitalized_interest.py /path/to/your.db

It is safe to run more than once - if the column already exists it
just prints a message and exits without error.
"""
import sqlite3
import sys


def migrate(db_path: str):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("ALTER TABLE loans ADD COLUMN capitalized_interest REAL")
        conn.commit()
        print("Added loans.capitalized_interest column.")
    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e).lower():
            print("Column loans.capitalized_interest already exists - nothing to do.")
        else:
            raise
    finally:
        conn.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python migrate_add_capitalized_interest.py /path/to/your.db")
        sys.exit(1)
    migrate(sys.argv[1])
