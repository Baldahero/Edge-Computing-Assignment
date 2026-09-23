"""Client that counts key presses locally and sends one aggregate per window."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import random
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import requests


SERVER_URL = os.getenv("EDGE_SERVER_URL", "http://localhost:5000")
API_KEY = os.getenv("EDGE_API_KEY", "dev-key")
REGION_ID = os.getenv("REGION_ID", "vilnius")
WINDOW_SECONDS = int(os.getenv("WINDOW_SECONDS", "900"))
QUEUE_FILE = Path(os.getenv("EDGE_QUEUE_FILE", "data/edge_pending.jsonl"))


class EdgeClient:
    def __init__(self, user_id: str):
        self.user_id = user_id
        self.key_count = 0
        self.lock = threading.Lock()
        self.interval_start = datetime.now(timezone.utc)
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

    def on_key_press(self, _key=None) -> None:
        # Only the count is retained. The pressed key is deliberately discarded.
        with self.lock:
            self.key_count += 1

    def _queue(self, payload: dict) -> None:
        with QUEUE_FILE.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload) + "\n")

    def flush_queue(self) -> None:
        if not QUEUE_FILE.exists():
            return
        lines = QUEUE_FILE.read_text(encoding="utf-8").splitlines()
        remaining = []
        for line in lines:
            try:
                payload = json.loads(line)
                response = self.session.post(
                    f"{SERVER_URL}/aggregate",
                    json=payload,
                    headers=self.headers,
                    timeout=5,
                )
                response.raise_for_status()
            except (ValueError, requests.RequestException):
                remaining.append(line)
        if remaining:
            QUEUE_FILE.write_text("\n".join(remaining) + "\n", encoding="utf-8")
        else:
            QUEUE_FILE.unlink(missing_ok=True)

    def send_window(self) -> None:
        now = datetime.now(timezone.utc)
        with self.lock:
            count = self.key_count
            self.key_count = 0
            start = self.interval_start
            self.interval_start = now
        payload = {
            "user_id": self.user_id,
            "region_id": REGION_ID,
            "interval_start": start.isoformat(),
            "interval_end": now.isoformat(),
            "key_count": count,
        }
        try:
            self.flush_queue()
            response = self.session.post(
                f"{SERVER_URL}/aggregate",
                json=payload,
                headers=self.headers,
                timeout=5,
            )
            response.raise_for_status()
            print("Aggregate sent:", response.json())
        except requests.RequestException as exc:
            self._queue(payload)
            print("Server unavailable; aggregate queued locally:", exc)

    def periodic_sender(self) -> None:
        while True:
            time.sleep(WINDOW_SECONDS)
            self.send_window()


def run_simulation(client: EdgeClient, windows: int) -> None:
    print(f"Simulation mode: {windows} windows, {WINDOW_SECONDS} seconds each")
    for _ in range(windows):
        for _ in range(random.randint(0, 35)):
            client.on_key_press()
        client.send_window()
        time.sleep(0.2)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--user", default=getpass.getuser())
    parser.add_argument("--simulate", type=int, metavar="WINDOWS")
    args = parser.parse_args()

    client = EdgeClient(args.user)
    client.register()
    if args.simulate is not None:
        run_simulation(client, args.simulate)
        return

    try:
        from pynput import keyboard
    except ImportError as exc:
        raise SystemExit("Install requirements.txt or use --simulate") from exc
    threading.Thread(target=client.periodic_sender, daemon=True).start()
    print("Live mode started. Press Ctrl+C to stop.")
    with keyboard.Listener(on_press=client.on_key_press) as listener:
        listener.join()


if __name__ == "__main__":
    main()
