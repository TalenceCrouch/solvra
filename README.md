# Solvra

Echelon Proxy

Solvra is a backend-heavy payments operations CLI for transaction syncing, webhook replay, ledger reconciliation, and revenue/risk analytics.

Milestone 8 adds basic local reconciliation mismatch detection. It includes a Typer CLI, Rich terminal output, environment-based settings, SQLAlchemy 2.x models, fake sample data, pytest tests, and ruff setup.

Planned later: revenue/risk analytics. There is no Stripe integration or real payment processing logic yet.

## Install locally

```bash
python -m pip install -e ".[dev]"
```

## Run

```bash
solvra status
solvra init-db
solvra ingest samples/payments.json
solvra events ingest samples/webhook_events.json
solvra events list
solvra events show evt_demo_001
solvra events replay evt_demo_001
solvra events replay --type payment.succeeded
solvra reconcile run
solvra reconcile history
solvra reconcile mismatches
solvra reconcile show <run_id>
solvra payments list
solvra payments show pay_demo_001
solvra customers list
solvra refunds list
```

Replay, reconciliation, and mismatch detection use stored fake local data only. Solvra does not process real payments or connect to Stripe.

## Test

```bash
pytest
ruff format --check .
ruff check .
```
