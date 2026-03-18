from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker
from src.config import ORM_DB_PATH

SQLALCHEMY_DATABASE_URL = f"sqlite:///{ORM_DB_PATH}"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
)

# Enable WAL mode for better concurrent read/write performance
@event.listens_for(engine, "connect")
def _set_wal_mode(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def _ensure_columns():
    """Add columns that may not exist yet in the SQLite database."""
    import sqlite3
    conn = sqlite3.connect(str(ORM_DB_PATH))
    cursor = conn.cursor()
    _add_column_if_missing(cursor, "sc2_profiles", "last_game_result", "TEXT")
    _add_column_if_missing(cursor, "sc2_profiles", "last_game_opponent", "TEXT")
    _add_column_if_missing(cursor, "lol_profiles", "current_game_queue_id", "INTEGER")
    _add_column_if_missing(cursor, "lol_profiles", "last_game_result", "TEXT")
    _add_column_if_missing(cursor, "lol_profiles", "last_game_queue_id", "INTEGER")
    _add_column_if_missing(cursor, "lol_profiles", "last_game_lp_change", "INTEGER")
    _add_column_if_missing(cursor, "lol_ranks", "decay_start", "INTEGER")
    _add_column_if_missing(cursor, "sc2_gm_thresholds", "ladder_mmrs", "TEXT")
    _add_column_if_missing(cursor, "sc2_profiles", "last_game_ended_at", "INTEGER")
    _add_column_if_missing(cursor, "sc2_profiles", "last_game_mmr_change", "INTEGER")
    _add_column_if_missing(cursor, "sc2_profiles", "last_game_mmr_race", "TEXT")
    _add_column_if_missing(cursor, "sc2_profiles", "last_game_gm_rank_change", "INTEGER")
    _add_column_if_missing(cursor, "lol_profiles", "last_game_ended_at", "INTEGER")
    _add_column_if_missing(cursor, "sc2_gm_thresholds", "season_id", "INTEGER")
    _add_column_if_missing(cursor, "sc2_gm_thresholds", "season_start", "INTEGER")
    _add_column_if_missing(cursor, "sc2_gm_thresholds", "season_end", "INTEGER")
    conn.commit()
    conn.close()


def _add_column_if_missing(cursor, table: str, column: str, col_type: str):
    cursor.execute(f"PRAGMA table_info({table})")
    existing = {row[1] for row in cursor.fetchall()}
    if column not in existing:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
        print(f"[DB] Added column {table}.{column}")


_ensure_columns()


@contextmanager
def get_session():
    """Context manager that provides a DB session with auto-commit/rollback."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
