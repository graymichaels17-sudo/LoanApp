import sqlite3

# =====================================================================
# CLIENT LOCATIONS
# A managed lookup list so location entry can be standardized via a
# dropdown, instead of free text that drifts (e.g. "Harare" vs "harare").
# clients.location itself remains plain TEXT (see schema.sql) - this
# module only manages the list of options offered to the user.
# =====================================================================

def list_locations(conn, active_only: bool = False):
    query = "SELECT * FROM locations"
    if active_only:
        query += " WHERE active = 1"
    query += " ORDER BY name"
    return conn.execute(query).fetchall()


def create_location(conn, name: str):
    name = (name or "").strip()
    if not name:
        raise ValueError("Location name is required.")
    try:
        conn.execute("INSERT INTO locations (name) VALUES (?)", (name,))
    except sqlite3.IntegrityError:
        raise ValueError(f"Location '{name}' already exists.")
    conn.commit()


def update_location(conn, location_id: int, name: str = None, active: bool = None):
    fields, values = [], []
    if name is not None:
        name = name.strip()
        if not name:
            raise ValueError("Location name is required.")
        fields.append("name = ?")
        values.append(name)
    if active is not None:
        fields.append("active = ?")
        values.append(1 if active else 0)
    if not fields:
        return
    values.append(location_id)
    try:
        conn.execute(f"UPDATE locations SET {', '.join(fields)} WHERE id = ?", values)
    except sqlite3.IntegrityError:
        raise ValueError(f"Location '{name}' already exists.")
    conn.commit()


def delete_location(conn, location_id: int):
    """
    Hard delete is safe here: clients.location is plain text, not a
    foreign key, so removing an entry from this lookup list never touches
    any existing client record. Prefer update_location(..., active=False)
    instead if you just want to retire an option from the dropdown while
    keeping it around for historical reference.
    """
    conn.execute("DELETE FROM locations WHERE id = ?", (location_id,))
    conn.commit()


# =====================================================================
# LOAN PRODUCTS
# Full CRUD so interest rates, fees, and terms can be managed from the
# Settings screen instead of only being seedable in code.
# =====================================================================

_PRODUCT_FIELDS = [
    "name", "interest_method", "interest_rate", "rate_period",
    "admin_fee_pct", "penalty_pct", "grace_period_days",
    "repayment_frequency", "term_unit_label", "application_fee_pct",
]


def list_loan_products(conn, active_only: bool = False):
    query = "SELECT * FROM loan_products"
    if active_only:
        query += " WHERE active = 1"
    query += " ORDER BY name"
    return conn.execute(query).fetchall()


def get_loan_product(conn, product_id: int):
    return conn.execute("SELECT * FROM loan_products WHERE id = ?", (product_id,)).fetchone()


def create_loan_product(conn, data: dict):
    if not (data.get("name") or "").strip():
        raise ValueError("Product name is required.")
    cols = [f for f in _PRODUCT_FIELDS if f in data]
    values = [data[c] for c in cols]
    placeholders = ",".join("?" for _ in cols)
    try:
        conn.execute(
            f"INSERT INTO loan_products ({','.join(cols)}) VALUES ({placeholders})", values
        )
    except sqlite3.IntegrityError:
        raise ValueError(f"A loan product named '{data['name']}' already exists.")
    conn.commit()


def update_loan_product(conn, product_id: int, data: dict):
    fields = list(_PRODUCT_FIELDS) + ["active"]
    sets, values = [], []
    for f in fields:
        if f in data:
            sets.append(f"{f} = ?")
            values.append(data[f])
    if not sets:
        return
    values.append(product_id)
    try:
        conn.execute(f"UPDATE loan_products SET {', '.join(sets)} WHERE id = ?", values)
    except sqlite3.IntegrityError:
        raise ValueError(f"A loan product named '{data.get('name')}' already exists.")
    conn.commit()


def set_loan_product_active(conn, product_id: int, active: bool):
    conn.execute("UPDATE loan_products SET active = ? WHERE id = ?", (1 if active else 0, product_id))
    conn.commit()


# =====================================================================
# INTEREST RATE PRESETS
# A managed, reusable list of interest rates that can be picked from
# elsewhere in the app (e.g. a quick-select next to the Interest Rate
# field on the New Loan form), independent of any particular Loan Product.
# =====================================================================

def list_rate_presets(conn, active_only: bool = False):
    query = "SELECT * FROM interest_rate_presets"
    if active_only:
        query += " WHERE active = 1"
    query += " ORDER BY rate"
    return conn.execute(query).fetchall()


def create_rate_preset(conn, label: str, rate: float):
    label = (label or "").strip()
    if not label:
        raise ValueError("Preset label is required.")
    rate = float(rate)
    if rate <= 0:
        raise ValueError("Rate must be a positive number.")
    try:
        conn.execute(
            "INSERT INTO interest_rate_presets (label, rate) VALUES (?, ?)", (label, rate)
        )
    except sqlite3.IntegrityError:
        raise ValueError(f"Preset '{label}' already exists.")
    conn.commit()


def update_rate_preset(conn, preset_id: int, label: str = None, rate: float = None, active: bool = None):
    fields, values = [], []
    if label is not None:
        label = label.strip()
        if not label:
            raise ValueError("Preset label is required.")
        fields.append("label = ?")
        values.append(label)
    if rate is not None:
        rate = float(rate)
        if rate <= 0:
            raise ValueError("Rate must be a positive number.")
        fields.append("rate = ?")
        values.append(rate)
    if active is not None:
        fields.append("active = ?")
        values.append(1 if active else 0)
    if not fields:
        return
    values.append(preset_id)
    try:
        conn.execute(f"UPDATE interest_rate_presets SET {', '.join(fields)} WHERE id = ?", values)
    except sqlite3.IntegrityError:
        raise ValueError(f"Preset '{label}' already exists.")
    conn.commit()


def delete_rate_preset(conn, preset_id: int):
    """
    Hard delete is safe here: rates on existing loans/products are copied
    values, not references to this table, so removing a preset never
    touches historical data.
    """
    conn.execute("DELETE FROM interest_rate_presets WHERE id = ?", (preset_id,))
    conn.commit()

def get_company_details(conn) -> dict:
    rows = conn.execute("SELECT key, value FROM company_details").fetchall()
    return {r["key"]: r["value"] for r in rows}

def save_company_details(conn, details: dict):
    for key, value in details.items():
        conn.execute(
            "REPLACE INTO company_details (key, value) VALUES (?, ?)",
            (key, value)
        )
    conn.commit()
