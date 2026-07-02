import json
from copy import deepcopy
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select

from solvra.config import Settings
from solvra.db import create_session_factory, initialize_database
from solvra.ingest import IngestionValidationError
from solvra.ingest.schemas import PaymentDataBatch
from solvra.ingest.service import ingest_payments_file, load_payment_data
from solvra.models import Customer, MerchantAccount, Payment, Refund

SAMPLE_PATH = Path("samples/payments.json")


def make_settings(tmp_path) -> Settings:
    database_path = tmp_path / "solvra-ingest.db"
    return Settings(
        environment="test",
        database_url=f"sqlite:///{database_path.as_posix()}",
    )


def load_sample_mapping() -> dict:
    return json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))


def write_data(tmp_path, data: dict) -> Path:
    path = tmp_path / "payments.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_sample_file_exists_and_is_valid_json() -> None:
    batch = load_payment_data(SAMPLE_PATH)

    assert len(batch.customers) >= 2
    assert len(batch.merchant_accounts) >= 1
    assert len(batch.payments) >= 3
    assert len(batch.refunds) >= 1


def test_ingest_sample_data_persists_records_and_relationships(tmp_path) -> None:
    settings = make_settings(tmp_path)
    summary = ingest_payments_file(SAMPLE_PATH, settings)
    engine = initialize_database(settings)
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        customer_count = session.scalar(select(func.count(Customer.id)))
        account_count = session.scalar(select(func.count(MerchantAccount.id)))
        payment_count = session.scalar(select(func.count(Payment.id)))
        refund_count = session.scalar(select(func.count(Refund.id)))
        payment = session.scalar(
            select(Payment).where(Payment.external_id == "pay_demo_001"),
        )
        refund = session.scalar(
            select(Refund).where(Refund.external_id == "ref_demo_001"),
        )

        assert summary.customers_inserted == 2
        assert summary.merchant_accounts_inserted == 1
        assert summary.payments_inserted == 3
        assert summary.refunds_inserted == 1
        assert customer_count == 2
        assert account_count == 1
        assert payment_count == 3
        assert refund_count == 1
        assert payment is not None
        assert payment.customer.external_id == "cus_demo_001"
        assert payment.merchant_account.external_id == "acct_demo_001"
        assert payment.amount == Decimal("125.00")
        assert refund is not None
        assert refund.payment.external_id == "pay_demo_001"
        assert refund.amount == Decimal("25.00")


def test_ingestion_skips_duplicates_on_second_run(tmp_path) -> None:
    settings = make_settings(tmp_path)

    first = ingest_payments_file(SAMPLE_PATH, settings)
    second = ingest_payments_file(SAMPLE_PATH, settings)

    assert first.payments_inserted == 3
    assert second.customers_inserted == 0
    assert second.customers_skipped == 2
    assert second.merchant_accounts_inserted == 0
    assert second.merchant_accounts_skipped == 1
    assert second.payments_inserted == 0
    assert second.payments_skipped == 3
    assert second.refunds_inserted == 0
    assert second.refunds_skipped == 1


def test_invalid_payment_status_fails_validation() -> None:
    data = load_sample_mapping()
    data["payments"][0]["status"] = "settled"

    with pytest.raises(IngestionValidationError, match="status"):
        PaymentDataBatch.from_mapping(data)


def test_invalid_refund_status_fails_validation() -> None:
    data = load_sample_mapping()
    data["refunds"][0]["status"] = "settled"

    with pytest.raises(IngestionValidationError, match="status"):
        PaymentDataBatch.from_mapping(data)


def test_invalid_amount_fails_validation() -> None:
    data = load_sample_mapping()
    data["payments"][0]["amount"] = "12.345"

    with pytest.raises(IngestionValidationError, match="amount"):
        PaymentDataBatch.from_mapping(data)


def test_unknown_customer_reference_fails_validation() -> None:
    data = load_sample_mapping()
    data["payments"][0]["customer_external_id"] = "cus_missing"

    with pytest.raises(IngestionValidationError, match="unknown customer"):
        PaymentDataBatch.from_mapping(data)


def test_unknown_merchant_account_reference_fails_validation() -> None:
    data = load_sample_mapping()
    data["payments"][0]["merchant_account_external_id"] = "acct_missing"

    with pytest.raises(IngestionValidationError, match="unknown merchant account"):
        PaymentDataBatch.from_mapping(data)


def test_unknown_payment_reference_for_refund_fails_validation() -> None:
    data = load_sample_mapping()
    data["refunds"][0]["payment_external_id"] = "pay_missing"

    with pytest.raises(IngestionValidationError, match="unknown payment"):
        PaymentDataBatch.from_mapping(data)


def test_duplicate_external_id_in_input_fails_validation() -> None:
    data = load_sample_mapping()
    duplicate = deepcopy(data["payments"][0])
    data["payments"].append(duplicate)

    with pytest.raises(IngestionValidationError, match="duplicate payment"):
        PaymentDataBatch.from_mapping(data)


def test_missing_required_field_fails_validation() -> None:
    data = load_sample_mapping()
    del data["payments"][0]["external_id"]

    with pytest.raises(IngestionValidationError, match="external_id"):
        PaymentDataBatch.from_mapping(data)
