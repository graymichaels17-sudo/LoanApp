"""
Microfinance Manager - offline desktop application.
Run with:  python main.py
"""
import sys
from app.database import init_db


def _fix_windows_taskbar_icon():
    """
    On Windows, Tkinter/CustomTkinter windows launched via 'python main.py'
    often show python.exe's own icon in the taskbar instead of the one set
    via iconbitmap() - Windows groups the taskbar entry by the process's
    "App User Model ID", which defaults to python.exe's identity when not
    set explicitly. Telling Windows this process has its own distinct App
    User Model ID (before any window is created) makes it use the window's
    own icon in the taskbar instead of falling back to python.exe's.
    """
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "MicrofinManager.DesktopApp.1"
            )
        except Exception:
            pass  # best-effort - must never block the app from starting


def main():
    _fix_windows_taskbar_icon()
    init_db()
    from app.ui.app_root import AppRoot
    app = AppRoot()
    app.mainloop()


if __name__ == "__main__":
    main()
