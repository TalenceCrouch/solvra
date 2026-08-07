from sqlalchemy import inspect

from solvra.config import Settings
from solvra.db import initialize_database, sqlite_database_path

EXPECTED_TABLES = {
    "customers",
    "ledger_entries",
    "merchant_accounts",
    "payments",
    "reconciliation_runs",
    "refunds",
    "webhook_events",
}


def test_sqlite_database_file_creation(tmp_path) -> None:
    database_path = tmp_path / "nested" / "solvra-test.db"
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{database_path.as_posix()}",
    )

    initialize_database(settings)

    assert database_path.exists()


def test_initialize_database_creates_model_tables(tmp_path) -> None:
    database_path = tmp_path / "solvra-test.db"
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{database_path.as_posix()}",
    )

    engine = initialize_database(settings)

    assert EXPECTED_TABLES <= set(inspect(engine).get_table_names())


def test_sqlite_memory_database_has_no_file_path() -> None:
    assert sqlite_database_path("sqlite:///:memory:") is None
