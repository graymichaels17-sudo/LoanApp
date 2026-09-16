"""
Single persistent application root.

CustomTkinter only properly supports ONE ctk.CTk() root window per process -
it keeps class-level trackers (DPI scaling watcher, button click animations)
tied to the active root via .after(). Destroying a root and immediately
creating + mainloop()-ing a brand new one (the old pattern) leaves those
trackers pointing at destroyed widgets, which surfaces as:

    invalid command name "...update" / "...check_dpi_scaling" / "..._click_animation"

Fix: keep a single AppRoot alive for the whole program, and swap the
Login screen / Main dashboard in and out as plain CTkFrames.
"""
import os
import tkinter as tk
import customtkinter as ctk
from .. import config

# assets/ is expected to sit alongside the app package (i.e. project_root/assets/),
# same level as main.py - adjust ASSETS_DIR below if yours lives elsewhere.
ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "assets")


def _load_png_icon(png_path):
    return tk.PhotoImage(file=png_path)


class AppRoot(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")
        self.configure(fg_color="#0A1929")
        self.title(config.APP_NAME)
        self._set_app_icon()
        self._current = None
        self.show_login()

    def _set_app_icon(self):
        """Sets the window/titlebar/taskbar icon. Deferred slightly via .after()
        because on Windows, setting the icon before the window is fully mapped
        often updates the titlebar but not the taskbar - a very commonly-hit
        quirk. Sets both iconbitmap (Windows-native .ico) and iconphoto
        (cross-platform) together, since taskbar icon updates are inconsistent
        on Windows when only one of the two is set."""
        self.after(200, self._apply_icon)

    def _apply_icon(self):
        ico_path = os.path.join(ASSETS_DIR, "app_icon.ico")
        png_path = os.path.join(ASSETS_DIR, "app_icon.png")
        try:
            if os.name == "nt" and os.path.exists(ico_path):
                self.iconbitmap(default=ico_path)
            if os.path.exists(png_path):
                self._icon_image = _load_png_icon(png_path)  # keep a reference - Tk drops GC'd images
                self.iconphoto(True, self._icon_image)
        except Exception:
            pass  # missing/invalid icon file should never crash the app

    def _clear_current(self):
        if self._current is not None:
            self._current.destroy()
            self._current = None

    def show_login(self):
        self._clear_current()
        from .login_window import LoginFrame
        self.geometry("440x520")
        self.resizable(False, False)
        self._current = LoginFrame(self)
        self._current.pack(expand=True, fill="both")

    def show_main(self, user):
        self._clear_current()
        from .main_window import MainWindowFrame
        self.geometry("1320x820")
        self.resizable(True, True)
        self._current = MainWindowFrame(self, user)
        self._current.pack(expand=True, fill="both")
