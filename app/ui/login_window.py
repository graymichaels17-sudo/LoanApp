import customtkinter as ctk
from ..database import get_connection
from ..auth import Session, AuthError, get_security_question, reset_password_with_security_answer, hash_password
from .. import config
from .widgets import NAVY_DEEP, NAVY_MID, NAVY_BORDER, BLUE_ACCENT, BLUE_HOVER, BLUE_LIGHT, TEXT_PRIMARY, TEXT_MUTED, TEXT_DIM

DANGER = "#EF5350"
SUCCESS = "#66BB6A"


class LoginFrame(ctk.CTkFrame):
    def __init__(self, master):
        super().__init__(master, fg_color=NAVY_DEEP)

        container = ctk.CTkFrame(self, corner_radius=20, fg_color=NAVY_MID,
                                  border_width=1, border_color=NAVY_BORDER)
        container.pack(expand=True, fill="both", padx=30, pady=30)

        ctk.CTkLabel(container, text="💎", font=("Segoe UI", 32)).pack(pady=(28, 0))
        ctk.CTkLabel(container, text=config.APP_NAME, font=("Segoe UI", 22, "bold"),
                     text_color=BLUE_LIGHT).pack(pady=(4, 4))
        ctk.CTkLabel(container, text="Offline Microfinance Management",
                     font=("Segoe UI", 12), text_color=TEXT_MUTED).pack(pady=(0, 28))

        self.username_var = ctk.StringVar()
        self.password_var = ctk.StringVar()

        entry_kwargs = dict(fg_color=NAVY_DEEP, border_color=NAVY_BORDER,
                             text_color=TEXT_PRIMARY, placeholder_text_color=TEXT_DIM)

        ctk.CTkLabel(container, text="Username", font=("Segoe UI", 12),
                     text_color=TEXT_MUTED).pack(anchor="w", padx=40)
        username_entry = ctk.CTkEntry(container, textvariable=self.username_var, width=280, **entry_kwargs)
        username_entry.pack(pady=(4, 14))

        ctk.CTkLabel(container, text="Password", font=("Segoe UI", 12),
                     text_color=TEXT_MUTED).pack(anchor="w", padx=40)
        password_entry = ctk.CTkEntry(container, textvariable=self.password_var, show="*",
                                       width=280, **entry_kwargs)
        password_entry.pack(pady=(4, 6))

        self.error_label = ctk.CTkLabel(container, text="", text_color=DANGER, font=("Segoe UI", 11))
        self.error_label.pack(pady=(4, 10))

        ctk.CTkButton(container, text="Log In", width=280, height=40, font=("Segoe UI", 14, "bold"),
                      fg_color=BLUE_ACCENT, hover_color=BLUE_HOVER,
                      command=self._attempt_login).pack(pady=6)

        # ---- Bottom links ----
        link_frame = ctk.CTkFrame(container, fg_color="transparent")
        link_frame.pack(pady=(0, 6))

        forgot_link = ctk.CTkButton(
            link_frame, text="Forgot password?", fg_color="transparent", hover_color=NAVY_BORDER,
            text_color=BLUE_LIGHT, width=140, height=24, font=("Segoe UI", 11),
            command=self._open_forgot_password,
        )
        forgot_link.pack(side="left", padx=6)

        change_pwd_link = ctk.CTkButton(
            link_frame, text="Change Password", fg_color="transparent", hover_color=NAVY_BORDER,
            text_color=BLUE_LIGHT, width=140, height=24, font=("Segoe UI", 11),
            command=self._open_change_password,
        )
        change_pwd_link.pack(side="left", padx=6)

        ctk.CTkLabel(
            container,
            text="Built by GrayT",
            font=("Segoe UI", 10),
            text_color=TEXT_DIM,
        ).pack(side="bottom", pady=10)

        username_entry.bind("<Return>", lambda e: self._attempt_login())
        password_entry.bind("<Return>", lambda e: self._attempt_login())

    def _attempt_login(self):
        conn = get_connection()
        try:
            user = Session.login(conn, self.username_var.get().strip(), self.password_var.get())
            self.master.show_main(user)
        except AuthError as e:
            self.error_label.configure(text=str(e))
        finally:
            conn.close()

    def _open_forgot_password(self):
        ForgotPasswordDialog(self, prefill_username=self.username_var.get().strip())

    def _open_change_password(self):
        ChangePasswordDialog(self, prefill_username=self.username_var.get().strip())


class ForgotPasswordDialog(ctk.CTkToplevel):
    """
    Two-step self-service reset: look up the account's security question,
    then verify the answer and set a new password - all offline, no email
    server involved. If no question is set for the account, points the
    person to an administrator instead (who can reset it directly from the
    Users screen).
    """

    def __init__(self, master, prefill_username: str = ""):
        super().__init__(master)
        self.title("Forgot Password")
        self.geometry("380x480")
        self.resizable(False, True)
        self.configure(fg_color=NAVY_DEEP)
        self.transient(master)
        self.grab_set()

        self.username = None

        self.container = ctk.CTkFrame(self, fg_color="transparent")
        self.container.pack(expand=True, fill="both", padx=24, pady=20)

        self._build_step_username(prefill_username)

    def _clear(self):
        for w in self.container.winfo_children():
            w.destroy()

    def _build_step_username(self, prefill=""):
        self._clear()
        ctk.CTkLabel(self.container, text="Reset Your Password", font=("Segoe UI", 16, "bold"),
                     text_color=BLUE_LIGHT).pack(pady=(0, 14))
        ctk.CTkLabel(self.container, text="Username", text_color=TEXT_MUTED).pack(anchor="w")
        username_var = ctk.StringVar(value=prefill)
        entry = ctk.CTkEntry(self.container, textvariable=username_var, width=300,
                              fg_color=NAVY_MID, border_color=NAVY_BORDER, text_color=TEXT_PRIMARY)
        entry.pack(pady=(2, 14))

        self.msg_label = ctk.CTkLabel(self.container, text="", text_color=DANGER, wraplength=300)
        self.msg_label.pack(pady=(0, 6))

        def find_account():
            uname = username_var.get().strip()
            if not uname:
                self.msg_label.configure(text="Enter your username.")
                return
            conn = get_connection()
            try:
                question = get_security_question(conn, uname)
            finally:
                conn.close()
            if question is None:
                self.msg_label.configure(
                    text="No recovery question is set up for this account. "
                         "Please ask an administrator to reset your password."
                )
                return
            self.username = uname
            self._build_step_answer(question)

        ctk.CTkButton(self.container, text="Continue", width=300, fg_color=BLUE_ACCENT,
                      hover_color=BLUE_HOVER, command=find_account).pack(pady=6)
        entry.bind("<Return>", lambda e: find_account())
        entry.focus_set()

    def _build_step_answer(self, question: str):
        self._clear()
        ctk.CTkLabel(self.container, text="Security Question", font=("Segoe UI", 16, "bold"),
                     text_color=BLUE_LIGHT).pack(pady=(0, 6))
        ctk.CTkLabel(self.container, text=question, wraplength=300, font=("Segoe UI", 12, "italic"),
                     text_color=TEXT_PRIMARY).pack(pady=(0, 14))

        entry_kwargs = dict(fg_color=NAVY_MID, border_color=NAVY_BORDER, text_color=TEXT_PRIMARY)

        ctk.CTkLabel(self.container, text="Your Answer", text_color=TEXT_MUTED).pack(anchor="w")
        answer_var = ctk.StringVar()
        answer_entry = ctk.CTkEntry(self.container, textvariable=answer_var, width=300, **entry_kwargs)
        answer_entry.pack(pady=(2, 10))

        ctk.CTkLabel(self.container, text="New Password", text_color=TEXT_MUTED).pack(anchor="w")
        new_pwd_var = ctk.StringVar()
        new_pwd_entry = ctk.CTkEntry(self.container, textvariable=new_pwd_var, show="*", width=300, **entry_kwargs)
        new_pwd_entry.pack(pady=(2, 10))

        ctk.CTkLabel(self.container, text="Confirm New Password", text_color=TEXT_MUTED).pack(anchor="w")
        confirm_pwd_var = ctk.StringVar()
        confirm_pwd_entry = ctk.CTkEntry(self.container, textvariable=confirm_pwd_var, show="*",
                                          width=300, **entry_kwargs)
        confirm_pwd_entry.pack(pady=(2, 10))

        self.msg_label = ctk.CTkLabel(self.container, text="", text_color=DANGER, wraplength=300)
        self.msg_label.pack(pady=(0, 4))

        def submit():
            if new_pwd_var.get() != confirm_pwd_var.get():
                self.msg_label.configure(text="New password and confirmation don't match.", text_color=DANGER)
                return
            conn = get_connection()
            try:
                reset_password_with_security_answer(
                    conn, self.username, answer_var.get(), new_pwd_var.get()
                )
            except AuthError as e:
                self.msg_label.configure(text=str(e), text_color=DANGER)
                return
            finally:
                conn.close()
            self.msg_label.configure(text="Password reset. You can now log in.", text_color=SUCCESS)
            self.after(1200, self.destroy)

        ctk.CTkButton(self.container, text="Reset Password", width=300, fg_color=BLUE_ACCENT,
                      hover_color=BLUE_HOVER, command=submit).pack(pady=6)
        answer_entry.focus_set()


class ChangePasswordDialog(ctk.CTkToplevel):
    """
    Dialog for changing a user's password on the login screen.
    Requires username, old password, new password, and confirmation.
    """

    def __init__(self, master, prefill_username: str = ""):
        super().__init__(master)
        self.title("Change Password")
        self.geometry("380x420")
        self.resizable(False, True)
        self.configure(fg_color=NAVY_DEEP)
        self.transient(master)
        self.grab_set()

        self.container = ctk.CTkFrame(self, fg_color="transparent")
        self.container.pack(expand=True, fill="both", padx=24, pady=20)

        ctk.CTkLabel(self.container, text="Change Password", font=("Segoe UI", 16, "bold"),
                     text_color=BLUE_LIGHT).pack(pady=(0, 14))

        entry_kwargs = dict(fg_color=NAVY_MID, border_color=NAVY_BORDER, text_color=TEXT_PRIMARY)

        # Username
        ctk.CTkLabel(self.container, text="Username", text_color=TEXT_MUTED).pack(anchor="w")
        self.username_var = ctk.StringVar(value=prefill_username)
        username_entry = ctk.CTkEntry(self.container, textvariable=self.username_var, width=300, **entry_kwargs)
        username_entry.pack(pady=(2, 10))

        # Old Password
        ctk.CTkLabel(self.container, text="Current Password", text_color=TEXT_MUTED).pack(anchor="w")
        self.old_pwd_var = ctk.StringVar()
        old_pwd_entry = ctk.CTkEntry(self.container, textvariable=self.old_pwd_var, show="*", width=300, **entry_kwargs)
        old_pwd_entry.pack(pady=(2, 10))

        # New Password
        ctk.CTkLabel(self.container, text="New Password", text_color=TEXT_MUTED).pack(anchor="w")
        self.new_pwd_var = ctk.StringVar()
        new_pwd_entry = ctk.CTkEntry(self.container, textvariable=self.new_pwd_var, show="*", width=300, **entry_kwargs)
        new_pwd_entry.pack(pady=(2, 10))

        # Confirm New Password
        ctk.CTkLabel(self.container, text="Confirm New Password", text_color=TEXT_MUTED).pack(anchor="w")
        self.confirm_pwd_var = ctk.StringVar()
        confirm_pwd_entry = ctk.CTkEntry(self.container, textvariable=self.confirm_pwd_var, show="*", width=300, **entry_kwargs)
        confirm_pwd_entry.pack(pady=(2, 10))

        self.msg_label = ctk.CTkLabel(self.container, text="", text_color=DANGER, wraplength=300)
        self.msg_label.pack(pady=(6, 0))

        # Buttons
        btn_frame = ctk.CTkFrame(self.container, fg_color="transparent")
        btn_frame.pack(fill="x", pady=(14, 0))

        ctk.CTkButton(btn_frame, text="Cancel", fg_color=NAVY_BORDER, hover_color=TEXT_DIM,
                      command=self.destroy).pack(side="right", padx=4)
        ctk.CTkButton(btn_frame, text="Change Password", fg_color=BLUE_ACCENT, hover_color=BLUE_HOVER,
                      command=self._submit).pack(side="right", padx=4)

        old_pwd_entry.focus_set()

    def _submit(self):
        username = self.username_var.get().strip()
        old_pwd = self.old_pwd_var.get()
        new_pwd = self.new_pwd_var.get()
        confirm_pwd = self.confirm_pwd_var.get()

        # Validate inputs
        if not username:
            self.msg_label.configure(text="Username is required.", text_color=DANGER)
            return
        if not old_pwd:
            self.msg_label.configure(text="Current password is required.", text_color=DANGER)
            return
        if not new_pwd:
            self.msg_label.configure(text="New password is required.", text_color=DANGER)
            return
        if new_pwd != confirm_pwd:
            self.msg_label.configure(text="New password and confirmation do not match.", text_color=DANGER)
            return
        if len(new_pwd) < 4:
            self.msg_label.configure(text="New password must be at least 4 characters.", text_color=DANGER)
            return

        conn = get_connection()
        try:
            # Fetch user
            user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
            if not user:
                self.msg_label.configure(text="User not found.", text_color=DANGER)
                return

            # Verify old password by attempting login
            try:
                Session.login(conn, username, old_pwd)
            except AuthError:
                self.msg_label.configure(text="Current password is incorrect.", text_color=DANGER)
                return
            # If successful, logout to clear session
            Session.logout()

            # Update password
            new_hash, new_salt = hash_password(new_pwd)
            conn.execute("UPDATE users SET password_hash = ?, salt = ? WHERE id = ?",
                         (new_hash, new_salt, user["id"]))
            conn.commit()
            self.msg_label.configure(text="Password changed successfully. You can now log in.", text_color=SUCCESS)
            self.after(1200, self.destroy)

        except Exception as e:
            self.msg_label.configure(text=str(e), text_color=DANGER)
        finally:
            conn.close()