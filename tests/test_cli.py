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
