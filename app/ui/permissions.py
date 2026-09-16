"""
Per-user, per-module, per-action access rights ("give users access rights" screen).

Admins always have full access to every module/action regardless of what's
stored here - permissions only restrict non-admin users. "Dashboard"
(read-only landing page) and "Users" (admin-only user/permission management)
are intentionally not toggleable here: Dashboard is available to everyone
who can log in, and Users stays admin-only no matter what.

Each module has four independent action flags:
  - view:    can the user see this module/screen at all (drives the sidebar)
  - edit:    can the user edit existing records in this module
  - delete:  can the user delete/deactivate records in this module
  - approve: can the user approve/decline (loan approvals, etc.)

Not every action is meaningful for every module (e.g. "Approve" mainly
matters for Loans), but all four are exposed uniformly in the Users screen
for simplicity - unused ones just have no effect anywhere.
"""

MODULES = ["Clients", "Loans", "Rollovers", "Bad Debts", "Reports", "Accounting"]
ACTIONS = ["view", "edit", "delete", "approve"]


def get_permissions(conn, user_id: int) -> dict:
    """Returns {module: {action: True/False}} for every module/action."""
    rows = conn.execute(
        "SELECT module, action, allowed FROM permissions WHERE user_id = ?", (user_id,)
    ).fetchall()
    granted = {(r["module"], r["action"]) for r in rows if r["allowed"]}
    return {m: {a: ((m, a) in granted) for a in ACTIONS} for m in MODULES}


def set_permissions(conn, user_id: int, data: dict):
    """data: {module: {action: True/False}}. Only known modules/actions are stored."""
    for module in MODULES:
        action_flags = data.get(module, {})
        for action in ACTIONS:
            allowed = 1 if action_flags.get(action) else 0
            conn.execute(
                """INSERT INTO permissions (user_id, module, action, allowed) VALUES (?,?,?,?)
                   ON CONFLICT(user_id, module, action) DO UPDATE SET allowed = excluded.allowed""",
                (user_id, module, action, allowed),
            )
    conn.commit()


def has_permission(conn, user: dict, module: str, action: str = "view") -> bool:
    """True if the given user (dict with at least 'id' and 'role') can perform
    `action` ('view'/'edit'/'delete'/'approve') on `module`."""
    if user is None:
        return False
    if user.get("role") == "admin":
        return True
    row = conn.execute(
        "SELECT allowed FROM permissions WHERE user_id = ? AND module = ? AND action = ?",
        (user["id"], module, action),
    ).fetchone()
    return bool(row and row["allowed"])
