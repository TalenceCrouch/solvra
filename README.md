# Solvra

Echelon Proxy

Solvra is a backend payments-ops CLI demo for fake local payment data.

It covers ingestion, querying, webhook simulation, reconciliation, revenue summary, and a local risk scan. Solvra does not process real payments or connect to Stripe.

## Install locally

```bash
python -m pip install -e ".[dev]"
```

## Demo

```bash
solvra status
solvra init-db
solvra ingest samples/payments.json
solvra events ingest samples/webhook_events.json
solvra payments list
solvra events list
solvra events replay --type payment.succeeded
solvra reconcile run
solvra reconcile mismatches
solvra revenue summary
solvra risk scan
```

Everything in this demo stays local and uses fake data.

## Test

```bash
pytest
ruff format --check .
ruff check .
```
