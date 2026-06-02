#!/usr/bin/env python3
import sqlite3
from dataclasses import dataclass
from pathlib import Path


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
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
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
