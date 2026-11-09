"""Receive signed order.created events over loopback HTTP. Python 3.10+."""
import argparse
from contextlib import closing
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import re
import sqlite3
import time

ID = re.compile(r"[A-Za-z0-9_-]{1,80}")
MAX_BODY = 16384
MAX_AGE = 300


def sign(secret, timestamp, body):
    message = timestamp.encode("ascii") + b"." + body
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


def verified(secret, timestamp, signature, body):
    if not re.fullmatch(r"[0-9]{1,12}", timestamp):
        return False
    if abs(time.time() - int(timestamp)) > MAX_AGE:
        return False
    return bool(re.fullmatch("[a-f0-9]{64}", signature)) and hmac.compare_digest(
        sign(secret, timestamp, body), signature
    )


def parse_event(body):
    event = json.loads(body.decode("utf-8"))
    if not isinstance(event, dict) or event.get("type") != "order.created":
        raise ValueError("Expected an order.created event")
    for field in ("event_id", "order_id"):
        if not isinstance(event.get(field), str) or not ID.fullmatch(event[field]):
            raise ValueError(f"Invalid {field}")
    if type(event.get("units")) is not int or not 1 <= event["units"] <= 100000:
        raise ValueError("units must be an integer from 1 to 100000")
    return event


def record(path, event):
    """Serialize competing writers. A retry may never create another order."""
    values = (event["event_id"], event["order_id"], event["units"])
    with closing(sqlite3.connect(path, timeout=5)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        prior = db.execute("SELECT order_id, units FROM orders WHERE event_id=?", values[:1]).fetchone()
        if prior:
            if prior == values[1:]:
                return 200, "duplicate"
            return 409, "event_conflict"
        try:
            db.execute("INSERT INTO orders(event_id, order_id, units) VALUES (?, ?, ?)", values)
        except sqlite3.IntegrityError:
            return 409, "order_conflict"
    return 201, "created"


class Receiver(BaseHTTPRequestHandler):
    def respond(self, code, status):
        data = json.dumps({"status": status}).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        if self.path != "/webhooks/orders":
            return self.respond(404, "unknown_route")
        if self.headers.get_content_type() != "application/json":
            return self.respond(415, "expected_json")
        size = self.headers.get("Content-Length", "")
        if not re.fullmatch("[0-9]{1,12}", size):
            return self.respond(411, "length_required")
        if int(size) > MAX_BODY:
            return self.respond(413, "payload_too_large")
        body = self.rfile.read(int(size))
        if not verified(self.server.secret, self.headers.get("X-Timestamp", ""),
                        self.headers.get("X-Signature", ""), body):
            return self.respond(401, "invalid_signature_or_timestamp")
        try:
            event = parse_event(body)
        except (ValueError, RecursionError):
            return self.respond(422, "invalid_event")
        try:
            code, status = record(self.server.database, event)
        except sqlite3.OperationalError:
            return self.respond(503, "storage_unavailable")
        self.respond(code, status)


def make_server(path, secret, port):
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("""CREATE TABLE IF NOT EXISTS orders (
            event_id TEXT PRIMARY KEY, order_id TEXT NOT NULL UNIQUE, units INTEGER NOT NULL
        )""")
    service = ThreadingHTTPServer(("127.0.0.1", port), Receiver)
    service.database = path
    service.secret = secret
    return service


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--database", default="orders.sqlite3")
    args = parser.parse_args()
    key = os.environ.get("WEBHOOK_SECRET")
    if not key:
        parser.error("Set WEBHOOK_SECRET to a local demo secret, or run python demo.py")
    with make_server(args.database, key.encode(), args.port) as receiver:
        print(f"Listening on http://127.0.0.1:{receiver.server_port}/webhooks/orders", flush=True)
        receiver.serve_forever()
