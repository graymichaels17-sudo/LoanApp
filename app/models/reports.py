from datetime import date, timedelta
from .bad_debts import list_bad_debts
from .disbursements import list_disbursements


def _aging_bucket(days_overdue: int) -> str:
    if days_overdue <= 30:
        return "1-30 days"
    if days_overdue <= 60:
        return "31-60 days"
    if days_overdue <= 90:
        return "61-90 days"
    return "Over 90 days"



def past_maturity_report(conn, as_of_date: str = None):
    """Loans that have passed their maturity date without being settled."""
    as_of_date = as_of_date or date.today().isoformat()
    rows = conn.execute(
        """SELECT l.id, l.loan_no, l.maturity_date, l.status, 
                  c.first_name, c.last_name, c.location, c.phone
           FROM loans l
           JOIN clients c ON c.id = l.client_id
           WHERE l.status = 'Active' AND l.maturity_date IS NOT NULL AND l.maturity_date < ?
           ORDER BY l.maturity_date ASC""",
        (as_of_date,),
    ).fetchall()
    
    result = []
    today = date.fromisoformat(as_of_date)
    for r in rows:
        maturity = date.fromisoformat(r["maturity_date"])
        days_past_maturity = (today - maturity).days
        
        outstanding = conn.execute(
            """SELECT COALESCE(SUM((principal_due - principal_paid) 
                                    + (interest_due - interest_paid) 
                                    + (penalty_charged - penalty_paid)), 0) as total
               FROM repayment_schedule WHERE loan_id = ?""",
            (r["id"],),
        ).fetchone()
        outstanding_balance = round(outstanding["total"], 2)
        
        result.append({
            "loan_no": r["loan_no"],
            "client": f"{r['first_name']} {r['last_name']}",
            "maturity_date": r["maturity_date"],
            "ageing_days": days_past_maturity,
            "location": r["location"] or "-",
            "balance": outstanding_balance,
            "contact": r["phone"] or "-",
        })
    
    return result


def arrears_report(conn, as_of_date: str = None):
    """Consolidated report: Per-loan aggregated arrears with aging buckets."""
    as_of_date = as_of_date or date.today().isoformat()
    
    # Query all overdue installments directly
    rows = conn.execute(
        """SELECT rs.loan_id, rs.due_date, 
                  (rs.principal_due - rs.principal_paid) + 
                  (rs.interest_due - rs.interest_paid) + 
                  (rs.penalty_charged - rs.penalty_paid) as outstanding,
                  l.loan_no, c.client_no, c.first_name, c.last_name,
                  c.phone, c.location
           FROM repayment_schedule rs
           JOIN loans l ON l.id = rs.loan_id
           JOIN clients c ON c.id = l.client_id
           WHERE l.status = 'Active' AND rs.status != 'Paid' AND rs.due_date < ?
           ORDER BY rs.due_date""",
        (as_of_date,),
    ).fetchall()
    
    today = date.fromisoformat(as_of_date)
    by_loan = {}
    
    for r in rows:
        if r["outstanding"] <= 0: 
            continue
            
        due = date.fromisoformat(r["due_date"])
        days_overdue = (today - due).days
        
        key = r["loan_no"]
        if key not in by_loan:
            by_loan[key] = {
                "loan_no": r["loan_no"], 
                "client_no": r["client_no"],
                "client_name": f"{r['first_name']} {r['last_name']}", 
                "phone": r["phone"], 
                "location": r["location"] or "",
                "max_days_overdue": 0, 
                "amount_overdue": 0.0,
            }
        
        agg = by_loan[key]
        agg["max_days_overdue"] = max(agg["max_days_overdue"], days_overdue)
        agg["amount_overdue"] += r["outstanding"]

    result = []
    for agg in by_loan.values():
        agg["amount_overdue"] = round(agg["amount_overdue"], 2)
        loan_row = conn.execute("SELECT id FROM loans WHERE loan_no = ?", (agg["loan_no"],)).fetchone()
        outstanding_total = _loan_total_outstanding(conn, loan_row["id"]) if loan_row else agg["amount_overdue"]
        
        agg["outstanding_balance"] = outstanding_total
        agg["aging_bucket"] = _aging_bucket(agg["max_days_overdue"])
        result.append(agg)
        
    result.sort(key=lambda r: r["max_days_overdue"], reverse=True)
    return result

def _loan_total_outstanding(conn, loan_id):
    row = conn.execute(
        """SELECT COALESCE(SUM((principal_due - principal_paid) + (interest_due - interest_paid)
                                 + (penalty_charged - penalty_paid)),0) as t
           FROM repayment_schedule WHERE loan_id = ?""",
        (loan_id,),
    ).fetchone()
    return round(row["t"], 2)


def bad_debts_report(conn, status: str = None):
    return list_bad_debts(conn, status=status)


def disbursement_report(conn, date_from=None, date_to=None):
    query = """SELECT d.*, l.loan_no, l.parent_loan_id, l.maturity_date, l.repayment_frequency,
                      l.interest_method, l.term_months, c.first_name, c.last_name, c.location
               FROM disbursements d
               JOIN loans l ON l.id = d.loan_id
               JOIN clients c ON c.id = l.client_id
               WHERE 1=1"""
    params = []
    if date_from:
        query += " AND d.disbursement_date >= ?"
        params.append(date_from)
    if date_to:
        query += " AND d.disbursement_date <= ?"
        params.append(date_to)
    query += " ORDER BY d.disbursement_date DESC"
    rows = conn.execute(query, params).fetchall()
    result = []
    cash_total = 0
    rollover_total = 0
    cash_count = 0
    for r in rows:
        # A loan's parent_loan_id is set once, at creation, by
        # rollovers.request_rollover() and never changed afterwards - unlike
        # disbursements.method (a separate, editable field that can end up
        # wrong or out of sync). Every RN-numbered loan has parent_loan_id
        # set, so this is the reliable signal for "this was a rollover",
        # regardless of what method actually got stored.
        is_rollover = r["parent_loan_id"] is not None
        display_method = "Rollover" if is_rollover else r["method"]
        if is_rollover:
            rollover_total += r["amount"]
        else:
            cash_total += r["amount"]
            cash_count += 1
        result.append({
            "disbursement_date": r["disbursement_date"],
            "loan_no": r["loan_no"],
            "client_name": f"{r['first_name']} {r['last_name']}",
            "location": r["location"] or "",
            "amount": r["amount"],
            "method": display_method,
            "is_rollover": is_rollover,
            "reference": r["reference"] or "",
            "maturity_date": r["maturity_date"] or "-",
            "repayment_frequency": r["repayment_frequency"] or "-",
            "interest_method": r["interest_method"] or "-",
            "term_months": r["term_months"] or "-",
        })
    # total_disbursed is cash-only (excludes rollovers, same convention as
    # disbursement_location_summary - a rollover isn't new cash out the
    # door, it's a paper re-financing of an existing balance). rollover_total
    # is reported separately so it's still visible, just not counted as cash.
    return {
        "rows": result,
        "total_disbursed": round(cash_total, 2),
        "count": cash_count,
        "rollover_total": round(rollover_total, 2),
        "rollover_count": len(result) - cash_count,
    }

def repayment_report(conn, date_from=None, date_to=None):
    query = """SELECT r.payment_date, r.amount, r.reference, l.loan_no, c.first_name, c.last_name, c.location
               FROM repayments r
               JOIN loans l ON l.id = r.loan_id
               JOIN clients c ON c.id = l.client_id
               WHERE 1=1"""
    params = []
    if date_from:
        query += " AND r.payment_date >= ?"
        params.append(date_from)
    if date_to:
        query += " AND r.payment_date <= ?"
        params.append(date_to)
    query += " ORDER BY r.payment_date DESC, r.id DESC"
    rows = conn.execute(query, params).fetchall()
    result = [{
        "date": r["payment_date"], "loan_no": r["loan_no"],
        "client": f"{r['first_name']} {r['last_name']}",
        "location": r["location"] or "",
        "amount": r["amount"],
        "reference": r["reference"] or "",
    } for r in rows]
    total = round(sum(r["amount"] for r in result), 2)
    return {"rows": result, "total": total, "count": len(result)}


def loan_statements_report(conn, status: str = None):
    query = """SELECT l.*, c.first_name, c.last_name, c.client_no, c.location, c.phone
               FROM loans l JOIN clients c ON c.id = l.client_id WHERE 1=1"""
    params = []
    if status:
        query += " AND l.status = ?"
        params.append(status)
    query += " ORDER BY l.id DESC"
    loans = conn.execute(query, params).fetchall()
    result = []
    for l in loans:
        totals = conn.execute(
            """SELECT COALESCE(SUM(interest_due),0) as interest,
                      COALESCE(SUM(principal_paid + interest_paid + penalty_paid),0) as received,
                      COALESCE(SUM((principal_due - principal_paid) + (interest_due - interest_paid)
                                    + (penalty_charged - penalty_paid)),0) as outstanding
               FROM repayment_schedule WHERE loan_id = ?""",
            (l["id"],),
        ).fetchone()
        result.append({
            "loan_no": l["loan_no"], "client_name": f"{l['first_name']} {l['last_name']}",
            "location": l["location"] or "", "phone": l["phone"] or "",
            "principal": l["principal"], "interest": round(totals["interest"], 2),
            "amount_received": round(totals["received"], 2),
            "outstanding_balance": round(totals["outstanding"], 2),
            "status": l["status"],
        })
    return result


def rollover_report(conn):
    rows = conn.execute(
        """SELECT ro.*, lo.loan_no as original_loan_no, lo.principal as original_principal,
                  ln.loan_no as new_loan_no, c.first_name, c.last_name, c.location, c.phone
           FROM rollovers ro
           JOIN loans lo ON lo.id = ro.original_loan_id
           JOIN loans ln ON ln.id = ro.new_loan_id
           JOIN clients c ON c.id = lo.client_id
           ORDER BY ro.rollover_date DESC"""
    ).fetchall()
    result = []
    for r in rows:
        totals = conn.execute(
            """SELECT COALESCE(SUM(interest_due),0) as interest,
                      COALESCE(SUM(principal_paid + interest_paid + penalty_paid),0) as received
               FROM repayment_schedule WHERE loan_id = ?""",
            (r["original_loan_id"],),
        ).fetchone()
        result.append({
            "client_name": f"{r['first_name']} {r['last_name']}", "location": r["location"] or "",
            "phone": r["phone"] or "", "original_loan_no": r["original_loan_no"],
            "new_loan_no": r["new_loan_no"], "principal": r["original_principal"],
            "interest": round(totals["interest"], 2), "amount_received": round(totals["received"], 2),
            "outstanding_balance": round(r["outstanding_balance"], 2), "rollover_date": r["rollover_date"],
        })
    return result


def portfolio_summary(conn, as_of_date: str = None):
    as_of_date = as_of_date or date.today().isoformat()
    # Only count Active loans that still have a real outstanding balance.
    # Without this, a loan that's fully paid off but never transitioned to
    # 'Closed' (e.g. an edge case that skipped close_loan_if_settled()) would
    # keep inflating this count forever, even though nothing is actually
    # still "running" on it.
    active_loans = conn.execute(
        """SELECT COUNT(*) c FROM loans l
           WHERE l.status = 'Active'
           AND (
               SELECT COALESCE(SUM(
                   (rs.principal_due - rs.principal_paid) +
                   (rs.interest_due - rs.interest_paid) +
                   (rs.penalty_charged - rs.penalty_paid)
               ), 0)
               FROM repayment_schedule rs WHERE rs.loan_id = l.id
           ) > 0.01"""
    ).fetchone()["c"]
    total_clients = conn.execute("SELECT COUNT(*) c FROM clients WHERE status='Active'").fetchone()["c"]
    gross_outstanding = conn.execute(
        """SELECT COALESCE(SUM(principal_due - principal_paid),0) as t
           FROM repayment_schedule rs JOIN loans l ON l.id = rs.loan_id WHERE l.status='Active'"""
    ).fetchone()["t"]
    arrears = arrears_report(conn, as_of_date)
    par_amount = sum(a["amount_overdue"] for a in arrears)
    bad_debts_total = conn.execute(
        "SELECT COALESCE(SUM(amount_written_off),0) as t FROM bad_debts"
    ).fetchone()["t"]
    recoveries_total = conn.execute(
        "SELECT COALESCE(SUM(amount),0) as t FROM bad_debt_recoveries"
    ).fetchone()["t"]
    pending_approval = conn.execute(
        "SELECT COUNT(*) c FROM loans WHERE approval_status='Pending'"
    ).fetchone()["c"]
    return {
        "active_loans": active_loans,
        "active_clients": total_clients,
        "gross_outstanding_principal": round(gross_outstanding, 2),
        "portfolio_at_risk": round(par_amount, 2),
        "par_ratio_pct": round((par_amount / gross_outstanding * 100), 2) if gross_outstanding else 0,
        "bad_debts_written_off": round(bad_debts_total, 2),
        "bad_debts_recovered": round(recoveries_total, 2),
        "pending_approval": pending_approval,
    }


def interest_received_report(conn, date_from=None, date_to=None):
    query = """SELECT r.payment_date, l.loan_no, c.first_name, c.last_name, c.location, 
                      r.interest_paid
               FROM repayments r
               JOIN loans l ON l.id = r.loan_id
               JOIN clients c ON c.id = l.client_id
               WHERE r.interest_paid > 0"""
    params = []
    if date_from:
        query += " AND r.payment_date >= ?"
        params.append(date_from)
    if date_to:
        query += " AND r.payment_date <= ?"
        params.append(date_to)
    query += " ORDER BY r.payment_date DESC"
    rows = conn.execute(query, params).fetchall()
    result = [{
        "date": r["payment_date"],
        "loan_no": r["loan_no"],
        "client": f"{r['first_name']} {r['last_name']}",
        "location": r["location"] or "-",
        "amount": r["interest_paid"],
    } for r in rows]
    total = round(sum(r["amount"] for r in result), 2)
    return {"rows": result, "total": total, "count": len(result)}


def interest_due_report(conn, as_of_date: str = None):
    as_of_date = as_of_date or date.today().isoformat()
    query = """SELECT l.loan_no, c.first_name, c.last_name, c.location,
                      COALESCE(SUM(rs.interest_due - rs.interest_paid), 0) as interest_due
               FROM loans l
               JOIN clients c ON c.id = l.client_id
               JOIN repayment_schedule rs ON rs.loan_id = l.id
               WHERE l.status = 'Active'
               GROUP BY l.id
               HAVING interest_due > 0
               ORDER BY interest_due DESC"""
    rows = conn.execute(query).fetchall()
    result = [{
        "loan_no": r["loan_no"],
        "client": f"{r['first_name']} {r['last_name']}",
        "location": r["location"] or "-",
        "amount": round(r["interest_due"], 2),
    } for r in rows]
    total = round(sum(r["amount"] for r in result), 2)
    return {"rows": result, "total": total, "count": len(result)}


def application_fees_report(conn, date_from=None, date_to=None):
    query = """SELECT f.date_charged, f.amount, f.status, l.loan_no,
                      c.first_name, c.last_name, c.location
               FROM fees f
               JOIN loans l ON l.id = f.loan_id
               JOIN clients c ON c.id = l.client_id
               WHERE f.fee_type = 'Application'"""
    params = []
    if date_from:
        query += " AND f.date_charged >= ?"
        params.append(date_from)
    if date_to:
        query += " AND f.date_charged <= ?"
        params.append(date_to)
    query += " ORDER BY f.date_charged DESC"
    rows = conn.execute(query, params).fetchall()
    result = [{
        "date": r["date_charged"], "loan_no": r["loan_no"],
        "client": f"{r['first_name']} {r['last_name']}", "location": r["location"] or "-",
        "amount": round(r["amount"], 2), "status": r["status"],
    } for r in rows]
    total = round(sum(r["amount"] for r in result), 2)
    return {"rows": result, "total": total, "count": len(result)}


def admin_fees_report(conn, date_from=None, date_to=None):
    query = """SELECT COALESCE(l.disbursement_date, l.application_date) as fee_date, 
                      l.loan_no, c.first_name, c.last_name, c.location,
                      l.admin_fee as amount
               FROM loans l
               JOIN clients c ON c.id = l.client_id
               WHERE l.admin_fee > 0"""
    params = []
    if date_from:
        query += " AND COALESCE(l.disbursement_date, l.application_date) >= ?"
        params.append(date_from)
    if date_to:
        query += " AND COALESCE(l.disbursement_date, l.application_date) <= ?"
        params.append(date_to)
    query += " ORDER BY fee_date DESC"
    rows = conn.execute(query, params).fetchall()
    result = [{
        "date": r["fee_date"],
        "loan_no": r["loan_no"],
        "client": f"{r['first_name']} {r['last_name']}",
        "location": r["location"] or "-",
        "amount": round(r["amount"], 2),
    } for r in rows]
    total = round(sum(r["amount"] for r in result), 2)
    return {"rows": result, "total": total, "count": len(result)}


def clients_due_per_day_report(conn, due_date: str):
    query = """SELECT rs.due_date, l.loan_no, c.first_name, c.last_name, c.location,
                      (rs.principal_due + rs.interest_due + rs.penalty_charged) as amount,
                      rs.installment_no, c.phone
               FROM repayment_schedule rs
               JOIN loans l ON l.id = rs.loan_id
               JOIN clients c ON c.id = l.client_id
               WHERE rs.due_date = ? AND rs.status != 'Paid' AND l.status = 'Active'
               ORDER BY c.last_name ASC"""
    rows = conn.execute(query, (due_date,)).fetchall()
    result = [{
        "date": r["due_date"],
        "loan_no": r["loan_no"],
        "client": f"{r['first_name']} {r['last_name']}",
        "location": r["location"] or "-",
        "amount": round(r["amount"], 2),
        "installment_no": r["installment_no"],
        "contact": r["phone"] or "-",
    } for r in rows]
    total = round(sum(r["amount"] for r in result), 2)
    return {"rows": result, "total": total, "count": len(result)}


def expected_collections_report(conn, as_of_date: str = None):
    """
    What a loan officer should expect to collect as of a given date: every
    not-yet-fully-paid installment with a due date on or before as_of_date
    (i.e. everything overdue, plus whatever falls due that day), for active
    loans. Aggregated to one row per loan showing the total still
    outstanding across those installments - not the original scheduled
    amount, so any partial payments already made are already netted out.
    """
    as_of_date = as_of_date or date.today().isoformat()
    query = """SELECT rs.loan_id, rs.due_date,
                      rs.principal_due, rs.principal_paid,
                      rs.interest_due, rs.interest_paid,
                      rs.penalty_charged, rs.penalty_paid,
                      l.loan_no, c.first_name, c.last_name, c.location, c.phone
               FROM repayment_schedule rs
               JOIN loans l ON l.id = rs.loan_id
               JOIN clients c ON c.id = l.client_id
               WHERE rs.due_date <= ? AND rs.status != 'Paid' AND l.status = 'Active'
               ORDER BY c.last_name ASC, rs.due_date ASC"""
    rows = conn.execute(query, (as_of_date,)).fetchall()

    by_loan = {}
    for r in rows:
        remaining = round(
            (r["principal_due"] - r["principal_paid"])
            + (r["interest_due"] - r["interest_paid"])
            + (r["penalty_charged"] - r["penalty_paid"]),
            2,
        )
        if remaining <= 0.01:
            continue  # nothing actually still owed on this installment
        loan_id = r["loan_id"]
        if loan_id not in by_loan:
            by_loan[loan_id] = {
                "loan_no": r["loan_no"],
                "client": f"{r['first_name']} {r['last_name']}",
                "location": r["location"] or "-",
                "contact": r["phone"] or "-",
                "oldest_due_date": r["due_date"],
                "installments_due": 0,
                "amount": 0.0,
            }
        entry = by_loan[loan_id]
        entry["installments_due"] += 1
        entry["amount"] = round(entry["amount"] + remaining, 2)
        if r["due_date"] < entry["oldest_due_date"]:
            entry["oldest_due_date"] = r["due_date"]

    result = sorted(by_loan.values(), key=lambda e: e["client"])
    total = round(sum(r["amount"] for r in result), 2)
    return {"rows": result, "total": total, "count": len(result)}


# ----- NEW: Rollover Fee Report -----
def rollover_fee_report(conn, date_from=None, date_to=None):
    """List of rollover fees charged, with date range filtering."""
    query = """SELECT f.date_charged, f.amount, f.description, f.status,
                      l.loan_no, c.first_name, c.last_name, c.location
               FROM fees f
               JOIN loans l ON l.id = f.loan_id
               JOIN clients c ON c.id = l.client_id
               WHERE f.fee_type = 'Rollover'"""
    params = []
    if date_from:
        query += " AND f.date_charged >= ?"
        params.append(date_from)
    if date_to:
        query += " AND f.date_charged <= ?"
        params.append(date_to)
    query += " ORDER BY f.date_charged DESC"
    rows = conn.execute(query, params).fetchall()
    result = [{
        "date": r["date_charged"],
        "loan_no": r["loan_no"],
        "client": f"{r['first_name']} {r['last_name']}",
        "location": r["location"] or "-",
        "amount": round(r["amount"], 2),
        "status": r["status"],
        "description": r["description"] or "",
    } for r in rows]
    total = round(sum(r["amount"] for r in result), 2)
    return {"rows": result, "total": total, "count": len(result)}

def location_performance(conn, as_of_date: str = None):
    """
    Group key performance indicators by client location.
    Returns a list of dicts for each location with at least one active loan.
    """
    as_of_date = as_of_date or date.today().isoformat()

    # Main query: active clients, active loans, outstanding balance per location
    query = """
        SELECT
            COALESCE(c.location, 'Unknown') AS location,
            COUNT(DISTINCT c.id) AS active_clients,
            COUNT(DISTINCT l.id) AS active_loans,
            COALESCE(SUM(
                (rs.principal_due - rs.principal_paid) +
                (rs.interest_due - rs.interest_paid) +
                (rs.penalty_charged - rs.penalty_paid)
            ), 0) AS outstanding_principal
        FROM clients c
        JOIN loans l ON l.client_id = c.id AND l.status = 'Active'
            AND (
                SELECT COALESCE(SUM(
                    (rs2.principal_due - rs2.principal_paid) +
                    (rs2.interest_due - rs2.interest_paid) +
                    (rs2.penalty_charged - rs2.penalty_paid)
                ), 0)
                FROM repayment_schedule rs2 WHERE rs2.loan_id = l.id
            ) > 0.01
        LEFT JOIN repayment_schedule rs ON rs.loan_id = l.id
        GROUP BY COALESCE(c.location, 'Unknown')
        ORDER BY outstanding_principal DESC
    """
    rows = conn.execute(query).fetchall()

    # Arrears report (per loan overdue amount)
    arrears = arrears_report(conn, as_of_date)
    overdue_by_loan = {a["loan_no"]: a["amount_overdue"] for a in arrears}

    result = []
    for r in rows:
        location = r["location"]
        outstanding = round(r["outstanding_principal"], 2)

        # Get loans for this location to sum PAR
        loans = conn.execute(
            """SELECT loan_no FROM loans l
               JOIN clients c ON c.id = l.client_id
               WHERE COALESCE(c.location, 'Unknown') = ? AND l.status = 'Active'""",
            (location,)
        ).fetchall()
        par_amount = round(sum(overdue_by_loan.get(l["loan_no"], 0) for l in loans), 2)
        par_ratio = round((par_amount / outstanding * 100), 2) if outstanding else 0

        result.append({
            "location": location,
            "active_clients": r["active_clients"],
            "active_loans": r["active_loans"],
            "outstanding_principal": outstanding,
            "par_amount": par_amount,
            "par_ratio": par_ratio,
        })

    return result

def bad_debts_recovery_report(conn, date_from=None, date_to=None):
    """Report tracking funds successfully recovered from previously written-off loans."""
    query = """SELECT bdr.recovery_date, bdr.amount, bdr.reference, 
                      bd.date_written_off, bd.amount_written_off,
                      l.loan_no, c.first_name, c.last_name, c.location
               FROM bad_debt_recoveries bdr
               JOIN bad_debts bd ON bd.id = bdr.bad_debt_id
               JOIN loans l ON l.id = bd.loan_id
               JOIN clients c ON c.id = l.client_id
               WHERE 1=1"""
    params = []
    
    if date_from:
        query += " AND bdr.recovery_date >= ?"
        params.append(date_from)
    if date_to:
        query += " AND bdr.recovery_date <= ?"
        params.append(date_to)
        
    query += " ORDER BY bdr.recovery_date DESC"
    
    rows = conn.execute(query, params).fetchall()
    
    result = [{
        "recovery_date": r["recovery_date"],
        "loan_no": r["loan_no"],
        "client": f"{r['first_name']} {r['last_name']}",
        "location": r["location"] or "-",
        "amount_recovered": round(r["amount"], 2),
        "reference": r["reference"] or "-",
        "date_written_off": r["date_written_off"],
        "amount_written_off": round(r["amount_written_off"], 2)
    } for r in rows]
    
    total_recovered = round(sum(r["amount_recovered"] for r in result), 2)
    
    return {
        "rows": result, 
        "total": total_recovered, 
        "count": len(result)
    }


# =====================================================================
# LOCATION x PERIOD SUMMARY REPORT
# (Disbursements / Repayment Collections / Bad Debt Recovery / Expenses
#  broken down per location, per day/week/month - modelled on the
#  branch-performance sheet used for management reporting.)
# =====================================================================

def _period_bucket(d: date, period: str):
    """Return (sort_key, display_label) for the period bucket a date falls into."""
    if period == "daily":
        return d.isoformat(), d.strftime("%d %b %Y")
    if period == "weekly":
        monday = d - timedelta(days=d.weekday())
        return monday.isoformat(), f"Wk of {monday.strftime('%d %b %Y')}"
    # monthly (default)
    return f"{d.year:04d}-{d.month:02d}", d.strftime("%b-%y")


def _pivot_by_location(entries, period: str):
    """
    entries: iterable of (location, date_str, amount).
    Returns {"columns": [(key,label),...], "rows": [...], "totals_row": {...}}
    ready to hand straight to a DataTable, with a Location column, one
    column per period bucket (in chronological order), and a Total column.
    """
    bucket_labels = {}
    by_location = {}

    for location, date_str, amount in entries:
        if not date_str:
            continue
        loc = location or "Unknown"
        key, label = _period_bucket(date.fromisoformat(date_str), period)
        bucket_labels[key] = label
        by_location.setdefault(loc, {})
        by_location[loc][key] = round(by_location[loc].get(key, 0.0) + amount, 2)

    sorted_keys = sorted(bucket_labels.keys())
    columns = [("location", "Location")] + [(k, bucket_labels[k]) for k in sorted_keys] + [("total", "Total")]

    rows = []
    totals_row = {"location": "TOTAL"}
    for k in sorted_keys:
        totals_row[k] = 0.0
    totals_row["total"] = 0.0

    for loc in sorted(by_location.keys()):
        row = {"location": loc}
        row_total = 0.0
        for k in sorted_keys:
            v = round(by_location[loc].get(k, 0.0), 2)
            row[k] = v
            row_total += v
            totals_row[k] = round(totals_row[k] + v, 2)
        row["total"] = round(row_total, 2)
        totals_row["total"] = round(totals_row["total"] + row["total"], 2)
        rows.append(row)

    return {"columns": columns, "rows": rows, "totals_row": totals_row}


def _pivot_by_location_split(entries, period: str):
    """
    Same idea as _pivot_by_location, but each period bucket is split into two
    columns - one for loans NOT originating from a rollover (LN) and one for
    loans that ARE the result of a rollover (RN) - so the two never get
    blended into a single figure.

    entries: iterable of (location, date_str, amount, category) where
             category is "LN" or "RN".
    Returns {"columns": [...], "rows": [...], "totals_row": {...}}.
    """
    bucket_labels = {}
    by_location = {}  # loc -> {(key, category): amount}

    for location, date_str, amount, category in entries:
        if not date_str:
            continue
        loc = location or "Unknown"
        key, label = _period_bucket(date.fromisoformat(date_str), period)
        bucket_labels[key] = label
        by_location.setdefault(loc, {})
        cell = (key, category)
        by_location[loc][cell] = round(by_location[loc].get(cell, 0.0) + amount, 2)

    sorted_keys = sorted(bucket_labels.keys())

    columns = [("location", "Location")]
    for k in sorted_keys:
        columns.append((f"{k}__LN", f"{bucket_labels[k]} (LN)"))
        columns.append((f"{k}__RN", f"{bucket_labels[k]} (RN)"))
    columns += [("total_ln", "Total (LN)"), ("total_rn", "Total (RN)"), ("total", "Total")]

    rows = []
    totals_row = {"location": "TOTAL"}
    for k in sorted_keys:
        totals_row[f"{k}__LN"] = 0.0
        totals_row[f"{k}__RN"] = 0.0
    totals_row["total_ln"] = 0.0
    totals_row["total_rn"] = 0.0
    totals_row["total"] = 0.0

    for loc in sorted(by_location.keys()):
        row = {"location": loc}
        row_total_ln = row_total_rn = 0.0
        for k in sorted_keys:
            v_ln = round(by_location[loc].get((k, "LN"), 0.0), 2)
            v_rn = round(by_location[loc].get((k, "RN"), 0.0), 2)
            row[f"{k}__LN"] = v_ln
            row[f"{k}__RN"] = v_rn
            row_total_ln += v_ln
            row_total_rn += v_rn
            totals_row[f"{k}__LN"] = round(totals_row[f"{k}__LN"] + v_ln, 2)
            totals_row[f"{k}__RN"] = round(totals_row[f"{k}__RN"] + v_rn, 2)
        row["total_ln"] = round(row_total_ln, 2)
        row["total_rn"] = round(row_total_rn, 2)
        row["total"] = round(row_total_ln + row_total_rn, 2)
        totals_row["total_ln"] = round(totals_row["total_ln"] + row["total_ln"], 2)
        totals_row["total_rn"] = round(totals_row["total_rn"] + row["total_rn"], 2)
        totals_row["total"] = round(totals_row["total"] + row["total"], 2)
        rows.append(row)

    return {"columns": columns, "rows": rows, "totals_row": totals_row}


def disbursement_location_summary(conn, period: str = "monthly", date_from=None, date_to=None):
    """Cash disbursed per location per period. Excludes rollover disbursements
    (identified by l.parent_loan_id being set - see disbursement_report for
    why that's used instead of d.method), since those aren't new cash out
    the door."""
    query = """SELECT c.location, d.disbursement_date, d.amount
               FROM disbursements d
               JOIN loans l ON l.id = d.loan_id
               JOIN clients c ON c.id = l.client_id
               WHERE l.parent_loan_id IS NULL"""
    params = []
    if date_from:
        query += " AND d.disbursement_date >= ?"
        params.append(date_from)
    if date_to:
        query += " AND d.disbursement_date <= ?"
        params.append(date_to)
    rows = conn.execute(query, params).fetchall()
    entries = [(r["location"], r["disbursement_date"], r["amount"]) for r in rows]
    return _pivot_by_location(entries, period)


def repayment_location_summary(conn, period: str = "monthly", date_from=None, date_to=None):
    """
    Repayment collections per location per period, with loans that are NOT
    the result of a rollover (LN) and loans that ARE (RN) shown in separate
    columns rather than blended into one figure.
    """
    query = """SELECT c.location, r.payment_date, r.amount, l.parent_loan_id
               FROM repayments r
               JOIN loans l ON l.id = r.loan_id
               JOIN clients c ON c.id = l.client_id
               WHERE 1=1"""
    params = []
    if date_from:
        query += " AND r.payment_date >= ?"
        params.append(date_from)
    if date_to:
        query += " AND r.payment_date <= ?"
        params.append(date_to)
    rows = conn.execute(query, params).fetchall()

    entries = []
    for r in rows:
        category = "RN" if r["parent_loan_id"] is not None else "LN"
        entries.append((r["location"], r["payment_date"], r["amount"], category))
    return _pivot_by_location_split(entries, period)


def bad_debt_recovery_location_summary(conn, period: str = "monthly", date_from=None, date_to=None):
    """Bad debt recoveries per location per period, split into LN vs RN
    columns depending on whether the written-off loan was itself the
    result of a rollover."""
    query = """SELECT c.location, bdr.recovery_date, bdr.amount, l.parent_loan_id
               FROM bad_debt_recoveries bdr
               JOIN bad_debts bd ON bd.id = bdr.bad_debt_id
               JOIN loans l ON l.id = bd.loan_id
               JOIN clients c ON c.id = l.client_id
               WHERE 1=1"""
    params = []
    if date_from:
        query += " AND bdr.recovery_date >= ?"
        params.append(date_from)
    if date_to:
        query += " AND bdr.recovery_date <= ?"
        params.append(date_to)
    rows = conn.execute(query, params).fetchall()
    entries = []
    for r in rows:
        category = "RN" if r["parent_loan_id"] is not None else "LN"
        entries.append((r["location"], r["recovery_date"], r["amount"], category))
    return _pivot_by_location_split(entries, period)


def expenses_period_summary(conn, period: str = "monthly", date_from=None, date_to=None):
    """
    Expenses per period. NOTE: the `expenses` table has no location column,
    so this cannot be split by branch/location the way the other three
    reports are - everything is rolled up under a single "All Locations"
    row. If per-branch expense tracking is needed, a location column would
    need to be added to expenses (and to record_expense()).
    """
    query = "SELECT expense_date, amount FROM expenses WHERE 1=1"
    params = []
    if date_from:
        query += " AND expense_date >= ?"
        params.append(date_from)
    if date_to:
        query += " AND expense_date <= ?"
        params.append(date_to)
    rows = conn.execute(query, params).fetchall()
    entries = [("All Locations", r["expense_date"], r["amount"]) for r in rows]
    return _pivot_by_location(entries, period)


def location_activity_summary(conn, period: str = "monthly", date_from=None, date_to=None):
    """
    Bundled report with the sections actually needed for branch reporting:
    Disbursements (real cash out, rollovers excluded), Loan Collections
    (repayments, with non-rollover "LN" loans and rollover-originated "RN"
    loans shown in separate columns), and Bad Debt Recovery (also split
    LN vs RN) - each already pivoted by location x period, ready for
    display/export.
    """
    return {
        "disbursements": disbursement_location_summary(conn, period, date_from, date_to),
        "loan_collections": repayment_location_summary(conn, period, date_from, date_to),
        "bad_debt_recovery": bad_debt_recovery_location_summary(conn, period, date_from, date_to),
    }

def fund_position_report(conn, as_of_date=None):
    from datetime import date
    as_of_date = as_of_date or date.today().isoformat()

    # 1. Get Liquid Cash Balance (Account 1000)
    cash_row = conn.execute(
        """SELECT COALESCE(SUM(jl.debit) - SUM(jl.credit), 0) as balance
           FROM journal_lines jl
           JOIN journal_entries je ON je.id = jl.journal_entry_id
           JOIN accounts a ON a.id = jl.account_id
           WHERE a.code = '1000' AND je.entry_date <= ?""", (as_of_date,)
    ).fetchone()
    cash_balance = cash_row["balance"] if cash_row else 0.0

    # 2. Get Outstanding Loan Principal (Account 1100)
    loan_row = conn.execute(
        """SELECT COALESCE(SUM(jl.debit) - SUM(jl.credit), 0) as balance
           FROM journal_lines jl
           JOIN journal_entries je ON je.id = jl.journal_entry_id
           JOIN accounts a ON a.id = jl.account_id
           WHERE a.code = '1100' AND je.entry_date <= ?""", (as_of_date,)
    ).fetchone()
    loan_balance = loan_row["balance"] if loan_row else 0.0

    # 3. Get Expected Interest Receivable (Unpaid interest on Active loans)
    interest_row = conn.execute(
        """SELECT COALESCE(SUM(rs.interest_due - rs.interest_paid), 0) as expected_interest
           FROM repayment_schedule rs
           JOIN loans l ON l.id = rs.loan_id
           WHERE l.status = 'Active'"""
    ).fetchone()
    interest_receivable = interest_row["expected_interest"] if interest_row else 0.0

    # 4. Get Pending Disbursements (submitted loans awaiting a decision).
    # Approval and disbursement happen in a single step in this system, so a
    # loan is never left sitting as approval_status='Approved' with
    # status='Pending' - it goes straight to 'Active' once approved. The
    # amount that will actually leave the fund once these are decided on is
    # the full set of submitted applications still awaiting a decision,
    # i.e. status='Pending', excluding any that have already been declined.
    pending_row = conn.execute(
        """SELECT COALESCE(SUM(principal), 0) as pending_amount
           FROM loans
           WHERE status = 'Pending' AND approval_status != 'Declined'"""
    ).fetchone()
    pending_disbursements = pending_row["pending_amount"] if pending_row else 0.0

    # 5. Calculate Totals
    current_fund_capital = cash_balance + loan_balance
    projected_fund_value = current_fund_capital + interest_receivable
    # Net Available Liquidity is cash on hand only - pending applications are
    # not yet a committed liability (some will be declined), so they're
    # reported separately as an informational figure rather than netted out.
    available_liquidity = cash_balance
    # Secondary, more conservative view: liquidity if every pending
    # application were approved and disbursed.
    liquidity_after_pipeline = cash_balance - pending_disbursements

    return {
        "as_of_date": as_of_date,
        "cash_balance": cash_balance,
        "loan_balance": loan_balance,
        "interest_receivable": interest_receivable,
        "current_fund_capital": current_fund_capital,
        "projected_fund_value": projected_fund_value,
        "pending_disbursements": pending_disbursements,
        "available_liquidity": available_liquidity,
        "liquidity_after_pipeline": liquidity_after_pipeline
    }