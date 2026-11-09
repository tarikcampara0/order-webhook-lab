# Order Webhook Lab

**Buyer question:** If an order system times out and sends the same event twice, could fulfillment ship twice?

This Python integration lab accepts signed order events over real HTTP, records orders in SQLite, and lets a sales engineer demonstrate exactly what happens during retries and conflicting deliveries. Northline Supply and its order data are fictional.

## Run the live demo

With Python 3.10 or newer, run these commands from the repository directory:

```sh
python demo.py
python -m unittest -v
```

The demo starts its own loopback server on a free port, signs requests with a temporary key, and inspects the resulting database. It needs no cloud account, credentials, or third-party packages. Every run starts clean.

| Try this in the demo | HTTP response | Fulfillment outcome |
| --- | --- | --- |
| Deliver an order for 12 units | 201 created | One order stored |
| Retry the same event | 200 duplicate | Same order acknowledged |
| Modify the signed body or send an expired request | 401 | Request rejected |
| Reuse an event ID with different order details | 409 event_conflict | Original record retained |
| Send another event ID for an existing order | 409 order_conflict | Conflict surfaced for review |

## Walk a buyer through it

1. Ask the integration owner how their sender retries after a lost acknowledgement. Agree on stable identifiers for both the delivery event and the business order.
2. Run the demo. Compare the first two responses and the final database check. Ask which response the sender should retry. A successful duplicate acknowledgement closes the retry loop.
3. Show the two 409s. Ask the operations lead who investigates conflicting quantities or identifiers. Discuss a reconciliation queue and audit trail before a production rollout.

## Integration contract

Send a JSON object to `POST /webhooks/orders` with `type` set to `order.created`, string `event_id` and `order_id`, and integer `units` from 1 through 100,000. IDs accept letters, digits, underscores and hyphens up to 80 characters. Set `Content-Type: application/json` and send a content length.

`X-Timestamp` contains Unix seconds. `X-Signature` is the lowercase hex HMAC-SHA256 of the timestamp, a period, and the exact request body. The receiver allows five minutes of clock skew. SQLite serializes writers and enforces uniqueness on both identifiers. A storage failure returns 503 so the sender can retry.

For a persistent local receiver, set `WEBHOOK_SECRET` in the environment and run `python server.py --database orders.sqlite3 --port 8080`. The client helper in `demo.py` shows the signing protocol. The server binds to loopback. A production deployment would also need TLS termination, managed key rotation, durable operational monitoring, and a reconciliation workflow.
