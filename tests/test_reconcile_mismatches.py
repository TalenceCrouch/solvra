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
    WebhookEvent,
)
from solvra.reconcile import (
    create_reconciliation_run,
    list_latest_reconciliation_mismatches,
)

PAYMENT_SAMPLE_PATH = Path("samples/payments.json")
WEBHOOK_SAMPLE_PATH = Path("samples/webhook_events.json")
runner = CliRunner()


def make_settings(tmp_path) -> Settings:
    database_path = tmp_path / "solvra-mismatches.db"
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


def add_status_mismatch_payment(settings: Settings) -> None:
    engine = initialize_database(settings)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        customer = Customer(
            external_id="cus_status_mismatch",
            email="status@example.test",
            name="Status Mismatch",
        )
        account = MerchantAccount(
            external_id="acct_status_mismatch",
            name="Status Account",
            currency="usd",
        )
        session.add_all(
            [
                Payment(
                    external_id="pay_status_mismatch",
                    customer=customer,
                    merchant_account=account,
                    amount=Decimal("19.00"),
                    currency="usd",
                    status="failed",
                    description="Webhook says succeeded",
                ),
                WebhookEvent(
                    external_id="evt_status_mismatch",
                    event_type="payment.succeeded",
                    payload={"payment_external_id": "pay_status_mismatch"},
                ),
            ],
        )
        session.commit()


def mismatch_count(settings: Settings) -> int:
    engine = initialize_database(settings)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        return session.scalar(select(func.count(ReconciliationMismatch.id))) or 0


def test_reconcile_mismatches_command_appears_in_help() -> None:
    result = runner.invoke(app, ["reconcile", "--help"])

    assert result.exit_code == 0
    assert "mismatches" in result.output


def test_sample_data_creates_expected_missing_payment_event_mismatch(tmp_path) -> None:
    settings = ingest_sample_data(tmp_path)

    summary = create_reconciliation_run(settings)

    assert summary.mismatch_count == 1
    assert mismatch_count(settings) == 1
    assert summary.mismatches[0].mismatch_type == "missing_payment_succeeded_event"
    assert summary.mismatches[0].severity == "warning"
    assert summary.mismatches[0].entity_external_id == "pay_demo_003"


def test_no_mismatch_case_stores_zero_mismatches(tmp_path) -> None:
    settings = ingest_sample_data(tmp_path)
    add_webhook_event(
        settings,
        external_id="evt_demo_005",
        event_type="payment.succeeded",
        payload={"payment_external_id": "pay_demo_003"},
    )

    summary = create_reconciliation_run(settings)

    assert summary.mismatch_count == 0
    assert summary.mismatches == []


def test_webhook_referencing_missing_payment_creates_error_mismatch(tmp_path) -> None:
    settings = make_settings(tmp_path)
    initialize_database(settings)
    add_webhook_event(
        settings,
        external_id="evt_missing_payment",
        event_type="payment.succeeded",
        payload={"payment_external_id": "pay_missing"},
    )

    summary = create_reconciliation_run(settings)

    assert summary.mismatch_count == 1
    mismatch = summary.mismatches[0]
    assert mismatch.mismatch_type == "webhook_missing_payment"
    assert mismatch.severity == "error"
    assert mismatch.entity_type == "webhook_event"
    assert mismatch.entity_external_id == "evt_missing_payment"


def test_webhook_referencing_missing_refund_creates_error_mismatch(tmp_path) -> None:
    settings = make_settings(tmp_path)
    initialize_database(settings)
    add_webhook_event(
        settings,
        external_id="evt_missing_refund",
        event_type="refund.succeeded",
        payload={"refund_external_id": "ref_missing"},
    )

    summary = create_reconciliation_run(settings)

    assert summary.mismatch_count == 1
    mismatch = summary.mismatches[0]
    assert mismatch.mismatch_type == "webhook_missing_refund"
    assert mismatch.severity == "error"
    assert mismatch.entity_external_id == "evt_missing_refund"


def test_payment_status_mismatch_creates_warning_mismatch(tmp_path) -> None:
    settings = make_settings(tmp_path)
    initialize_database(settings)
    add_status_mismatch_payment(settings)

    summary = create_reconciliation_run(settings)

    assert summary.mismatch_count == 1
    mismatch = summary.mismatches[0]
    assert mismatch.mismatch_type == "payment_status_mismatch"
    assert mismatch.expected == "succeeded"
    assert mismatch.actual == "failed"


def test_empty_database_reconcile_run_creates_zero_mismatches(tmp_path) -> None:
    settings = make_settings(tmp_path)
    initialize_database(settings)

    summary = create_reconciliation_run(settings)

    assert summary.mismatch_count == 0
    assert summary.mismatches == []


def test_reconcile_mismatches_handles_no_runs_cleanly(tmp_path) -> None:
    settings = make_settings(tmp_path)
    initialize_database(settings)
    result = runner.invoke(app, ["reconcile", "mismatches"], env=make_env(settings))

    assert result.exit_code == 0
    assert "No reconciliation runs found." in result.output


def test_reconcile_mismatches_handles_run_with_no_mismatches(tmp_path) -> None:
    settings = ingest_sample_data(tmp_path)
    add_webhook_event(
        settings,
        external_id="evt_demo_005",
        event_type="payment.succeeded",
        payload={"payment_external_id": "pay_demo_003"},
    )
    create_reconciliation_run(settings)
    result = runner.invoke(app, ["reconcile", "mismatches"], env=make_env(settings))

    assert result.exit_code == 0
    assert "No reconciliation mismatches found." in result.output


def test_reconcile_mismatches_lists_latest_run_mismatches(tmp_path) -> None:
    settings = ingest_sample_data(tmp_path)
    summary = create_reconciliation_run(settings)
    result = runner.invoke(app, ["reconcile", "mismatches"], env=make_env(settings))

    assert result.exit_code == 0
    assert summary.external_id in result.output
    assert "missing_payment_succeeded_event" in result.output
    assert "pay_demo_003" in result.output


def test_latest_mismatch_service_returns_latest_run_only(tmp_path) -> None:
    settings = ingest_sample_data(tmp_path)
    first = create_reconciliation_run(settings)
    add_webhook_event(
        settings,
        external_id="evt_demo_005",
        event_type="payment.succeeded",
        payload={"payment_external_id": "pay_demo_003"},
    )
    second = create_reconciliation_run(settings)

    result = list_latest_reconciliation_mismatches(settings)

    assert first.external_id != second.external_id
    assert result.run_external_id == second.external_id
    assert result.mismatches == []


def test_reconcile_show_includes_mismatch_count_and_details(tmp_path) -> None:
    settings = ingest_sample_data(tmp_path)
    summary = create_reconciliation_run(settings)
    result = runner.invoke(
        app,
        ["reconcile", "show", summary.external_id],
        env=make_env(settings),
    )

    assert result.exit_code == 0
    assert "mismatch count" in result.output
    assert "missing_payment_succeeded_event" in result.output
    assert "pay_demo_003" in result.output
