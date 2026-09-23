"""Comparison client that transmits every key event directly to the server."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import random
import time
from datetime import datetime, timezone
from pathlib import Path

import requests


SERVER_URL = os.getenv("DIRECT_SERVER_URL", "http://localhost:5001")
API_KEY = os.getenv("EDGE_API_KEY", "dev-key")
REGION_ID = os.getenv("REGION_ID", "vilnius")
QUEUE_FILE = Path(os.getenv("DIRECT_QUEUE_FILE", "data/direct_pending.jsonl"))


class DirectClient:
    def __init__(self, user_id: str):
        self.user_id = user_id
        self.session = requests.Session()
        self.headers = {"X-API-Key": API_KEY}
        QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)

    def register(self) -> None:
        response = self.session.post(
            f"{SERVER_URL}/register",
            json={"user_id": self.user_id, "region_id": REGION_ID},
            headers=self.headers,
            timeout=5,
        )
        response.raise_for_status()
        self.flush_queue()

    def _payload(self, key) -> dict:
        return {
            "user_id": self.user_id,
            "region_id": REGION_ID,
            "event_time": datetime.now(timezone.utc).isoformat(),
            "key": str(key),
        }

    def _queue(self, payload: dict) -> None:
        with QUEUE_FILE.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload) + "\n")

    def flush_queue(self) -> None:
        """Retry raw events retained during an earlier connection failure."""
        if not QUEUE_FILE.exists():
            return
        lines = QUEUE_FILE.read_text(encoding="utf-8").splitlines()
        remaining = []
        for index, line in enumerate(lines):
            try:
                payload = json.loads(line)
                response = self.session.post(
                    f"{SERVER_URL}/event",
                    json=payload,
                    headers=self.headers,
                    timeout=3,
                )
                response.raise_for_status()
            except (ValueError, requests.RequestException):
                remaining.extend(lines[index:])
                break
        if remaining:
            QUEUE_FILE.write_text("\n".join(remaining) + "\n", encoding="utf-8")
        else:
            QUEUE_FILE.unlink(missing_ok=True)

    def send_key(self, key) -> None:
        payload = self._payload(key)
        try:
            self.flush_queue()
            response = self.session.post(
                f"{SERVER_URL}/event", json=payload, headers=self.headers, timeout=3
            )
            response.raise_for_status()
        except requests.RequestException:
            self._queue(payload)


def run_simulation(client: DirectClient, events: int) -> None:
    keys = list("abcdefghijklmnopqrstuvwxyz")
    print(f"Simulation mode: sending {events} raw key events")
    for _ in range(events):
        client.send_key(random.choice(keys))
    response = client.session.post(
        f"{SERVER_URL}/evaluate-now", headers=client.headers, timeout=5
    )
    response.raise_for_status()
    print("Evaluation:", response.json())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--user", default=getpass.getuser())
    parser.add_argument("--simulate", type=int, metavar="EVENTS")
    args = parser.parse_args()

    client = DirectClient(args.user)
    client.register()
    if args.simulate is not None:
        run_simulation(client, args.simulate)
        return

    try:
        from pynput import keyboard
    except ImportError as exc:
        raise SystemExit("Install requirements.txt or use --simulate") from exc
    print("Live direct-transmission mode started. Press Ctrl+C to stop.")
    with keyboard.Listener(on_press=client.send_key) as listener:
        listener.join()


if __name__ == "__main__":
    main()
