from typer.testing import CliRunner

from solvra.cli import app

runner = CliRunner()


def test_help_exits_successfully() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0


def test_status_exits_successfully() -> None:
    result = runner.invoke(app, ["status"])

    assert result.exit_code == 0


def test_status_output_contains_solvra() -> None:
    result = runner.invoke(app, ["status"])

    assert "Solvra" in result.output


def test_init_db_exits_successfully(tmp_path) -> None:
    database_path = tmp_path / "solvra-test.db"
    result = runner.invoke(
        app,
        ["init-db"],
        env={"SOLVRA_DATABASE_URL": f"sqlite:///{database_path.as_posix()}"},
    )

    assert result.exit_code == 0
    assert database_path.exists()


def test_status_does_not_print_raw_database_password() -> None:
    result = runner.invoke(
        app,
        ["status"],
        env={
            "SOLVRA_DATABASE_URL": "postgresql://solvra:secret-password@example.test/solvra"
        },
    )

    assert result.exit_code == 0
    assert "secret-password" not in result.output


def test_cli_does_not_expose_future_workflow_commands() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    for command in ("replay", "reconcile", "revenue", "risk"):
        assert command not in result.output


def test_query_command_groups_appear_in_cli_help() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "payments" in result.output
    assert "customers" in result.output
    assert "refunds" in result.output
    assert "events" in result.output


def test_payment_commands_appear_in_help() -> None:
    result = runner.invoke(app, ["payments", "--help"])

    assert result.exit_code == 0
    assert "list" in result.output
    assert "show" in result.output


def test_event_commands_appear_in_help() -> None:
    result = runner.invoke(app, ["events", "--help"])

    assert result.exit_code == 0
    assert "ingest" in result.output
    assert "list" in result.output
    assert "show" in result.output


def test_ingest_exits_successfully(tmp_path) -> None:
    database_path = tmp_path / "solvra-ingest.db"
    result = runner.invoke(
        app,
        ["ingest", "samples/payments.json"],
        env={"SOLVRA_DATABASE_URL": f"sqlite:///{database_path.as_posix()}"},
    )

    assert result.exit_code == 0
    assert "Ingestion summary" in result.output
