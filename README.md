# Solvra

Echelon Proxy

Solvra is a backend-heavy payments operations CLI for transaction syncing, webhook replay, ledger reconciliation, and revenue/risk analytics.

Milestone 4 adds read-only query commands for local fake payment data. It includes a Typer CLI, Rich terminal output, environment-based settings, SQLAlchemy 2.x models, fake sample data, pytest tests, and ruff setup.

Planned later: webhook replay, ledger reconciliation, and revenue/risk analytics. There is no replay, reconciliation, reporting, Stripe integration, or real payment processing logic yet.

## Install locally

```bash
python -m pip install -e ".[dev]"
```

## Run

```bash
solvra status
solvra init-db
solvra ingest samples/payments.json
solvra payments list
solvra payments show pay_demo_001
solvra customers list
solvra refunds list
```

These commands inspect fake local data only. Solvra does not process real payments.

## Test

```bash
pytest
ruff format --check .
ruff check .
```
