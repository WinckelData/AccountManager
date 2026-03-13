from pathlib import Path

# Base directory is the root of the project (one level up from src)
BASE_DIR = Path(__file__).resolve().parent.parent

# Data directory and files
DATA_DIR = Path(r"E:\AccountManagerData")
SETTINGS_PATH = DATA_DIR / "settings.json"

# Phase 4 Database and Raw Data Paths
ORM_DB_PATH = DATA_DIR / "app_orm.db"

# Ensure data directories exist
DATA_DIR.mkdir(parents=True, exist_ok=True)