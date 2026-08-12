import re
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select
from typer.testing import CliRunner

from solvra.cli import app
from solvra.config import Settings
from solvra.db import create_session_factory, initialize_database
from solvra.events.service import ingest_webhook_events_file
from solvra.ingest.service import ingest_payments_file
from solvra.models import Customer, LedgerEntry, Payment, Refund, WebhookEvent
from solvra.reconcile import (
    ReconciliationRunNotFoundError,
    create_reconciliation_run,
    get_reconciliation_run,
    list_reconciliation_runs,
)

PAYMENT_SAMPLE_PATH = Path("samples/payments.json")
WEBHOOK_SAMPLE_PATH = Path("samples/webhook_events.json")
RUN_ID_PATTERN = re.compile(r"rec_[0-9a-f]{12}")
runner = CliRunner()


def make_settings(tmp_path) -> Settings:
    database_path = tmp_path / "solvra-reconcile.db"
    return Settings(
        environment="test",
        database_url=f"sqlite:///{database_path.as_posix()}",
    )


def make_env(settings: Settings) -> dict[str, str]:
    return {"SOLVRA_DATABASE_URL": settings.database_url}


def ingest_sample_data(tmp_path) -> Settings:
    settings = make_settings(tmp_path)
    ingest_payments_file(PAYMENT_SAMPLE_PATH, settings)
    ingest_webhook_events_file(WEBHOOK_SAMPLE_PATH, settings)
    return settings


def domain_counts(settings: Settings) -> tuple[int, int, int, int, int]:
    engine = initialize_database(settings)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        return (
            session.scalar(select(func.count(Customer.id))) or 0,
            session.scalar(select(func.count(Payment.id))) or 0,
            session.scalar(select(func.count(Refund.id))) or 0,
            session.scalar(select(func.count(WebhookEvent.id))) or 0,
            session.scalar(select(func.count(LedgerEntry.id))) or 0,
        )


def run_id_from_output(output: str) -> str:
    match = RUN_ID_PATTERN.search(output)
    assert match is not None
    return match.group(0)


def test_reconcile_command_group_appears_in_cli_help() -> None:
    root = runner.invoke(app, ["--help"])
    reconcile = runner.invoke(app, ["reconcile", "--help"])

    assert root.exit_code == 0
    assert reconcile.exit_code == 0
    assert "reconcile" in root.output
    assert "run" in reconcile.output
    assert "history" in reconcile.output
    assert "show" in reconcile.output


def test_reconcile_run_creates_completed_summary(tmp_path) -> None:
    settings = ingest_sample_data(tmp_path)

    summary = create_reconciliation_run(settings)

    assert summary.external_id.startswith("rec_")
    assert summary.status == "completed"
    assert summary.payment_count == 3
    assert summary.refund_count == 1
    assert summary.webhook_event_count == 4
    assert summary.currency == "usd"
    assert summary.completed_at is not None


def test_reconcile_run_stores_decimal_totals_and_net_amount(tmp_path) -> None:
    settings = ingest_sample_data(tmp_path)

    summary = create_reconciliation_run(settings)

    assert isinstance(summary.total_payment_amount, Decimal)
    assert isinstance(summary.total_refund_amount, Decimal)
    assert isinstance(summary.net_amount, Decimal)
    assert summary.total_payment_amount == Decimal("420.25")
    assert summary.total_refund_amount == Decimal("25.00")
    assert summary.net_amount == Decimal("395.25")
    assert summary.summary_json["net_amount"] == "395.25"


def test_reconcile_run_on_empty_database_does_not_crash(tmp_path) -> None:
    settings = make_settings(tmp_path)
    initialize_database(settings)

    summary = create_reconciliation_run(settings)

    assert summary.status == "completed"
    assert summary.payment_count == 0
    assert summary.refund_count == 0
    assert summary.webhook_event_count == 0
    assert summary.total_payment_amount == Decimal("0.00")
    assert summary.total_refund_amount == Decimal("0.00")
    assert summary.net_amount == Decimal("0.00")
    assert summary.currency is None


def test_reconcile_history_lists_previous_runs(tmp_path) -> None:
    settings = ingest_sample_data(tmp_path)
    first = create_reconciliation_run(settings)
    second = create_reconciliation_run(settings)

    rows = list_reconciliation_runs(settings)

    assert len(rows) == 2
    assert {row.external_id for row in rows} == {
        first.external_id,
        second.external_id,
    }
    assert all(row.status == "completed" for row in rows)
    assert all(row.net_amount == Decimal("395.25") for row in rows)


def test_reconcile_history_handles_no_runs_cleanly(tmp_path) -> None:
    settings = make_settings(tmp_path)
    initialize_database(settings)
    result = runner.invoke(app, ["reconcile", "history"], env=make_env(settings))

    assert result.exit_code == 0
    assert "No reconciliation runs found." in result.output


def test_reconcile_show_displays_run_details(tmp_path) -> None:
    settings = ingest_sample_data(tmp_path)
    summary = create_reconciliation_run(settings)
    result = runner.invoke(
        app,
        ["reconcile", "show", summary.external_id],
        env=make_env(settings),
    )

    assert result.exit_code == 0
    assert summary.external_id in result.output
    assert "completed" in result.output
    assert "395.25" in result.output
    assert "usd" in result.output


def test_reconcile_show_missing_run_exits_nonzero(tmp_path) -> None:
    settings = make_settings(tmp_path)
    initialize_database(settings)
    result = runner.invoke(
        app,
        ["reconcile", "show", "missing_run_id"],
        env=make_env(settings),
    )

    assert result.exit_code == 1
    assert "Reconciliation run not found" in result.output


def test_get_reconciliation_run_missing_id_raises(tmp_path) -> None:
    settings = make_settings(tmp_path)
    initialize_database(settings)

    with pytest.raises(ReconciliationRunNotFoundError):
        get_reconciliation_run("missing_run_id", settings)


def test_reconcile_run_does_not_mutate_domain_records(tmp_path) -> None:
    settings = ingest_sample_data(tmp_path)
    before = domain_counts(settings)

    create_reconciliation_run(settings)
    list_reconciliation_runs(settings)

    assert domain_counts(settings) == before


def test_reconcile_cli_workflow_works_with_existing_commands(tmp_path) -> None:
    settings = make_settings(tmp_path)
    env = make_env(settings)
    commands = [
        (["--help"], "Solvra"),
        (["status"], "Solvra"),
        (["init-db"], "Database initialized"),
        (["ingest", "samples/payments.json"], "Ingestion summary"),
        (["payments", "list"], "pay_demo_001"),
        (["payments", "show", "pay_demo_001"], "pay_demo_001"),
        (["customers", "list"], "cus_demo_001"),
        (["refunds", "list"], "ref_demo_001"),
        (["events", "ingest", "samples/webhook_events.json"], "Webhook event"),
        (["events", "list"], "evt_demo_001"),
        (["events", "show", "evt_demo_001"], "evt_demo_001"),
        (["events", "replay", "evt_demo_001"], "evt_demo_001"),
        (["events", "replay", "--type", "payment.succeeded"], "evt_demo_002"),
    ]

    for command, expected in commands:
        result = runner.invoke(app, command, env=env)
        assert result.exit_code == 0
        assert expected in result.output

    run = runner.invoke(app, ["reconcile", "run"], env=env)
    assert run.exit_code == 0
    assert "395.25" in run.output
    run_id = run_id_from_output(run.output)

    history = runner.invoke(app, ["reconcile", "history"], env=env)
    assert history.exit_code == 0
    assert run_id in history.output

    show = runner.invoke(app, ["reconcile", "show", run_id], env=env)
    assert show.exit_code == 0
    assert run_id in show.output


def test_future_revenue_and_risk_commands_are_still_absent() -> None:
    root = runner.invoke(app, ["--help"])
    reconcile = runner.invoke(app, ["reconcile", "--help"])

    assert root.exit_code == 0
    assert reconcile.exit_code == 0
    for command in ("revenue", "risk"):
        assert command not in root.output
        assert command not in reconcile.output

    assert runner.invoke(app, ["revenue", "summary"]).exit_code != 0
    assert runner.invoke(app, ["risk", "scan"]).exit_code != 0
