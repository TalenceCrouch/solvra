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
from solvra.risk import scan_local_risks

PAYMENT_SAMPLE_PATH = Path("samples/payments.json")
WEBHOOK_SAMPLE_PATH = Path("samples/webhook_events.json")
runner = CliRunner()


def make_settings(tmp_path) -> Settings:
    database_path = tmp_path / "solvra-risk.db"
    return Settings(
        environment="test",
        database_url=f"sqlite:///{database_path.as_posix()}",
    )


def make_env(settings: Settings) -> dict[str, str]:
    return {"SOLVRA_DATABASE_URL": settings.database_url}


def ingest_payment_data(tmp_path) -> Settings:
    settings = make_settings(tmp_path)
    ingest_payments_file(PAYMENT_SAMPLE_PATH, settings)
    return settings


def ingest_sample_data(tmp_path) -> Settings:
    settings = ingest_payment_data(tmp_path)
    ingest_webhook_events_file(WEBHOOK_SAMPLE_PATH, settings)
    return settings


def add_webhook_event(
    settings: Settings,
    external_id: str,
    event_type: str,
    payload: dict,
) -> None:
    engine = initialize_database(settings)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        session.add(
            WebhookEvent(
                external_id=external_id,
                event_type=event_type,
                payload=payload,
            ),
        )
        session.commit()


def add_failed_payment(settings: Settings) -> None:
    engine = initialize_database(settings)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        customer = session.scalar(select(Customer).limit(1))
        account = session.scalar(select(MerchantAccount).limit(1))
        assert customer is not None
        assert account is not None
        session.add(
            Payment(
                external_id="pay_failed_001",
                customer_id=customer.id,
                merchant_account_id=account.id,
                amount=Decimal("10.00"),
                currency="usd",
                status="failed",
            ),
        )
        session.commit()


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


def test_risk_scan_appears_in_cli_help() -> None:
    root = runner.invoke(app, ["--help"])
    risk = runner.invoke(app, ["risk", "--help"])

    assert root.exit_code == 0
    assert risk.exit_code == 0
    assert "risk" in root.output
    assert "scan" in risk.output


def test_risk_scan_handles_empty_database(tmp_path) -> None:
    settings = make_settings(tmp_path)
    scan = scan_local_risks(settings)
    result = runner.invoke(app, ["risk", "scan"], env=make_env(settings))

    assert scan.risk_level == "low"
    assert scan.payment_count == 0
    assert scan.customer_count == 0
    assert scan.reconciliation_run_count == 0
    assert result.exit_code == 0
    assert "No payments found" in result.output
    assert "risk level" in result.output


def test_risk_scan_finds_missing_webhooks_after_payment_ingestion(tmp_path) -> None:
    settings = ingest_payment_data(tmp_path)

    scan = scan_local_risks(settings)

    assert scan.risk_level == "medium"
    assert scan.payment_count == 3
    assert scan.webhook_event_count == 0
    assert any("no webhook events" in finding.message for finding in scan.findings)


def test_risk_scan_finds_missing_reconciliation_after_webhook_ingestion(
    tmp_path,
) -> None:
    settings = ingest_sample_data(tmp_path)

    scan = scan_local_risks(settings)

    assert scan.risk_level == "medium"
    assert scan.webhook_event_count == 4
    assert scan.reconciliation_run_count == 0
    assert any("no reconciliation run" in finding.message for finding in scan.findings)


def test_risk_scan_reports_mismatch_counts_and_higher_risk_level(tmp_path) -> None:
    settings = ingest_sample_data(tmp_path)
    create_reconciliation_run(settings)
    result = runner.invoke(app, ["risk", "scan"], env=make_env(settings))

    scan = scan_local_risks(settings)

    assert scan.risk_level == "medium"
    assert scan.reconciliation_mismatch_count == 1
    assert any(
        finding.related_entity == "payment:pay_demo_003" for finding in scan.findings
    )
    assert result.exit_code == 0
    assert "reconciliation mismatches" in result.output
    assert "pay_demo_003" in result.output


def test_risk_scan_reports_low_no_risk_after_clean_reconciliation(tmp_path) -> None:
    settings = ingest_sample_data(tmp_path)
    add_webhook_event(
        settings,
        external_id="evt_demo_005",
        event_type="payment.succeeded",
        payload={"payment_external_id": "pay_demo_003"},
    )
    create_reconciliation_run(settings)
    result = runner.invoke(app, ["risk", "scan"], env=make_env(settings))

    scan = scan_local_risks(settings)

    assert scan.risk_level == "low"
    assert scan.findings == []
    assert result.exit_code == 0
    assert "No local risk signals found." in result.output


def test_risk_scan_reports_high_risk_for_failed_payments(tmp_path) -> None:
    settings = ingest_sample_data(tmp_path)
    add_failed_payment(settings)

    scan = scan_local_risks(settings)

    assert scan.risk_level == "high"
    assert any(finding.category == "payments" for finding in scan.findings)


def test_risk_scan_does_not_mutate_local_records(tmp_path) -> None:
    settings = ingest_sample_data(tmp_path)
    create_reconciliation_run(settings)
    before = record_counts(settings)

    scan_local_risks(settings)
    result = runner.invoke(app, ["risk", "scan"], env=make_env(settings))

    assert result.exit_code == 0
    assert record_counts(settings) == before
