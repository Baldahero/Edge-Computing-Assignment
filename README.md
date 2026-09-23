# Edge Computing Assignment

This project contains two implementations of the employee-activity example:

1. **Edge aggregation**: the client counts key presses locally and sends one count per interval.
2. **Direct transmission**: the client sends every key event to the server for server-side aggregation.

The live keyboard mode is intended only for a transparent, consent-based classroom demonstration. Use `--simulate` when real keyboard capture is unnecessary.

Repository: <https://github.com/Baldahero/Edge-Computing-Assignment>

## Installation

```bash
python -m pip install -r requirements.txt
```

## Solution A: edge aggregation

Terminal 1:

```bash
python edge_server.py
```

Terminal 2 (safe simulation):

```bash
WINDOW_SECONDS=10 python edge_client.py --user demo-user --simulate 3
```

Report:

```bash
curl -H "X-API-Key: dev-key" http://localhost:5000/report/demo-user
```

## Solution B: direct transmission

Terminal 1:

```bash
python direct_server.py
```

Terminal 2 (safe simulation):

```bash
python direct_client.py --user demo-user --simulate 25
```

Report:

```bash
curl -H "X-API-Key: dev-key" http://localhost:5001/report/demo-user
```

## Automated verification

```bash
python test_solutions.py
```

Expected output:

```text
SUCCESS: edge aggregation and direct transmission solutions passed.
```

The same verification is executed automatically by GitHub Actions after every push.

## Configuration

- `EDGE_API_KEY`: shared demonstration API key. Change it outside a local demo.
- `ACTIVE_THRESHOLD`: minimum key count for an active interval (default `20`).
- `BUSY_RATIO`: active employee ratio used to detect business hours (default `0.8`).
- `WINDOW_SECONDS`: aggregation window (default `900`, which is 15 minutes).
- `EXPECTED_USERS`: number of aggregate submissions required before edge evaluation.
- `REGION_ID`: client region (default `vilnius`).

Production deployment should use HTTPS, individual client credentials, explicit employee consent, a retention policy, access controls, audit logging and applicable privacy-law review.
