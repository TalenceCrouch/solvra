from decimal import Decimal
from pathlib import Path

from sqlalchemy import func, select
from typer.testing import CliRunner

from solvra.cli import app
from solvra.config import Settings
from solvra.db import create_session_factory, initialize_database
from solvra.events.service import ingest_webhook_events_file
from solvra.ingest.service import ingest_payments_file
from solvra.models import (
    Customer,
    MerchantAccount,
    Payment,
    ReconciliationMismatch,
    ReconciliationRun,
    Refund,
    WebhookEvent,
)
from solvra.reconcile import create_reconciliation_run
from solvra.revenue import get_revenue_ops_summary

PAYMENT_SAMPLE_PATH = Path("samples/payments.json")
WEBHOOK_SAMPLE_PATH = Path("samples/webhook_events.json")
runner = CliRunner()


def make_settings(tmp_path) -> Settings:
    database_path = tmp_path / "solvra-revenue.db"
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


def record_counts(settings: Settings) -> tuple[int, int, int, int, int, int, int]:
    engine = initialize_database(settings)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        return (
            session.scalar(select(func.count(Customer.id))) or 0,
            session.scalar(select(func.count(MerchantAccount.id))) or 0,
            session.scalar(select(func.count(Payment.id))) or 0,
            session.scalar(select(func.count(Refund.id))) or 0,
            session.scalar(select(func.count(WebhookEvent.id))) or 0,
            session.scalar(select(func.count(ReconciliationRun.id))) or 0,
            session.scalar(select(func.count(ReconciliationMismatch.id))) or 0,
        )


def breakdown(rows) -> list[tuple[str, int]]:
    return [(row.label, row.count) for row in rows]


def test_revenue_summary_appears_in_cli_help() -> None:
    root = runner.invoke(app, ["--help"])
    revenue = runner.invoke(app, ["revenue", "--help"])

    assert root.exit_code == 0
    assert revenue.exit_code == 0
    assert "revenue" in root.output
    assert "summary" in revenue.output


def test_revenue_summary_handles_empty_database(tmp_path) -> None:
    settings = make_settings(tmp_path)
    summary = get_revenue_ops_summary(settings)
    result = runner.invoke(app, ["revenue", "summary"], env=make_env(settings))

    assert summary.gross_payment_amount == Decimal("0.00")
    assert summary.total_refund_amount == Decimal("0.00")
    assert summary.net_amount == Decimal("0.00")
    assert summary.currency is None
    assert summary.payment_count == 0
    assert summary.refund_count == 0
    assert summary.latest_reconciliation_run_id is None
    assert result.exit_code == 0
    assert "No payment data found yet." in result.output


def test_revenue_summary_reports_sample_data_totals_and_counts(tmp_path) -> None:
    settings = ingest_sample_data(tmp_path)

    summary = get_revenue_ops_summary(settings)

    assert summary.gross_payment_amount == Decimal("420.25")
    assert summary.total_refund_amount == Decimal("25.00")
    assert summary.net_amount == Decimal("395.25")
    assert summary.currency == "usd"
    assert summary.customer_count == 2
    assert summary.merchant_account_count == 1
    assert summary.payment_count == 3
    assert summary.refund_count == 1
    assert summary.webhook_event_count == 4
    assert summary.reconciliation_run_count == 0
    assert summary.reconciliation_mismatch_count == 0
    assert breakdown(summary.payment_statuses) == [("pending", 1), ("succeeded", 2)]
    assert breakdown(summary.refund_statuses) == [("succeeded", 1)]
    assert breakdown(summary.webhook_event_types) == [
        ("payment.created", 1),
        ("payment.succeeded", 1),
        ("refund.created", 1),
        ("refund.succeeded", 1),
    ]


def test_revenue_summary_includes_latest_reconciliation_and_mismatch_count(
    tmp_path,
) -> None:
    settings = ingest_sample_data(tmp_path)
    run = create_reconciliation_run(settings)
    result = runner.invoke(app, ["revenue", "summary"], env=make_env(settings))

    summary = get_revenue_ops_summary(settings)

    assert summary.reconciliation_run_count == 1
    assert summary.reconciliation_mismatch_count == 1
    assert summary.latest_reconciliation_run_id == run.external_id
    assert summary.latest_reconciliation_status == "completed"
    assert summary.latest_reconciliation_mismatch_count == 1
    assert summary.latest_reconciliation_completed_at is not None
    assert result.exit_code == 0
    assert run.external_id in result.output
    assert "latest mismatch count" in result.output
    assert "succeeded" in result.output


def test_revenue_summary_does_not_mutate_local_records(tmp_path) -> None:
    settings = ingest_sample_data(tmp_path)
    create_reconciliation_run(settings)
    before = record_counts(settings)

    get_revenue_ops_summary(settings)
    result = runner.invoke(app, ["revenue", "summary"], env=make_env(settings))

    assert result.exit_code == 0
    assert record_counts(settings) == before
