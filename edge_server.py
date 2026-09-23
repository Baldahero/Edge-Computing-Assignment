"""Server for the privacy-preserving edge aggregation solution."""

from __future__ import annotations

import os
import threading
from collections import defaultdict
from datetime import datetime

from flask import Flask, jsonify, request

from common import (
    classify_counts,
    initialise_database,
    register_user,
    report_for_user,
    save_activity,
)


DB_PATH = os.getenv("EDGE_DB_PATH", "data/edge_activity.db")
API_KEY = os.getenv("EDGE_API_KEY", "dev-key")
ACTIVE_THRESHOLD = int(os.getenv("ACTIVE_THRESHOLD", "20"))
BUSY_RATIO = float(os.getenv("BUSY_RATIO", "0.8"))
EXPECTED_USERS = int(os.getenv("EXPECTED_USERS", "1"))

app = Flask(__name__)
initialise_database(DB_PATH)

# pending[(region_id, interval_start, interval_end)] = {user_id: key_count}
pending: dict[tuple[str, str, str], dict[str, int]] = defaultdict(dict)
pending_lock = threading.Lock()


def authorised() -> bool:
    return request.headers.get("X-API-Key") == API_KEY


def valid_iso8601(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


@app.get("/health")
def health():
    return jsonify({"status": "ok", "solution": "edge-aggregation"})


@app.post("/register")
def register():
    if not authorised():
        return jsonify({"error": "unauthorised"}), 401
    data = request.get_json(silent=True) or {}
    user_id = data.get("user_id")
    region_id = data.get("region_id", "default")
    if not isinstance(user_id, str) or not user_id.strip():
        return jsonify({"error": "user_id is required"}), 400
    if not isinstance(region_id, str) or not region_id.strip():
        return jsonify({"error": "region_id is required"}), 400
    register_user(DB_PATH, user_id.strip(), region_id.strip())
    return jsonify({"status": "registered"}), 201


@app.post("/aggregate")
def aggregate():
    if not authorised():
        return jsonify({"error": "unauthorised"}), 401
    data = request.get_json(silent=True) or {}
    required = ("user_id", "region_id", "interval_start", "interval_end", "key_count")
    if any(field not in data for field in required):
        return jsonify({"error": "missing required field"}), 400
    if not valid_iso8601(data["interval_start"]) or not valid_iso8601(data["interval_end"]):
        return jsonify({"error": "invalid interval timestamp"}), 400
    if not isinstance(data["key_count"], int) or data["key_count"] < 0:
        return jsonify({"error": "key_count must be a non-negative integer"}), 400

    if not isinstance(data["user_id"], str) or not data["user_id"].strip():
        return jsonify({"error": "user_id is required"}), 400
    if not isinstance(data["region_id"], str) or not data["region_id"].strip():
        return jsonify({"error": "region_id is required"}), 400
    if len(data["user_id"]) > 128 or len(data["region_id"]) > 128:
        return jsonify({"error": "identifier is too long"}), 400
    user_id = data["user_id"].strip()
    region_id = data["region_id"].strip()
    key = (region_id, data["interval_start"], data["interval_end"])
    register_user(DB_PATH, user_id, region_id)

    processed = False
    result = None
    with pending_lock:
        pending[key][user_id] = data["key_count"]
        if len(pending[key]) >= EXPECTED_USERS:
            counts = dict(pending.pop(key))
            statuses, business_hours, active_ratio = classify_counts(
                counts, ACTIVE_THRESHOLD, BUSY_RATIO
            )
            save_activity(
                DB_PATH, region_id, key[1], key[2], counts, statuses
            )
            processed = True
            result = {
                "business_hours": business_hours,
                "active_ratio": round(active_ratio, 3),
                "statuses": statuses,
            }

    return jsonify({"status": "accepted", "processed": processed, "result": result})


@app.get("/report/<user_id>")
def report(user_id: str):
    if not authorised():
        return jsonify({"error": "unauthorised"}), 401
    return jsonify({"user_id": user_id, "summary": report_for_user(DB_PATH, user_id)})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("EDGE_PORT", "5000")))
