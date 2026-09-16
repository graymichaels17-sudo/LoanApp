"""
Currency handling for the app.

Every money column in the database is stored as an INTEGER number of
cents (e.g. $12.34 is stored as 1234). This module is the ONLY place that
should convert between that representation and the "dollars" floats/strings
the rest of the world (user input, display, PDFs, exports) uses.

Rules of thumb for the rest of the codebase:
  - Reading money out of the DB: it's already an int (cents). Do integer
    arithmetic on it (sums, differences, comparisons). Only call
    to_dollars()/fmt() right before it needs to be shown to a person.
  - Writing money into the DB: whatever you have (a float from a spinbox,
    a string a user typed, a dollar amount computed elsewhere) must go
    through to_cents() first.
  - Percentages/rates (interest_rate, admin_fee_pct, penalty_pct, PAYE
    band 'rate', etc.) are NOT money and are untouched by this module -
    they stay as plain floats.

Rounding: to_cents() uses ROUND_HALF_UP (ordinary "round half away from
zero" rounding), matching what a client expects to see on a printed
statement, rather than Python's default banker's rounding.
"""
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation


def to_cents(value) -> int:
    """Convert a dollar amount (float, int, str, Decimal, None) to integer cents."""
    if value is None or value == "":
        return 0
    if isinstance(value, bool):
        raise TypeError("Refusing to treat a bool as a money value.")
    try:
        d = value if isinstance(value, Decimal) else Decimal(str(value))
    except InvalidOperation:
        raise ValueError(f"Not a valid money amount: {value!r}")
    cents = (d * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(cents)


def to_dollars(cents) -> float:
    """Integer cents -> float dollars, for arithmetic/APIs that still need a float
    (e.g. handing a number to a charting widget). Prefer fmt() for display."""
    if cents is None:
        return 0.0
    return int(cents) / 100.0


def fmt(cents, symbol: str = "") -> str:
    """Format integer cents as a comma-grouped display string, e.g. fmt(123456) -> '1,234.56'."""
    if cents is None:
        cents = 0
    cents = int(round(cents))
    sign = "-" if cents < 0 else ""
    cents = abs(cents)
    dollars, rem = divmod(cents, 100)
    return f"{sign}{symbol}{dollars:,}.{rem:02d}"


def round_cents(cents) -> int:
    """Defensive helper: coerce a value that should already be an integer
    number of cents (e.g. after dividing a total pro-rata across several
    installments) back to a clean int."""
    if cents is None:
        return 0
    return int(Decimal(str(cents)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def allocate_pro_rata(total_cents: int, weights) -> list:
    """Split an integer cents amount across len(weights) buckets in
    proportion to `weights`, guaranteeing the parts sum exactly back to
    total_cents (the classic "largest remainder" method) - use this instead
    of dividing/rounding each share independently, which can leave the
    total a cent or two off due to rounding.
    """
    total_weight = sum(weights)
    if total_weight <= 0:
        return [0 for _ in weights]
    raw = [total_cents * w / total_weight for w in weights]
    base = [int(r) for r in raw]  # floor
    remainder = total_cents - sum(base)
    # distribute the leftover cents to the entries with the largest fractional part
    order = sorted(range(len(weights)), key=lambda i: raw[i] - base[i], reverse=True)
    for i in range(remainder):
        base[order[i % len(order)]] += 1
    return base
