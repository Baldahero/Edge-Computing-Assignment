"""Automated functional checks for both Flask servers."""

from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path

import direct_server
import edge_server
from common import initialise_database


HEADERS = {"X-API-Key": "dev-key"}


def test_edge(tmp: Path) -> None:
    edge_server.DB_PATH = str(tmp / "edge.db")
    edge_server.EXPECTED_USERS = 1
    edge_server.pending.clear()
    initialise_database(edge_server.DB_PATH)
    client = edge_server.app.test_client()
    assert client.get("/health").status_code == 200
    assert client.get("/report/alice").status_code == 401
    assert client.post(
        "/register", json={"user_id": "alice", "region_id": "vilnius"}, headers=HEADERS
    ).status_code == 201
    response = client.post(
        "/aggregate",
        json={
            "user_id": "alice",
            "region_id": "vilnius",
            "interval_start": "2026-09-23T08:00:00+00:00",
            "interval_end": "2026-09-23T08:15:00+00:00",
            "key_count": 30,
        },
        headers=HEADERS,
    )
    assert response.status_code == 200
    assert response.get_json()["result"]["statuses"]["alice"] == "WORKING"
    report = client.get("/report/alice", headers=HEADERS).get_json()
    assert report["summary"]["WORKING"] == 1

    # Regional rule: four active users out of five means business hours.
    edge_server.EXPECTED_USERS = 5
    edge_server.pending.clear()
    for index in range(5):
        response = client.post(
            "/aggregate",
            json={
                "user_id": f"team-{index}",
                "region_id": "kaunas",
                "interval_start": "2026-09-23T10:00:00+00:00",
                "interval_end": "2026-09-23T10:15:00+00:00",
                "key_count": 25 if index < 4 else 0,
            },
            headers=HEADERS,
        )
    result = response.get_json()["result"]
    assert result["business_hours"] is True
    assert result["statuses"]["team-0"] == "WORKING"
    assert result["statuses"]["team-4"] == "ABSENT"


def test_direct(tmp: Path) -> None:
    direct_server.DB_PATH = str(tmp / "direct.db")
    direct_server.WINDOW_SECONDS = 900
    initialise_database(direct_server.DB_PATH, include_raw_events=True)
    client = direct_server.app.test_client()
    assert client.get("/health").status_code == 200
    assert client.post("/evaluate-now").status_code == 401
    client.post(
        "/register", json={"user_id": "bob", "region_id": "vilnius"}, headers=HEADERS
    )
    for index in range(25):
        response = client.post(
            "/event",
            json={
                "user_id": "bob",
                "region_id": "vilnius",
                "event_time": "2026-09-23T09:01:00+00:00",
                "key": f"key-{index}",
            },
            headers=HEADERS,
        )
        assert response.status_code == 202
    evaluated = client.post("/evaluate-now", headers=HEADERS)
    assert evaluated.status_code == 200
    report = client.get("/report/bob", headers=HEADERS).get_json()
    assert report["summary"]["WORKING"] == 1
    too_long = client.post(
        "/event",
        json={
            "user_id": "bob",
            "region_id": "vilnius",
            "event_time": datetime.now(timezone.utc).isoformat(),
            "key": "x" * 65,
        },
        headers=HEADERS,
    )
    assert too_long.status_code == 400


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        test_edge(root)
        test_direct(root)
    print("SUCCESS: edge aggregation and direct transmission solutions passed.")
