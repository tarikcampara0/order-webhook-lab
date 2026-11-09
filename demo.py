"""Run the buyer demo with a temporary SQLite database and fresh signing key."""
from contextlib import closing
import http.client
import json
from pathlib import Path
import secrets
import sqlite3
import tempfile
import threading
import time

from server import make_server, sign


def send(port, key, event, *, timestamp=None, tamper=False):
    body = json.dumps(event, separators=(",", ":")).encode()
    stamp = str(int(time.time()) if timestamp is None else timestamp)
    signature = sign(key, stamp, body)
    if tamper:
        body += b" "
    with closing(http.client.HTTPConnection("127.0.0.1", port, timeout=5)) as client:
        client.request("POST", "/webhooks/orders", body, {
            "Content-Type": "application/json", "X-Timestamp": stamp, "X-Signature": signature
        })
        response = client.getresponse()
        return response.status, json.load(response)["status"]


def main():
    key = secrets.token_bytes(32)
    order = dict(type="order.created", event_id="evt-042", order_id="NL-1042", units=12)
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "orders.sqlite3"
        with make_server(database, key, 0) as service:
            worker = threading.Thread(target=service.serve_forever, daemon=True)
            worker.start()
            try:
                cases = [
                    ("Original delivery", order, {}, (201, "created")),
                    ("Retry after lost acknowledgement", order, {}, (200, "duplicate")),
                    ("Body changed in transit", order, {"tamper": True}, (401, "invalid_signature_or_timestamp")),
                    ("Expired signed request", order, {"timestamp": int(time.time()) - 600}, (401, "invalid_signature_or_timestamp")),
                    ("Event ID reused with new units", dict(order, units=13), {}, (409, "event_conflict")),
                    ("New event for the same order", dict(order, event_id="evt-043"), {}, (409, "order_conflict")),
                ]
                for name, payload, options, expected in cases:
                    actual = send(service.server_port, key, payload, **options)
                    print(f"{name:34} {actual[0]}  {actual[1]}")
                    if actual != expected:
                        raise RuntimeError(f"Expected {expected}, received {actual}")
                with closing(sqlite3.connect(database)) as db:
                    rows = db.execute("SELECT order_id, units FROM orders").fetchall()
                if rows != [("NL-1042", 12)]:
                    raise RuntimeError(f"Unexpected orders: {rows}")
                print("Inventory outcome: 1 order recorded, 12 units.")
            finally:
                service.shutdown()
                worker.join()


if __name__ == "__main__":
    main()
