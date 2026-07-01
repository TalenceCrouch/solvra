# Solvra

Echelon Proxy

Solvra is a backend-heavy payments operations CLI for transaction syncing, webhook replay, ledger reconciliation, and revenue/risk analytics.

Milestone 2 adds the first core payment and ledger schema. It includes a Typer CLI, Rich terminal output, environment-based settings, SQLAlchemy 2.x models, pytest tests, and ruff setup.

Planned later: transaction syncing, webhook replay, ledger reconciliation, and revenue/risk analytics. There is no ingestion, replay, reconciliation, reporting, or payment processing logic yet.

## Install locally

```bash
python -m pip install -e ".[dev]"
```

## Run

```bash
solvra status
solvra init-db
```

## Test

```bash
pytest
ruff format --check .
ruff check .
```
