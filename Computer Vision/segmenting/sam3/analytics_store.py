#!/usr/bin/env python3
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, TypeVar


@dataclass(frozen=True)
class ImageAnalytics:
    source_path: str
    output_path: str
    processed_at: str
    foreground_pixels: int
    total_pixels: int
    foreground_ratio: float
    mask_count: int
    source_mtime_ns: int
    source_size_bytes: int


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS image_analytics (
    source_path TEXT PRIMARY KEY,
    output_path TEXT NOT NULL,
    processed_at TEXT NOT NULL,
    foreground_pixels INTEGER NOT NULL,
    total_pixels INTEGER NOT NULL,
    foreground_ratio REAL NOT NULL,
    mask_count INTEGER NOT NULL,
    source_mtime_ns INTEGER NOT NULL,
    source_size_bytes INTEGER NOT NULL
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    init_db(conn)
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_image_analytics_processed_at "
        "ON image_analytics(processed_at)"
    )
    conn.commit()


def upsert_image_analytics(conn: sqlite3.Connection, analytics: ImageAnalytics) -> None:
    def write() -> None:
        conn.execute(
            """
            INSERT INTO image_analytics (
                source_path,
                output_path,
                processed_at,
                foreground_pixels,
                total_pixels,
                foreground_ratio,
                mask_count,
                source_mtime_ns,
                source_size_bytes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_path) DO UPDATE SET
                output_path = excluded.output_path,
                processed_at = excluded.processed_at,
                foreground_pixels = excluded.foreground_pixels,
                total_pixels = excluded.total_pixels,
                foreground_ratio = excluded.foreground_ratio,
                mask_count = excluded.mask_count,
                source_mtime_ns = excluded.source_mtime_ns,
                source_size_bytes = excluded.source_size_bytes
            """,
            (
                analytics.source_path,
                analytics.output_path,
                analytics.processed_at,
                analytics.foreground_pixels,
                analytics.total_pixels,
                analytics.foreground_ratio,
                analytics.mask_count,
                analytics.source_mtime_ns,
                analytics.source_size_bytes,
            ),
        )
        conn.commit()

    retry_sqlite(write)


def delete_analytics_older_than(conn: sqlite3.Connection, cutoff_iso: str) -> list[str]:
    rows = conn.execute(
        "SELECT output_path FROM image_analytics WHERE processed_at < ?",
        (cutoff_iso,),
    ).fetchall()
    conn.execute(
        "DELETE FROM image_analytics WHERE processed_at < ?",
        (cutoff_iso,),
    )
    conn.commit()
    return [str(row["output_path"]) for row in rows]


T = TypeVar("T")


def retry_sqlite(fn: Callable[[], T], attempts: int = 5, base_delay_seconds: float = 0.2) -> T:
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            return fn()
        except sqlite3.OperationalError as exc:
            last_exc = exc
            message = str(exc).lower()
            if "locked" not in message and "busy" not in message:
                raise
            if attempt == attempts - 1:
                raise
            time.sleep(base_delay_seconds * (attempt + 1))
    raise last_exc if last_exc is not None else RuntimeError("sqlite retry failed")
