from pathlib import Path

# Base directory is the root of the project (one level up from src)
BASE_DIR = Path(__file__).resolve().parent.parent

# Data directory and files
DATA_DIR = Path(r"E:\AccountManagerData")
LOL_DB_PATH = DATA_DIR / "lol_database.json"
SC2_DB_PATH = DATA_DIR / "sc2_database.json"
SETTINGS_PATH = DATA_DIR / "settings.json"

# Phase 4 Database and Raw Data Paths
SQLITE_DB_PATH = DATA_DIR / "app_database.db"
RAW_DATA_DIR = DATA_DIR / "Raw"
RAW_MATCHES_DIR = RAW_DATA_DIR / "Matches"
RAW_TIMELINES_DIR = RAW_DATA_DIR / "Timelines"

# Ensure data directories exist
DATA_DIR.mkdir(parents=True, exist_ok=True)
RAW_MATCHES_DIR.mkdir(parents=True, exist_ok=True)
RAW_TIMELINES_DIR.mkdir(parents=True, exist_ok=True)