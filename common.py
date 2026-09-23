"""Shared database and classification helpers for both implementations."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Mapping


STATUSES = ("WORKING", "ABSENT", "OVERTIME", "OFF_HOURS")


def connect(db_path: str) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path, timeout=10)
    connection.row_factory = sqlite3.Row
    return connection


def initialise_database(db_path: str, include_raw_events: bool = False) -> None:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with connect(db_path) as db:
        db.execute(
            """CREATE TABLE IF NOT EXISTS users (
                   user_id TEXT PRIMARY KEY,
                   region_id TEXT NOT NULL
               )"""
        )
        db.execute(
            """CREATE TABLE IF NOT EXISTS activity (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   user_id TEXT NOT NULL,
                   region_id TEXT NOT NULL,
                   interval_start TEXT NOT NULL,
                   interval_end TEXT NOT NULL,
                   key_count INTEGER NOT NULL,
                   status TEXT NOT NULL,
                   UNIQUE(user_id, interval_start, interval_end)
               )"""
        )
        if include_raw_events:
            db.execute(
                """CREATE TABLE IF NOT EXISTS raw_events (
                       id INTEGER PRIMARY KEY AUTOINCREMENT,
                       user_id TEXT NOT NULL,
                       region_id TEXT NOT NULL,
                       event_time TEXT NOT NULL,
                       key_value TEXT NOT NULL,
                       processed INTEGER NOT NULL DEFAULT 0
                   )"""
            )


def register_user(db_path: str, user_id: str, region_id: str) -> None:
    with connect(db_path) as db:
        db.execute(
            """INSERT INTO users(user_id, region_id) VALUES (?, ?)
               ON CONFLICT(user_id) DO UPDATE SET region_id=excluded.region_id""",
            (user_id, region_id),
        )


def classify_counts(
    counts: Mapping[str, int], active_threshold: int, busy_ratio: float
) -> tuple[dict[str, str], bool, float]:
    if not counts:
        return {}, False, 0.0
    active_users = sum(1 for value in counts.values() if value >= active_threshold)
    ratio = active_users / len(counts)
    business_hours = ratio >= busy_ratio
    statuses: dict[str, str] = {}
    for user_id, count in counts.items():
        if business_hours:
            statuses[user_id] = "WORKING" if count >= active_threshold else "ABSENT"
        else:
            statuses[user_id] = "OVERTIME" if count >= active_threshold else "OFF_HOURS"
    return statuses, business_hours, ratio


def save_activity(
    db_path: str,
    region_id: str,
    interval_start: str,
    interval_end: str,
    counts: Mapping[str, int],
    statuses: Mapping[str, str],
) -> None:
    with connect(db_path) as db:
        for user_id, status in statuses.items():
            db.execute(
                """INSERT INTO activity
                   (user_id, region_id, interval_start, interval_end, key_count, status)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(user_id, interval_start, interval_end)
                   DO UPDATE SET key_count=excluded.key_count, status=excluded.status""",
                (user_id, region_id, interval_start, interval_end, counts[user_id], status),
            )


def report_for_user(db_path: str, user_id: str) -> dict[str, int]:
    summary = {status: 0 for status in STATUSES}
    with connect(db_path) as db:
        rows = db.execute(
            "SELECT status, COUNT(*) AS total FROM activity WHERE user_id=? GROUP BY status",
            (user_id,),
        ).fetchall()
    for row in rows:
        if row["status"] in summary:
            summary[row["status"]] = row["total"]
    return summary
