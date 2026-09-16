import csv
import ast
import operator
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from datetime import date
import customtkinter as ctk

try:
    from tkcalendar import DateEntry as _TkCalDateEntry
    _HAS_TKCALENDAR = True
except ImportError:
    _HAS_TKCALENDAR = False

# ---------------------------------------------------------------------
# customtkinter draws CTkButton on a canvas and ships with keyboard focus
# switched OFF by default, which is why Tab skips right over every button
# in the app (it only stops on native focusable widgets like entries).
# Patch it once, here, so every CTkButton - however/wherever it's created
# - becomes keyboard operable:
#   - Tab / Shift+Tab will stop on it, with a visible focus outline
#   - Enter or Space "clicks" it once it has focus
# ---------------------------------------------------------------------
_orig_ctkbutton_init = ctk.CTkButton.__init__


def _ctkbutton_init_focusable(self, *args, command=None, **kwargs):
    _orig_ctkbutton_init(self, *args, command=command, **kwargs)

    # CTkButton.configure() only accepts customtkinter's own known options
    # and raises on anything else, so "takefocus" has to be set via the
    # underlying plain Tk widget's configure(), bypassing customtkinter's
    # override entirely.
    try:
        tk.Widget.configure(self, takefocus=1)
    except Exception:
        pass

    if command is not None:
        self.bind("<Return>", lambda e: command())
        self.bind("<space>", lambda e: command())

    # Give focus a visible outline, since canvas-drawn buttons don't get
    # Tk's usual highlight ring for free.
    try:
        _orig_border_w = self.cget("border_width")
        _orig_border_c = self.cget("border_color")

        def _focus_in(e):
            self.configure(border_width=2, border_color="#4FC3F7")

        def _focus_out(e):
            self.configure(border_width=_orig_border_w, border_color=_orig_border_c)

        self.bind("<FocusIn>", _focus_in, add="+")
        self.bind("<FocusOut>", _focus_out, add="+")
    except Exception:
        pass  # cosmetic only - never let this break button creation


ctk.CTkButton.__init__ = _ctkbutton_init_focusable


# ---------------------------------------------------------------------
# Quick math for amount/number entry fields - type an expression like
# "1250+375-40" or "(60*3)/2" into a money field, press Enter/Tab or click
# away, and it resolves to the final number. Deliberately does NOT use
# eval()/exec(): only a whitelist of arithmetic AST nodes/operators is
# allowed, mirroring the same safe-formula approach used for "=" cell
# formulas elsewhere in the app.
# ---------------------------------------------------------------------
_MONEY_MATH_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub,
    ast.Mult: operator.mul, ast.Div: operator.truediv,
    ast.USub: operator.neg, ast.UAdd: operator.pos,
}


def _eval_money_expression(expr: str) -> float:
    expr = expr.strip()
    if expr.startswith("="):
        expr = expr[1:]
    if not expr.strip():
        raise ValueError("Empty expression.")

    node = ast.parse(expr, mode="eval").body

    def _eval(n):
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return n.value
        if isinstance(n, ast.BinOp) and type(n.op) in _MONEY_MATH_OPS:
            return _MONEY_MATH_OPS[type(n.op)](_eval(n.left), _eval(n.right))
        if isinstance(n, ast.UnaryOp) and type(n.op) in _MONEY_MATH_OPS:
            return _MONEY_MATH_OPS[type(n.op)](_eval(n.operand))
        raise ValueError(f"Unsupported expression: {expr}")

    return _eval(node)


def enable_quick_math(entry):
    """Let a money/number CTkEntry double as a tiny calculator. Type an
    expression like '1250+375-40', then press Enter/Tab or click elsewhere,
    and it resolves to the final number (2 decimal places). A plain number
    with no operators, or text that isn't a valid expression, is left
    exactly as typed - so this is safe to attach to any amount field."""
    def _resolve(event=None):
        raw = entry.get().strip()
        if not raw or not any(op in raw for op in "+-*/()"):
            return  # nothing to compute (e.g. a plain "500") - leave as-is
        try:
            result = _eval_money_expression(raw)
        except Exception:
            return  # not a valid expression - leave the text alone; normal
                     # amount validation on submit will flag it if needed
        entry.delete(0, "end")
        entry.insert(0, f"{result:.2f}")
    entry.bind("<FocusOut>", _resolve, add="+")
    entry.bind("<Return>", _resolve, add="+")
    return entry

# ---------------------------------------------------------------------
# Shared palette - keep in sync with app_root.py / login_window.py
# ---------------------------------------------------------------------
NAVY_DEEP = "#0A1929"
NAVY_MID = "#0D2137"
NAVY_ROW_ALT = "#0F2743"      # <-- this is the missing constant
NAVY_CARD = "#122A45"
NAVY_BORDER = "#1E3A5F"
BLUE_ACCENT = "#1565C0"
BLUE_HOVER = "#1976D2"
BLUE_LIGHT = "#4FC3F7"
TEXT_PRIMARY = "#E0E0E0"
TEXT_MUTED = "#90A4AE"
TEXT_DIM = "#546E7A"

# ---------------------------------------------------------------------
# Semantic action colors - used consistently for every button across the
# app so the same color always means the same kind of action (primary
# action = blue, confirm/positive = green, destructive = red, neutral =
# slate gray). Defined once here instead of as ad-hoc hex strings.
# ---------------------------------------------------------------------
PRIMARY = "#2D9CDB"
PRIMARY_HOVER = "#2186BD"
SUCCESS = "#27AE60"
SUCCESS_HOVER = "#219653"
DANGER = "#EB5757"
DANGER_HOVER = "#C0392B"
WARNING = "#F2994A"
WARNING_HOVER = "#D9822B"
SLATE = "#3A4A5E"
SLATE_HOVER = "#48607A"

BTN_FONT = ("Segoe UI", 13, "bold")
BTN_HEIGHT = 36


def _btn(parent, text, command, fg, hover, icon="", width=None, height=BTN_HEIGHT,
         font=BTN_FONT, text_color="white", corner_radius=8, **kwargs):
    label = f"{icon}  {text}" if icon else text
    opts = dict(text=label, command=command, fg_color=fg, hover_color=hover,
                font=font, height=height, corner_radius=corner_radius, text_color=text_color)
    if width:
        opts["width"] = width
    opts.update(kwargs)
    return ctk.CTkButton(parent, **opts)


def primary_button(parent, text, command=None, icon="", **kwargs):
    """The single main action on a screen (Post, Save, Search, Submit)."""
    return _btn(parent, text, command, PRIMARY, PRIMARY_HOVER, icon, **kwargs)


def success_button(parent, text, command=None, icon="", **kwargs):
    """A positive/confirming action (Approve, Import, Reconcile)."""
    return _btn(parent, text, command, SUCCESS, SUCCESS_HOVER, icon, **kwargs)


def danger_button(parent, text, command=None, icon="", **kwargs):
    """A destructive action (Delete, Reject, Log Out)."""
    return _btn(parent, text, command, DANGER, DANGER_HOVER, icon, **kwargs)


def secondary_button(parent, text, command=None, icon="", **kwargs):
    """A lower-emphasis supporting action (Refresh, Cancel, Duplicate)."""
    kwargs.setdefault("font", ("Segoe UI", 12))
    kwargs.setdefault("text_color", TEXT_PRIMARY)
    return _btn(parent, text, command, SLATE, SLATE_HOVER, icon, **kwargs)


def outline_button(parent, text, command=None, icon="", **kwargs):
    """A quiet, bordered action that sits well next to a primary button."""
    kwargs.setdefault("font", ("Segoe UI", 12))
    return _btn(parent, text, command, "transparent", NAVY_BORDER, icon,
                text_color=TEXT_PRIMARY, border_width=1, **kwargs)


def card_header(parent, title, subtitle=None, icon=""):
    """A consistent card title row: bold heading (+ optional icon) with a
    muted one-line subtitle underneath, used at the top of a form card."""
    wrap = ctk.CTkFrame(parent, fg_color="transparent")
    top = ctk.CTkFrame(wrap, fg_color="transparent")
    top.pack(anchor="w", fill="x")
    text = f"{icon}  {title}" if icon else title
    ctk.CTkLabel(top, text=text, font=("Segoe UI", 16, "bold"),
                 text_color=TEXT_PRIMARY).pack(side="left")
    if subtitle:
        ctk.CTkLabel(wrap, text=subtitle, font=("Segoe UI", 11),
                     text_color=TEXT_MUTED, anchor="w", justify="left").pack(anchor="w", pady=(2, 0))
    return wrap


def styled_tabview(parent, command=None, **kwargs):
    """A CTkTabview pre-themed to match the app's navy/blue palette, with a
    bit more breathing room than the CTk defaults so tabs read as clear,
    professional section headers rather than cramped pill buttons."""
    tv = ctk.CTkTabview(
        parent, command=command,
        fg_color=NAVY_CARD, segmented_button_fg_color=NAVY_MID,
        segmented_button_selected_color=BLUE_ACCENT,
        segmented_button_selected_hover_color=BLUE_HOVER,
        segmented_button_unselected_color=NAVY_MID,
        segmented_button_unselected_hover_color=NAVY_BORDER,
        text_color=TEXT_PRIMARY, corner_radius=12,
        **kwargs,
    )
    try:
        tv._segmented_button.configure(font=("Segoe UI", 13, "bold"), height=38)
    except Exception:
        pass
    return tv


# ---------------------------------------------------------------------
# Resizable split - a themed tk.PanedWindow so any two (or more) panels
# can get a draggable divider between them. CTk has no native equivalent,
# but plain tk.PanedWindow happily parents CTk frames since they're just
# tkinter widgets underneath.
# ---------------------------------------------------------------------
def resizable_split(parent, orient="horizontal", sash_width=6, bg=None):
    """
    Returns a tk.PanedWindow styled to blend into the navy theme. Build
    child frames with this pane as their master, then call
    `pane.add(child, minsize=..., **opts)` for each one - the user can then
    drag the thin divider between panels to resize them.
    `opts` for .add(): width/height (initial size, horizontal/vertical
    respectively), minsize (won't shrink past this), stretch
    ("always"/"never"/"first"/"last", which panes absorb extra space).
    """
    pane = tk.PanedWindow(
        parent, orient=orient, sashwidth=sash_width, sashrelief="flat",
        bg=bg or NAVY_BORDER, bd=0, showhandle=False, sashpad=0,
        opaqueresize=True, background=bg or NAVY_BORDER,
    )
    return pane

# ---------------------------------------------------------------------
# Status badges - ttk.Treeview can't render a per-cell colored pill, so
# we prefix the status text with a small colored dot instead. Cheap to
# apply, and gives the same at-a-glance scanning benefit as a real pill.
# ---------------------------------------------------------------------
STATUS_DOT = {
    "Active": "🟢",
    "Approved": "🟢",
    "Pending": "🟡",
    "Closed": "⚪",
    "PaidOff": "⚪",
    "RolledOver": "🔵",
    "BadDebt": "🔴",
    "Rejected": "🔴",
    "Declined": "🔴",
}


def status_label(status: str) -> str:
    """Return `status` prefixed with a small colored dot for quick visual
    scanning in a DataTable/Treeview column."""
    if not status:
        return status
    dot = STATUS_DOT.get(status, "⚫")
    return f"{dot} {status}"


# ---------------------------------------------------------------------
# Reusable row of small metric/stat cards (same visual language as the
# Dashboard's stat cards), for use at the top of any module view.
# ---------------------------------------------------------------------
def build_stat_cards(parent, stats, columns=4):
    """
    stats: list of (label, value, color) tuples.
    Builds and packs a grid of stat cards into `parent` and returns the
    containing frame (call .destroy() on it to rebuild/refresh).
    """
    frame = ctk.CTkFrame(parent, fg_color="transparent")
    frame.pack(fill="x", pady=(0, 12))
    for i, (label, value, color) in enumerate(stats):
        row, col = divmod(i, columns)
        frame.grid_columnconfigure(col, weight=1)
        card = ctk.CTkFrame(frame, corner_radius=12, fg_color=NAVY_MID,
                             border_width=1, border_color=NAVY_BORDER)
        card.grid(row=row, column=col, padx=6, pady=6, sticky="nsew")
        ctk.CTkFrame(card, height=4, fg_color=color, corner_radius=0).pack(fill="x")
        ctk.CTkLabel(card, text=str(value), font=("Segoe UI", 20, "bold"),
                     text_color=BLUE_LIGHT).pack(padx=14, pady=(10, 2))
        ctk.CTkLabel(card, text=label, font=("Segoe UI", 11),
                     text_color=TEXT_MUTED).pack(padx=14, pady=(0, 12))
    return frame

# ---- ttk style for Treeview ----
_style = ttk.Style()
try:
    _style.theme_use("clam")
except Exception:
    pass
_style.configure("Custom.Treeview", rowheight=28, font=("Segoe UI", 11),
                  background=NAVY_MID, fieldbackground=NAVY_MID, foreground=TEXT_PRIMARY,
                  borderwidth=0)
_style.map("Custom.Treeview",
           background=[("selected", BLUE_ACCENT)],
           foreground=[("selected", "white")])
_style.configure("Custom.Treeview.Heading", font=("Segoe UI", 11, "bold"),
                  background=NAVY_DEEP, foreground=BLUE_LIGHT, borderwidth=0, relief="flat")
_style.map("Custom.Treeview.Heading", background=[("active", NAVY_DEEP)])
_style.configure("Custom.Vertical.TScrollbar", background=NAVY_BORDER, troughcolor=NAVY_MID,
                  bordercolor=NAVY_MID, arrowcolor=TEXT_MUTED)
_style.configure("Custom.Horizontal.TScrollbar", background=NAVY_BORDER, troughcolor=NAVY_MID,
                  bordercolor=NAVY_MID, arrowcolor=TEXT_MUTED)


# ---------------------------------------------------------------------
# DatePicker
# ---------------------------------------------------------------------
class DatePicker(ctk.CTkFrame):
    def __init__(self, master, width=230, default=None, **kwargs):
        super().__init__(master, fg_color="transparent")
        self._fallback = not _HAS_TKCALENDAR
        default = default or date.today().isoformat()

        if self._fallback:
            self.var = tk.StringVar(value=default)
            self.entry = ctk.CTkEntry(self, textvariable=self.var, width=width,
                                       placeholder_text="YYYY-MM-DD")
            self.entry.pack(side="left", fill="both", expand=True)
        else:
            try:
                y, m, d = (int(p) for p in default.split("-"))
            except Exception:
                today = date.today()
                y, m, d = today.year, today.month, today.day
            self.entry = _TkCalDateEntry(
                self, width=max(width // 9, 10), date_pattern="yyyy-mm-dd",
                year=y, month=m, day=d, background=BLUE_ACCENT, foreground="white", borderwidth=1,
            )
            self.entry.pack(side="left", fill="both", expand=True)

    def get(self):
        return self.entry.get().strip()

    def delete(self, first, last=None):
        if self._fallback:
            self.entry.delete(first, last)

    def insert(self, index, value):
        if self._fallback:
            self.entry.insert(index, value)
        elif value:
            try:
                self.entry.set_date(value)
            except Exception:
                pass

    def configure(self, **kwargs):
        if "state" in kwargs:
            self.entry.configure(state=kwargs.pop("state"))
        if kwargs:
            super().configure(**kwargs)

    def bind(self, sequence=None, func=None, add=None):
        if add is None:
            self.entry.bind(sequence, func)
        else:
            self.entry.bind(sequence, func, add)
        if not self._fallback and sequence == "<KeyRelease>":
            self.entry.bind("<<DateEntrySelected>>", func, add="+")


# ---------------------------------------------------------------------
# DataTable – with CTkScrollbar (visible, themed)
# ---------------------------------------------------------------------
class DataTable(ctk.CTkFrame):
    def __init__(self, master, columns: list[tuple[str, str]], height=14, on_row_click=None,
                 title="Data Export", show_summary=False, **kwargs):
        super().__init__(master, **kwargs)
        self.columns = columns
        self._all_rows = []
        self._row_by_iid = {}
        self.pdf_title = title
        self.pdf_meta_lines = []
        self.pdf_show_summary = show_summary
        self.on_row_click = on_row_click

        # Toolbar
        toolbar = ctk.CTkFrame(self, fg_color="transparent")
        toolbar.pack(fill="x", pady=(0, 6))
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *a: self._filter())
        ctk.CTkEntry(toolbar, textvariable=self.search_var, placeholder_text="🔍  Search...",
                     width=240, height=32, corner_radius=8, fg_color=NAVY_MID, border_color=NAVY_BORDER,
                     text_color=TEXT_PRIMARY, placeholder_text_color=TEXT_DIM).pack(side="left")
        outline_button(toolbar, "Export CSV", self.export_csv, icon="⇩", width=118, height=32).pack(side="right")
        outline_button(toolbar, "Export PDF", self.export_pdf, icon="⇩", width=118, height=32).pack(side="right", padx=(0, 6))

        # Table + CTkScrollbars
        tree_frame = ctk.CTkFrame(self, fg_color="transparent")
        tree_frame.pack(fill="both", expand=True)

        vsb = ctk.CTkScrollbar(tree_frame, orientation="vertical", fg_color=NAVY_BORDER,
                               button_color=BLUE_ACCENT, button_hover_color=BLUE_HOVER)
        hsb = ctk.CTkScrollbar(tree_frame, orientation="horizontal", fg_color=NAVY_BORDER,
                               button_color=BLUE_ACCENT, button_hover_color=BLUE_HOVER)

        self.tree = ttk.Treeview(
            tree_frame, columns=[c[0] for c in columns], show="headings", height=height,
            yscrollcommand=vsb.set, xscrollcommand=hsb.set, style="Custom.Treeview",
            selectmode="extended"   # <-- add this line
        )

        self.tree.tag_configure("oddrow", background=NAVY_MID)
        self.tree.tag_configure("evenrow", background=NAVY_ROW_ALT)   # now defined
        vsb.configure(command=self.tree.yview)
        hsb.configure(command=self.tree.xview)

        for key, label in columns:
            self.tree.heading(key, text=label, command=lambda k=key: self._sort_by(k))
            self.tree.column(key, width=120, anchor="w")

        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        tree_frame.rowconfigure(0, weight=1)
        tree_frame.columnconfigure(0, weight=1)

        self._sort_reverse = {}
        self.tree.bind("<ButtonRelease-1>", self._handle_click)

    def _handle_click(self, event):
        if self.on_row_click:
            row_data = self.selected_row()
            if row_data:
                self.on_row_click({"_raw": row_data})

    def set_rows(self, rows: list[dict]):
        self._all_rows = rows
        # Re-apply whatever's currently in the search box, so loading new
        # data while a filter is already typed in doesn't silently show
        # (and export) everything until the next keystroke.
        self._filter()

    def _visible_rows(self):
        """
        Rows currently shown in the table, in their current filtered and
        sorted display order - NOT the full unfiltered dataset. Exports use
        this so a search filter actually narrows down what gets exported,
        instead of always exporting everything regardless of what's typed
        into the search box.
        """
        return [self._row_by_iid[iid] for iid in self.tree.get_children() if iid in self._row_by_iid]

    def _render(self, rows):
        self.tree.delete(*self.tree.get_children())
        self._row_by_iid = {}
        for i, row in enumerate(rows):
            values = [row.get(k, "") for k, _ in self.columns]
            iid = str(i)
            tag = "evenrow" if i % 2 == 0 else "oddrow"
            self.tree.insert("", "end", iid=iid, values=values, tags=(tag,))
            self._row_by_iid[iid] = row

    def _filter(self):
        term = self.search_var.get().lower().strip()
        if not term:
            self._render(self._all_rows)
            return
        filtered = [r for r in self._all_rows if any(term in str(v).lower() for v in r.values())]
        self._render(filtered)

    def _sort_by(self, key):
        reverse = self._sort_reverse.get(key, False)
        try:
            self._all_rows.sort(key=lambda r: (r.get(key) is None, r.get(key)), reverse=reverse)
        except TypeError:
            self._all_rows.sort(key=lambda r: str(r.get(key)), reverse=reverse)
        self._sort_reverse[key] = not reverse
        # Re-render through _filter (not a direct self._render(self._all_rows))
        # so an active search term stays applied after sorting, instead of
        # sorting silently clearing whatever filter was in effect.
        self._filter()

    def selected_row(self):
        sel = self.tree.selection()
        if not sel:
            return None
        return self._row_by_iid.get(sel[0])
    
    def selected_rows(self):
        """Return a list of row dictionaries for all selected items."""
        selection = self.tree.selection()
        rows = []
        for iid in selection:
            row = self._row_by_iid.get(iid)
            if row:
                rows.append(row)
        return rows

    def export_csv(self):
        rows = self._visible_rows()
        if not rows:
            messagebox.showinfo("Export CSV", "There is no data to export.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")]
        )
        if not path:
            return
        
        try:
            # Using encoding="utf-8-sig" ensures Unicode characters/emojis exported properly
            # and makes the CSV open cleanly in Microsoft Excel without character corruption.
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                # Write header row
                writer.writerow([label for _, label in self.columns])
                
                # Write data rows with safeguards for dicts and list/tuple rows
                for row in rows:
                    if isinstance(row, dict):
                        writer.writerow([row.get(k, "") for k, _ in self.columns])
                    elif isinstance(row, (list, tuple)):
                        writer.writerow(row)
                    else:
                        writer.writerow([str(row)])
                        
            suffix = f" (filtered from {len(self._all_rows)})" if len(rows) != len(self._all_rows) else ""
            messagebox.showinfo("Export CSV", f"Exported {len(rows)} rows{suffix} to:\n{path}")
            
        except Exception as e:
            messagebox.showerror("Export CSV", f"Could not export CSV:\n{e}")
            
    def set_pdf_meta(self, lines: list[str]):
        self.pdf_meta_lines = list(lines or [])

    def export_pdf(self):
        rows = self._visible_rows()
        if not rows:
            messagebox.showinfo("Export PDF", "There is no data to export.")
            return
        try:
            from .pdf_export import export_table_pdf
        except ImportError:
            messagebox.showerror(
                "Export PDF",
                "PDF export requires the 'reportlab' package, which isn't installed.\n\n"
                "Install it with:\n    pip install reportlab",
            )
            return
        default_name = "".join(c if c.isalnum() or c in " -_" else "" for c in self.pdf_title).strip() or "export"
        path = filedialog.asksaveasfilename(
            defaultextension=".pdf", filetypes=[("PDF files", "*.pdf")],
            initialfile=f"{default_name.replace(' ', '_')}.pdf",
        )
        if not path:
            return
        try:
            export_table_pdf(path, title=self.pdf_title, columns=self.columns,
                              rows=rows, meta_lines=self.pdf_meta_lines,
                              show_summary=self.pdf_show_summary)
            suffix = f" (filtered from {len(self._all_rows)})" if len(rows) != len(self._all_rows) else ""
            messagebox.showinfo("Export PDF", f"Exported {len(rows)} rows{suffix} to:\n{path}")
        except Exception as e:
            messagebox.showerror("Export PDF", f"Could not create PDF:\n{e}")


# ---------------------------------------------------------------------
# SearchableCombobox
# ---------------------------------------------------------------------
class SearchableCombobox(ctk.CTkFrame):
    def __init__(self, master, values=None, width=300, command=None, placeholder="Type to search...", **kwargs):
        super().__init__(master, fg_color="transparent")
        self.all_values = list(values or [])
        self.command = command
        self.var = tk.StringVar()
        self.entry = ctk.CTkEntry(self, textvariable=self.var, width=width, placeholder_text=placeholder)
        self.entry.pack(side="left")
        self.entry.bind("<KeyRelease>", self._on_key)
        self.entry.bind("<FocusIn>", lambda e: self._show_dropdown())
        self.entry.bind("<FocusOut>", lambda e: self.after(150, self._hide_dropdown))
        self.entry.bind("<Escape>", lambda e: self._hide_dropdown())
        self.popup = None
        self.listbox = None

    def set_values(self, values):
        self.all_values = list(values or [])

    def configure(self, **kwargs):
        if "values" in kwargs:
            self.set_values(kwargs.pop("values"))
        if kwargs:
            super().configure(**kwargs)

    def get(self):
        return self.var.get()

    def set(self, value):
        self.var.set(value)

    def _on_key(self, event):
        if event.keysym in ("Up", "Down", "Return", "Escape"):
            if event.keysym == "Return":
                self._hide_dropdown()
            return
        self._show_dropdown()

    def _show_dropdown(self):
        term = self.var.get().lower().strip()
        matches = [v for v in self.all_values if term in v.lower()] if term else self.all_values
        matches = matches[:30]
        if not matches:
            self._hide_dropdown()
            return
        if self.popup is None or not self.popup.winfo_exists():
            self.popup = tk.Toplevel(self)
            self.popup.wm_overrideredirect(True)
            self.popup.attributes("-topmost", True)
            self.listbox = tk.Listbox(self.popup, font=("Segoe UI", 11), activestyle="dotbox",
                                       bg=NAVY_MID, fg=TEXT_PRIMARY, selectbackground=BLUE_ACCENT,
                                       selectforeground="white", highlightthickness=1,
                                       highlightbackground=NAVY_BORDER, highlightcolor=BLUE_ACCENT,
                                       borderwidth=0)
            self.listbox.pack(fill="both", expand=True)
            self.listbox.bind("<<ListboxSelect>>", self._on_select)
            self.listbox.bind("<Return>", self._on_select)
        try:
            x = self.entry.winfo_rootx()
            y = self.entry.winfo_rooty() + self.entry.winfo_height()
            w = max(self.entry.winfo_width(), 240)
            h = min(160, 22 * len(matches) + 4)
            self.popup.geometry(f"{w}x{h}+{x}+{y}")
        except tk.TclError:
            return
        self.listbox.delete(0, "end")
        for m in matches:
            self.listbox.insert("end", m)

    def _on_select(self, event):
        if not self.listbox.curselection():
            return
        value = self.listbox.get(self.listbox.curselection()[0])
        self.var.set(value)
        self._hide_dropdown()
        if self.command:
            self.command(value)

    def _hide_dropdown(self):
        if self.popup is not None and self.popup.winfo_exists():
            self.popup.destroy()
        self.popup = None


# ---------------------------------------------------------------------
# FormDialog – scrollable, buttons always visible, dark theme
# ---------------------------------------------------------------------
# ---------------------------------------------------------------------
# FormDialog – scrollable, buttons always visible, dark theme
# ---------------------------------------------------------------------
class FormDialog(ctk.CTkToplevel):
    def __init__(self, master, title: str, fields: list[dict], on_submit, width=460, height=None):
        super().__init__(master)
        self.title(title)
        self.configure(fg_color=NAVY_DEEP)

        # Compute a reasonable height if not provided
        if height is None:
            h = 130
            for f in fields:
                h += 100 if f.get("type") == "textarea" else 54
            # Slightly increased max height threshold to accommodate larger forms smoothly
            height = max(160, min(h, 600))
        else:
            # Allow a minimum of 150px (so compact forms work)
            height = max(150, height)

        self.geometry(f"{width}x{height}")
        self.minsize(width, 260)
        self.resizable(False, True)
        self.transient(master)
        self.grab_set()
        self.on_submit = on_submit
        self.vars = {}

        main_frame = ctk.CTkFrame(self, fg_color="transparent")
        main_frame.pack(fill="both", expand=True, padx=14, pady=(14, 6))

        # 1. Create and pack the button row FIRST at the bottom so it's always visible
        btn_row = ctk.CTkFrame(main_frame, fg_color="transparent")
        btn_row.pack(side="bottom", fill="x", pady=(0, 0))

        secondary_button(btn_row, "Cancel", self.destroy, width=100, height=34).pack(side="right", padx=4)
        primary_button(btn_row, "Save", self._submit, icon="✓", width=110, height=34).pack(side="right", padx=4)

        # 2. Create and pack the scrollable frame to fill the REST of the space above the buttons
        scroll = ctk.CTkScrollableFrame(main_frame, fg_color=NAVY_MID, corner_radius=8)
        scroll.pack(side="top", fill="both", expand=True, pady=(0, 10))

        for field in fields:
            row = ctk.CTkFrame(scroll, fg_color="transparent")
            row.pack(fill="x", pady=4)

            lbl = ctk.CTkLabel(row, text=field["label"], width=150, anchor="w", text_color=TEXT_PRIMARY)
            lbl.pack(side="left")

            ftype = field.get("type", "entry")
            default = field.get("default", "")
            if ftype == "combobox":
                var = tk.StringVar(value=default or (field["options"][0] if field.get("options") else ""))
                widget = ctk.CTkComboBox(row, values=field.get("options", []), variable=var, width=230)
            elif ftype == "searchable":
                widget = SearchableCombobox(row, values=field.get("options", []), width=230)
                if default:
                    widget.set(default)
                var = None
            elif ftype == "textarea":
                var = None
                widget = ctk.CTkTextbox(row, width=230, height=70, fg_color=NAVY_MID, text_color=TEXT_PRIMARY)
                if default:
                    widget.insert("1.0", str(default))
            elif ftype == "date":
                var = None
                widget = DatePicker(row, width=230, default=default or None)
            elif ftype == "money":
                var = tk.StringVar(value=default)
                widget = ctk.CTkEntry(row, textvariable=var, width=230, fg_color=NAVY_MID, text_color=TEXT_PRIMARY)
                enable_quick_math(widget)
            else:
                var = tk.StringVar(value=default)
                widget = ctk.CTkEntry(row, textvariable=var, width=230, fg_color=NAVY_MID, text_color=TEXT_PRIMARY)
            
            widget.pack(side="left")
            self.vars[field["key"]] = (ftype, var, widget)

        self.focus_set()
        self.lift()

        # Keyboard shortcuts: Esc cancels, Ctrl+Enter saves - handy so you
        # don't have to reach for the mouse to close/confirm a popup form.
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Control-Return>", lambda e: self._submit())

    def _submit(self):
        values = {}
        for key, (ftype, var, widget) in self.vars.items():
            if ftype == "textarea":
                values[key] = widget.get("1.0", "end").strip()
            elif ftype in ("searchable", "date"):
                values[key] = widget.get().strip()
            else:
                values[key] = var.get().strip() if isinstance(var.get(), str) else var.get()
        try:
            self.on_submit(values)
            self.destroy()
        except Exception as e:
            messagebox.showerror("Error", str(e), parent=self)# ---------------------------------------------------------------------
# TrendChart - lightweight grouped bar chart drawn on a plain Tk Canvas.
# Deliberately dependency-free (no matplotlib) so it fits the existing
# customtkinter/tksheet stack. Good for small "N buckets x 1-2 series"
# comparisons like disbursements vs collections per month.
# ---------------------------------------------------------------------
class TrendChart(ctk.CTkFrame):
    """
    data:    list of {"label": str, "values": {series_name: number, ...}}
    series:  list of (series_name, color) tuples - draw order + legend
    targets: optional {series_name: [value_per_group, ...]} - draws a thin
             marker line across that series' bar at the target height (e.g.
             a budgeted figure to compare the actual bar against). A target
             of 0/None for a given group is simply skipped, so months with
             no budget entered don't draw a misleading line at the baseline.
    """
    TARGET_COLOR = "#FFC107"

    def __init__(self, master, data=None, series=None, height=220, value_fmt=None, targets=None, **kwargs):
        kwargs.setdefault("fg_color", NAVY_MID)
        kwargs.setdefault("corner_radius", 12)
        super().__init__(master, **kwargs)
        self.data = data or []
        self.series = series or []
        self.targets = targets or {}
        self.value_fmt = value_fmt or (lambda v: f"{v:,.0f}")

        if self.series:
            legend = ctk.CTkFrame(self, fg_color="transparent")
            legend.pack(fill="x", padx=14, pady=(10, 0))
            for name, color in self.series:
                item = ctk.CTkFrame(legend, fg_color="transparent")
                item.pack(side="left", padx=(0, 16))
                ctk.CTkFrame(item, width=12, height=12, fg_color=color, corner_radius=3).pack(side="left", padx=(0, 6))
                ctk.CTkLabel(item, text=name, font=("Segoe UI", 11), text_color=TEXT_MUTED).pack(side="left")
            if self.targets:
                # Thin swatch (rather than a solid block) to read as a line
                # marker, matching how it's actually drawn on the chart.
                item = ctk.CTkFrame(legend, fg_color="transparent")
                item.pack(side="left", padx=(0, 16))
                ctk.CTkFrame(item, width=12, height=3, fg_color=self.TARGET_COLOR).pack(side="left", padx=(0, 6), pady=5)
                ctk.CTkLabel(item, text="Budgeted", font=("Segoe UI", 11), text_color=TEXT_MUTED).pack(side="left")

        self.canvas = tk.Canvas(self, height=height, bg=NAVY_MID, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True, padx=10, pady=(6, 12))
        self.canvas.bind("<Configure>", lambda e: self._draw_chart())
        self._draw_chart()

    def set_data(self, data, targets=None):
        self.data = data or []
        if targets is not None:
            self.targets = targets
        self._draw_chart()

    def _draw_chart(self):
        c = self.canvas
        c.delete("all")
        w, h = c.winfo_width(), c.winfo_height()
        if w < 20 or h < 20:
            return
        if not self.data:
            c.create_text(w // 2, h // 2, text="No data yet", fill=TEXT_DIM, font=("Segoe UI", 11))
            return

        pad_left, pad_right, pad_top, pad_bottom = 54, 16, 14, 26
        plot_w = max(w - pad_left - pad_right, 1)
        plot_h = max(h - pad_top - pad_bottom, 1)

        all_vals = [v for row in self.data for v in row["values"].values()]
        # Budget targets can exceed the actuals in a given month, so the
        # scale needs to account for them too or a target line could be
        # drawn above the plot area.
        for target_list in self.targets.values():
            all_vals.extend(v for v in target_list if v)
        max_val = max(all_vals) if all_vals else 0
        max_val = (max_val * 1.15) if max_val > 0 else 1

        # Gridlines + y-axis labels
        for i in range(5):
            y = pad_top + plot_h - (plot_h * i / 4)
            c.create_line(pad_left, y, w - pad_right, y, fill=NAVY_BORDER)
            c.create_text(pad_left - 8, y, text=self.value_fmt(max_val * i / 4),
                          fill=TEXT_DIM, font=("Segoe UI", 9), anchor="e")

        n_groups = len(self.data)
        n_series = max(len(self.series), 1)
        group_w = plot_w / n_groups
        bar_gap = 4
        bar_w = max((group_w - bar_gap * (n_series + 1)) / n_series, 3)

        for gi, row in enumerate(self.data):
            gx0 = pad_left + gi * group_w
            for si, (name, color) in enumerate(self.series):
                val = row["values"].get(name, 0)
                bar_h = (val / max_val) * plot_h if max_val else 0
                x0 = gx0 + bar_gap + si * (bar_w + bar_gap)
                x1 = x0 + bar_w
                y1 = pad_top + plot_h
                y0 = y1 - bar_h
                c.create_rectangle(x0, y0, x1, y1, fill=color, outline="")

                target_list = self.targets.get(name)
                target_val = target_list[gi] if target_list and gi < len(target_list) else None
                if target_val:
                    ty = pad_top + plot_h - (target_val / max_val) * plot_h if max_val else y1
                    c.create_line(x0 - 1, ty, x1 + 1, ty, fill=self.TARGET_COLOR, width=2)
            c.create_text(gx0 + group_w / 2, pad_top + plot_h + 12, text=row["label"],
                          fill=TEXT_MUTED, font=("Segoe UI", 10))


# Global message helpers
# ---------------------------------------------------------------------


def info(msg, title="Info"):
    messagebox.showinfo(title, msg)


def error(msg, title="Error"):
    messagebox.showerror(title, msg)


def confirm(msg, title="Confirm") -> bool:
    return messagebox.askyesno(title, msg)

class SectionedFormDialog(ctk.CTkToplevel):
    """
    Dynamically generates a multi-column, sectioned form based on a schema.
    Supports distinct background colors per section.
    """
    def __init__(self, master, title: str, schema: list[dict], on_submit, width=750, height=650):
        super().__init__(master)
        self.title(title)
        self.geometry(f"{width}x{height}")
        self.resizable(False, True)
        self.transient(master)
        self.grab_set()
        self.configure(fg_color=NAVY_DEEP)
        
        self.on_submit = on_submit
        self.vars = {}
        self.widgets = {}

        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=16, pady=16)

        card = ctk.CTkFrame(scroll, fg_color=("gray95", "gray15"), corner_radius=8)
        card.pack(fill="both", expand=True)

        # Main Title
        toolbar = ctk.CTkFrame(card, fg_color="transparent")
        toolbar.pack(fill="x", pady=(10, 10), padx=10)
        ctk.CTkLabel(toolbar, text=title, font=("Segoe UI", 17, "bold")).pack(side="left")

        # Build Sections
        for section in schema:
            self._build_section(card, section)

        # Action Buttons
        btn_frame = ctk.CTkFrame(card, fg_color="transparent")
        btn_frame.pack(fill="x", padx=10, pady=(12, 10))
        secondary_button(btn_frame, "Cancel", self.destroy, width=100, height=32).pack(side="right", padx=6)
        primary_button(btn_frame, "Save Changes", self._submit, icon="✓", width=150, height=32).pack(side="right")

        # Keyboard shortcuts: Esc cancels, Ctrl+Enter saves.
        self.bind("<Escape>", lambda e: self.destroy())
        self.bind("<Control-Return>", lambda e: self._submit())

    def _build_section(self, parent, section_data):
        sec_frame = ctk.CTkFrame(parent, fg_color="transparent")
        sec_frame.pack(fill="x", padx=10, pady=(0, 10))
        
        ctk.CTkLabel(sec_frame, text=section_data["title"], font=("Segoe UI", 11, "bold"), text_color=BLUE_LIGHT).pack(anchor="w")
        ctk.CTkFrame(sec_frame, height=2, fg_color=NAVY_BORDER).pack(fill="x", pady=(2, 3))

        bg_color = section_data.get("color", NAVY_MID)

        for row_data in section_data.get("rows", []):
            row_frame = ctk.CTkFrame(sec_frame, fg_color="transparent")
            row_frame.pack(fill="x", pady=2)
            
            # Configure columns to stretch equally
            for i in range(len(row_data)):
                row_frame.columnconfigure(i, weight=1, pad=4)

            for col_idx, field in enumerate(row_data):
                field_frame = ctk.CTkFrame(row_frame, fg_color="transparent")
                field_frame.grid(row=0, column=col_idx, sticky="nsew", padx=(8 if col_idx > 0 else 0, 0))
                
                ctk.CTkLabel(field_frame, text=field["label"], font=("Segoe UI", 9, "bold"), text_color=TEXT_MUTED).pack(anchor="w")
                
                self._build_field(field_frame, field, bg_color)

    def _build_field(self, parent, field, bg_color):
        key = field["key"]
        ftype = field.get("type", "entry")
        default = field.get("default", "")
        state = field.get("state", "normal")

        if ftype == "combobox":
            var = tk.StringVar(value=default or (field["options"][0] if field.get("options") else ""))
            widget = ctk.CTkComboBox(parent, values=field.get("options", []), variable=var, height=26, 
                                     fg_color=bg_color, button_color=NAVY_BORDER, text_color="white", state=state)
        elif ftype == "searchable":
            widget = SearchableCombobox(parent, values=field.get("options", []), width=400)
            if hasattr(widget, 'entry'):
                widget.entry.configure(fg_color=bg_color, text_color="white")
            if default:
                widget.set(default)
            var = None
        elif ftype == "textarea":
            var = None
            widget = ctk.CTkTextbox(parent, height=70, fg_color=bg_color, text_color="white")
            if default:
                widget.insert("1.0", str(default))
        elif ftype == "date":
            var = None
            widget = DatePicker(parent, width=200, default=default or None)
        elif ftype == "money":
            var = tk.StringVar(value=default)
            widget = ctk.CTkEntry(parent, textvariable=var, height=26, fg_color=bg_color, text_color="white", state=state)
            if field.get("placeholder"):
                widget.configure(placeholder_text=field["placeholder"])
            enable_quick_math(widget)
        else:
            var = tk.StringVar(value=default)
            widget = ctk.CTkEntry(parent, textvariable=var, height=26, fg_color=bg_color, text_color="white", state=state)
            if field.get("placeholder"):
                widget.configure(placeholder_text=field["placeholder"])

        widget.pack(anchor="w", fill="x")
        
        # Apply bind commands if present
        if "command" in field and ftype == "searchable":
            widget.command = field["command"]

        self.vars[key] = (ftype, var, widget)
        self.widgets[key] = widget

    def get_widget(self, key):
        """Allows external methods to update specific widget states dynamically."""
        return self.widgets.get(key)

    def _submit(self):
        values = {}
        for key, (ftype, var, widget) in self.vars.items():
            if ftype == "textarea":
                values[key] = widget.get("1.0", "end").strip()
            elif ftype in ("searchable", "date"):
                values[key] = widget.get().strip()
            else:
                values[key] = var.get().strip() if isinstance(var.get(), str) else var.get()
        try:
            self.on_submit(values)
        except Exception as e:
            messagebox.showerror("Error", str(e), parent=self)

class SectionedFormFrame(ctk.CTkFrame):
    """
    Dynamically generates a multi-column, sectioned form based on a schema,
    designed to be embedded directly into tabs or other frames.
    """
    def __init__(self, master, schema: list[dict], on_submit=None, submit_text="Save Changes", **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.vars = {}
        self.widgets = {}
        self.on_submit = on_submit

        self.card = ctk.CTkFrame(self, fg_color=("gray95", "gray15"), corner_radius=8)
        self.card.pack(fill="both", expand=True, padx=10, pady=10)

        # Build Sections
        for section in schema:
            self._build_section(self.card, section)

        # Action Buttons
        if on_submit:
            btn_frame = ctk.CTkFrame(self.card, fg_color="transparent")
            btn_frame.pack(fill="x", padx=10, pady=(12, 10))
            success_button(btn_frame, submit_text, self._submit, icon="✓", width=160).pack(side="left")

    def _build_section(self, parent, section_data):
        sec_frame = ctk.CTkFrame(parent, fg_color="transparent")
        sec_frame.pack(fill="x", padx=10, pady=(0, 10))
        
        if "title" in section_data:
            ctk.CTkLabel(sec_frame, text=section_data["title"], font=("Segoe UI", 11, "bold"), text_color=BLUE_LIGHT).pack(anchor="w")
            ctk.CTkFrame(sec_frame, height=2, fg_color=NAVY_BORDER).pack(fill="x", pady=(2, 3))

        bg_color = section_data.get("color", NAVY_MID)

        for row_data in section_data.get("rows", []):
            row_frame = ctk.CTkFrame(sec_frame, fg_color="transparent")
            row_frame.pack(fill="x", pady=2)
            
            for i in range(len(row_data)):
                row_frame.columnconfigure(i, weight=1, pad=4)

            for col_idx, field in enumerate(row_data):
                field_frame = ctk.CTkFrame(row_frame, fg_color="transparent")
                field_frame.grid(row=0, column=col_idx, sticky="nsew", padx=(8 if col_idx > 0 else 0, 0))
                
                if "label" in field:
                    ctk.CTkLabel(field_frame, text=field["label"], font=("Segoe UI", 9, "bold"), text_color=TEXT_MUTED).pack(anchor="w")
                
                self._build_field(field_frame, field, bg_color)

    def _build_field(self, parent, field, bg_color):
        key = field["key"]
        ftype = field.get("type", "entry")
        default = field.get("default", "")
        state = field.get("state", "normal")

        if ftype == "combobox":
            var = tk.StringVar(value=default or (field["options"][0] if field.get("options") else ""))
            widget = ctk.CTkComboBox(parent, values=field.get("options", []), variable=var, height=26, 
                                     fg_color=bg_color, button_color=NAVY_BORDER, text_color="white", state=state)
            if "command" in field:
                widget.configure(command=field["command"])
        elif ftype == "searchable":
            widget = SearchableCombobox(parent, values=field.get("options", []), width=400)
            if hasattr(widget, 'entry'):
                widget.entry.configure(fg_color=bg_color, text_color="white")
            if default:
                widget.set(default)
            var = None
            if "command" in field:
                widget.command = field["command"]
        elif ftype == "textarea":
            var = None
            widget = ctk.CTkTextbox(parent, height=70, fg_color=bg_color, text_color="white")
            if default:
                widget.insert("1.0", str(default))
        elif ftype == "date":
            var = None
            widget = DatePicker(parent, width=200, default=default or None)
            if "command" in field:
                widget.bind("<KeyRelease>", field["command"])
        elif ftype == "money":
            var = tk.StringVar(value=default)
            widget = ctk.CTkEntry(parent, textvariable=var, height=26, fg_color=bg_color, text_color="white", state=state)
            if field.get("placeholder"):
                widget.configure(placeholder_text=field["placeholder"])
            enable_quick_math(widget)
        else:
            var = tk.StringVar(value=default)
            widget = ctk.CTkEntry(parent, textvariable=var, height=26, fg_color=bg_color, text_color="white", state=state)
            if field.get("placeholder"):
                widget.configure(placeholder_text=field["placeholder"])

        widget.pack(anchor="w", fill="x")

        # Keyboard shortcut: Ctrl+Enter submits the form from any field,
        # without having to reach for the "Post"/"Save" button with the mouse.
        # Widgets like SearchableCombobox hold their real Entry as a
        # sub-widget, so bind to that (where keystrokes actually land)
        # rather than the wrapping frame.
        if self.on_submit:
            bind_target = widget.entry if hasattr(widget, "entry") else widget
            bind_target.bind("<Control-Return>", lambda e: self._submit())

        self.vars[key] = (ftype, var, widget)
        self.widgets[key] = widget

    def get_widget(self, key):
        """Allows external methods to manipulate a specific widget directly."""
        return self.widgets.get(key)
        
    def get_values(self):
        """Retrieves current values of all fields."""
        values = {}
        for key, (ftype, var, widget) in self.vars.items():
            if ftype == "textarea":
                values[key] = widget.get("1.0", "end").strip()
            elif ftype in ("searchable", "date"):
                values[key] = widget.get().strip()
            else:
                values[key] = var.get().strip() if isinstance(var.get(), str) else var.get()
        return values

    def _submit(self):
        try:
            self.on_submit(self.get_values())
        except Exception as e:
            import tkinter.messagebox as messagebox
            messagebox.showerror("Error", str(e), parent=self)
            
    def update_fields(self, data: dict):
        """Convenience method to push a dictionary of values into the form."""
        for key, val in data.items():
            if key in self.widgets:
                widget = self.widgets[key]
                ftype = self.vars[key][0]
                
                old_state = widget.cget("state") if hasattr(widget, "cget") and "state" in widget.keys() else "normal"
                if old_state == "disabled":
                    widget.configure(state="normal")
                    
                if ftype == "textarea":
                    widget.delete("1.0", "end")
                    if val: widget.insert("1.0", str(val))
                elif ftype in ("searchable", "combobox"):
                    widget.set(str(val) if val else "")
                elif ftype in ("date", "entry", "money"):
                    widget.delete(0, "end")
                    if val: widget.insert(0, str(val))
                    
                if old_state == "disabled":
                    widget.configure(state="disabled")