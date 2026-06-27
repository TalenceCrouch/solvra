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
