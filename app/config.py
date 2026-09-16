import os
import sys


def _bundle_dir():
    """
    Directory that holds files bundled alongside the code (like schema.sql).
    - In dev, this is the project root (two levels up from this file, i.e.
      the folder that CONTAINS the 'app' package).
    - When frozen by PyInstaller, bundled data files are extracted to
      sys._MEIPASS instead (a temp folder for --onefile, or the app's own
      folder for --onedir). This must match wherever the build script
      places schema.sql inside the bundle - see build.py / the --add-data
      flag, which puts it under an 'app' subfolder to mirror the dev layout.
    """
    if getattr(sys, "frozen", False):
        return sys._MEIPASS
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _user_data_root():
    """
    Stable, writable, user-visible folder for the database and exports -
    completely separate from wherever the .exe/install files happen to
    live. This is what makes backups possible and reinstalls/updates safe:
    the app can be replaced or reinstalled entirely without touching this
    folder, and the same relative path resolves consistently on every
    Windows machine the app is installed on.

    Using the Documents folder (rather than AppData) so the person can
    find it in File Explorer without knowing where "hidden" app data
    lives - useful since the goal here is manual backup.
    """
    if sys.platform == "win32":
        docs = os.environ.get("USERPROFILE", os.path.expanduser("~"))
        return os.path.join(docs, "Documents", "MicrofinanceManager")
    elif sys.platform == "darwin":
        return os.path.join(os.path.expanduser("~/Documents"), "MicrofinanceManager")
    else:
        return os.path.join(os.path.expanduser("~"), "MicrofinanceManager")


BASE_DIR = _bundle_dir()
DATA_ROOT = _user_data_root()

DATA_DIR = os.path.join(DATA_ROOT, "data")
EXPORTS_DIR = os.path.join(DATA_ROOT, "exports")
DB_PATH = os.path.join(DATA_DIR, "microfinance.db")

# schema.sql is a bundled resource (ships with the code, read-only at
# runtime), NOT user data - it must be resolved relative to BASE_DIR, not
# DATA_ROOT. It lives inside the 'app' package folder in both dev and the
# frozen build (see build.py's --add-data mapping).
SCHEMA_PATH = os.path.join(BASE_DIR, "app", "schema.sql")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(EXPORTS_DIR, exist_ok=True)

APP_NAME = "Microfinance Manager"
APP_VERSION = "1.0.0"

# Default admin credentials created on first run (change immediately after login)
DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = "admin123"

CURRENCY_SYMBOL = "$"
