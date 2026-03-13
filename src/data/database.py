from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from src.config import ORM_DB_PATH

# Create the SQLite URL for SQLAlchemy
SQLALCHEMY_DATABASE_URL = f"sqlite:///{ORM_DB_PATH}"

# We disable check_same_thread for SQLite to allow multiple threads to access it
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
