from decimal import Decimal
from pathlib import Path

from typer.testing import CliRunner

from solvra.cli import app
from solvra.config import Settings
from solvra.db import create_session_factory, initialize_database
from solvra.ingest.service import ingest_payments_file
from solvra.models import Customer, Payment, Refund
from solvra.queries import list_customers, list_payments, list_refunds, payment_detail

runner = CliRunner()


def make_settings(tmp_path) -> Settings:
    database_path = tmp_path / "solvra-query.db"
    return Settings(
        environment="test",
        database_url=f"sqlite:///{database_path.as_posix()}",
    )


def make_env(settings: Settings) -> dict[str, str]:
    return {"SOLVRA_DATABASE_URL": settings.database_url}


def ingest_sample_data(tmp_path) -> Settings:
    settings = make_settings(tmp_path)
    ingest_payments_file(Path("samples/payments.json"), settings)
    return settings


def test_query_services_return_ingested_data(tmp_path) -> None:
    settings = ingest_sample_data(tmp_path)

    payments = list_payments(settings)
    customers = list_customers(settings)
    refunds = list_refunds(settings)
    detail = payment_detail("pay_demo_001", settings)

    assert [payment.external_id for payment in payments] == [
        "pay_demo_001",
        "pay_demo_002",
        "pay_demo_003",
    ]
    assert [customer.external_id for customer in customers] == [
        "cus_demo_001",
        "cus_demo_002",
    ]
    assert [refund.external_id for refund in refunds] == ["ref_demo_001"]
    assert detail is not None
    assert detail.external_id == "pay_demo_001"
    assert detail.amount == Decimal("125.00")
    assert detail.customer_external_id == "cus_demo_001"
    assert detail.merchant_account_external_id == "acct_demo_001"
    assert detail.refunds[0].external_id == "ref_demo_001"


def test_query_services_do_not_mutate_data(tmp_path) -> None:
    settings = ingest_sample_data(tmp_path)
    engine = initialize_database(settings)
    session_factory = create_session_factory(engine)

    list_payments(settings)
    payment_detail("pay_demo_001", settings)
    list_customers(settings)
    list_refunds(settings)

    with session_factory() as session:
        assert session.query(Customer).count() == 2
        assert session.query(Payment).count() == 3
        assert session.query(Refund).count() == 1


def test_payment_list_cli_displays_sample_payment_ids(tmp_path) -> None:
    settings = ingest_sample_data(tmp_path)
    result = runner.invoke(
        app,
        ["payments", "list"],
        env=make_env(settings),
    )

    assert result.exit_code == 0
    assert "pay_demo_001" in result.output
    assert "pay_demo_002" in result.output
    assert "pay_demo_003" in result.output


def test_payment_show_cli_displays_expected_details(tmp_path) -> None:
    settings = ingest_sample_data(tmp_path)
    result = runner.invoke(
        app,
        ["payments", "show", "pay_demo_001"],
        env=make_env(settings),
    )

    assert result.exit_code == 0
    assert "pay_demo_001" in result.output
    assert "125.00" in result.output
    assert "cus_demo_001" in result.output
    assert "acct_demo_001" in result.output
    assert "ref_demo_001" in result.output


def test_payment_show_missing_id_exits_nonzero(tmp_path) -> None:
    settings = make_settings(tmp_path)
    initialize_database(settings)
    result = runner.invoke(
        app,
        ["payments", "show", "missing_payment_id"],
        env=make_env(settings),
    )

    assert result.exit_code == 1
    assert "Payment not found" in result.output


def test_customer_list_cli_works_after_ingest(tmp_path) -> None:
    settings = ingest_sample_data(tmp_path)
    result = runner.invoke(app, ["customers", "list"], env=make_env(settings))

    assert result.exit_code == 0
    assert "cus_demo_001" in result.output
    assert "ada@example.test" in result.output


def test_refund_list_cli_works_after_ingest(tmp_path) -> None:
    settings = ingest_sample_data(tmp_path)
    result = runner.invoke(app, ["refunds", "list"], env=make_env(settings))

    assert result.exit_code == 0
    assert "ref_demo_001" in result.output
    assert "pay_demo_001" in result.output


def test_empty_database_list_commands_show_useful_messages(tmp_path) -> None:
    settings = make_settings(tmp_path)
    initialize_database(settings)

    payments = runner.invoke(app, ["payments", "list"], env=make_env(settings))
    customers = runner.invoke(app, ["customers", "list"], env=make_env(settings))
    refunds = runner.invoke(app, ["refunds", "list"], env=make_env(settings))

    assert payments.exit_code == 0
    assert "No payments found." in payments.output
    assert customers.exit_code == 0
    assert "No customers found." in customers.output
    assert refunds.exit_code == 0
    assert "No refunds found." in refunds.output


def test_future_workflow_commands_still_absent() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    for command in ("reconcile", "revenue", "risk"):
        assert command not in result.output
