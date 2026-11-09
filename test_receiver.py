from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
import secrets
import sqlite3
import tempfile
import threading
import unittest

from demo import send
from server import make_server, parse_event, record


class DeliveryTests(unittest.TestCase):
    def test_simultaneous_retries_and_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "orders.db"
            key = secrets.token_bytes(32)
            event = dict(type="order.created", event_id="evt-a", order_id="ord-a", units=7)
            with make_server(path, key, 0) as server:
                thread = threading.Thread(target=server.serve_forever)
                thread.start()
                try:
                    with ThreadPoolExecutor(max_workers=6) as pool:
                        replies = list(pool.map(lambda _: send(server.server_port, key, event), range(6)))
                    self.assertCountEqual(replies, [(201, "created")] + [(200, "duplicate")] * 5)
                    self.assertEqual(send(server.server_port, key, dict(event, units=True))[0], 422)
                finally:
                    server.shutdown()
                    thread.join()
            with make_server(path, key, 0):
                self.assertEqual(record(path, event), (200, "duplicate"))
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute("SELECT count(*), sum(units) FROM orders").fetchone(), (1, 7))

    def test_malformed_payload(self):
        for body in (b"{", b"[]", b"{}", b"null", b"\xff"):
            with self.subTest(body=body), self.assertRaises(ValueError):
                parse_event(body)


if __name__ == "__main__":
    unittest.main()
