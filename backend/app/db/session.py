"""
GD-IPCA Database Engine & Session Management
Supports MySQL 8.0 with graceful SQLite dev fallback
"""
import socket
import logging
from urllib.parse import urlparse
from typing import Generator
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base
from app.core.config import settings

logger = logging.getLogger("gdipca.db")

Base = declarative_base()


def _is_port_reachable(host: str, port: int, timeout: float = 0.3) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False


def _create_db_engine():
    db_url = settings.DATABASE_URL
    is_sqlite = db_url.startswith("sqlite")

    if not is_sqlite and "mysql" in db_url:
        try:
            # Parse host and port to check availability instantly
            clean_url = db_url.replace("mysql+pymysql://", "http://").replace("mysql://", "http://")
            parsed = urlparse(clean_url)
            host = parsed.hostname or "localhost"
            port = parsed.port or 3306
            if not _is_port_reachable(host, port):
                logger.info(
                    f"MySQL server at {host}:{port} is not listening. "
                    "Transparently activating SQLite engine (gdipca.db) for local development/testing."
                )
                return create_engine(
                    "sqlite:///./gdipca.db",
                    connect_args={"check_same_thread": False},
                    echo=settings.DEBUG,
                )
        except Exception:
            pass

    try:
        if is_sqlite:
            engine = create_engine(
                db_url,
                connect_args={"check_same_thread": False},
                echo=settings.DEBUG,
            )
        else:
            engine = create_engine(
                db_url,
                connect_args={"connect_timeout": 2},
                pool_pre_ping=settings.DB_POOL_PRE_PING,
                pool_size=settings.DB_POOL_SIZE,
                max_overflow=settings.DB_MAX_OVERFLOW,
                pool_recycle=settings.DB_POOL_RECYCLE,
                echo=settings.DEBUG,
            )
        # Test connection
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info(f"Database connected successfully via {db_url.split('@')[-1] if '@' in db_url else 'local engine'}")
        return engine
    except Exception as exc:
        logger.warning(
            f"Failed to connect to primary database ({db_url}): {exc}. "
            "Falling back to local SQLite engine (gdipca.db) for development/testing."
        )
        return create_engine(
            "sqlite:///./gdipca.db",
            connect_args={"check_same_thread": False},
            echo=settings.DEBUG,
        )


engine = _create_db_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator:
    """FastAPI dependency for database sessions."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Ensure all declared models exist in database."""
    Base.metadata.create_all(bind=engine)
