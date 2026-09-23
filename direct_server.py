"""Server for the direct/raw keystroke transmission comparison solution."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from flask import Flask, jsonify, request

from common import (
    classify_counts,
    connect,
    initialise_database,
    register_user,
    report_for_user,
    save_activity,
)


DB_PATH = os.getenv("DIRECT_DB_PATH", "data/direct_activity.db")
API_KEY = os.getenv("EDGE_API_KEY", "dev-key")
ACTIVE_THRESHOLD = int(os.getenv("ACTIVE_THRESHOLD", "20"))
BUSY_RATIO = float(os.getenv("BUSY_RATIO", "0.8"))
WINDOW_SECONDS = int(os.getenv("WINDOW_SECONDS", "900"))

app = Flask(__name__)
initialise_database(DB_PATH, include_raw_events=True)


def authorised() -> bool:
    return request.headers.get("X-API-Key") == API_KEY


def parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def interval_bounds(timestamp: datetime) -> tuple[datetime, datetime]:
    epoch = int(timestamp.timestamp())
    start_epoch = epoch - (epoch % WINDOW_SECONDS)
    start = datetime.fromtimestamp(start_epoch, timezone.utc)
    return start, start + timedelta(seconds=WINDOW_SECONDS)


def finalise_closed_intervals(force: bool = False) -> int:
    now = datetime.now(timezone.utc)
    with connect(DB_PATH) as db:
        rows = db.execute(
            "SELECT DISTINCT region_id, event_time FROM raw_events WHERE processed=0"
        ).fetchall()
    intervals: set[tuple[str, datetime, datetime]] = set()
    for row in rows:
        event_time = parse_timestamp(row["event_time"])
        if event_time is None:
            continue
        start, end = interval_bounds(event_time)
        if force or end <= now:
            intervals.add((row["region_id"], start, end))

    processed = 0
    for region_id, start, end in sorted(intervals, key=lambda item: item[1]):
        start_iso, end_iso = start.isoformat(), end.isoformat()
        with connect(DB_PATH) as db:
            users = [
                row["user_id"]
                for row in db.execute(
                    "SELECT user_id FROM users WHERE region_id=?", (region_id,)
                ).fetchall()
            ]
            counts = {user_id: 0 for user_id in users}
            event_rows = db.execute(
                """SELECT user_id, COUNT(*) AS total FROM raw_events
                   WHERE region_id=? AND event_time>=? AND event_time<?
                   GROUP BY user_id""",
                (region_id, start_iso, end_iso),
            ).fetchall()
            for row in event_rows:
                counts[row["user_id"]] = row["total"]
            statuses, _, _ = classify_counts(counts, ACTIVE_THRESHOLD, BUSY_RATIO)
            save_activity(DB_PATH, region_id, start_iso, end_iso, counts, statuses)
            db.execute(
                """UPDATE raw_events SET processed=1
                   WHERE region_id=? AND event_time>=? AND event_time<?""",
                (region_id, start_iso, end_iso),
            )
            processed += 1
    return processed


@app.get("/health")
def health():
    return jsonify({"status": "ok", "solution": "direct-raw-events"})


@app.post("/register")
def register():
    if not authorised():
        return jsonify({"error": "unauthorised"}), 401
    data = request.get_json(silent=True) or {}
    user_id = data.get("user_id")
    region_id = data.get("region_id", "default")
    if not isinstance(user_id, str) or not user_id.strip():
        return jsonify({"error": "user_id is required"}), 400
    register_user(DB_PATH, user_id.strip(), str(region_id))
    return jsonify({"status": "registered"}), 201


@app.post("/event")
def event():
    if not authorised():
        return jsonify({"error": "unauthorised"}), 401
    data = request.get_json(silent=True) or {}
    user_id = data.get("user_id")
    region_id = data.get("region_id")
    event_time = parse_timestamp(data.get("event_time"))
    key_value = data.get("key")
    if not all(isinstance(value, str) and value for value in (user_id, region_id, key_value)):
        return jsonify({"error": "user_id, region_id and key are required"}), 400
    if len(user_id) > 128 or len(region_id) > 128 or len(key_value) > 64:
        return jsonify({"error": "input value is too long"}), 400
    if event_time is None:
        return jsonify({"error": "invalid event_time"}), 400
    user_id = user_id.strip()
    region_id = region_id.strip()
    register_user(DB_PATH, user_id, region_id)
    with connect(DB_PATH) as db:
        db.execute(
            "INSERT INTO raw_events(user_id, region_id, event_time, key_value) VALUES (?, ?, ?, ?)",
            (user_id, region_id, event_time.isoformat(), key_value),
        )
    finalise_closed_intervals()
    return jsonify({"status": "accepted"}), 202


@app.post("/evaluate-now")
def evaluate_now():
    if not authorised():
        return jsonify({"error": "unauthorised"}), 401
    return jsonify({"processed_intervals": finalise_closed_intervals(force=True)})


@app.get("/report/<user_id>")
def report(user_id: str):
    if not authorised():
        return jsonify({"error": "unauthorised"}), 401
    finalise_closed_intervals()
    return jsonify({"user_id": user_id, "summary": report_for_user(DB_PATH, user_id)})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("DIRECT_PORT", "5001")))
