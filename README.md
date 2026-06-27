# Solvra

Echelon Proxy

Solvra is a backend-heavy payments operations CLI for transaction syncing, webhook replay, ledger reconciliation, and revenue/risk analytics.

Milestone 0 is only the project scaffold. It includes a Typer CLI, Rich terminal output, basic environment configuration, pytest tests, and ruff setup.

Planned later: transaction syncing, webhook replay, ledger reconciliation, and revenue/risk analytics.

## Install locally

```bash
python -m pip install -e ".[dev]"
```

## Run

```bash
solvra status
```

## Test

```bash
pytest
ruff format --check .
ruff check .
```
