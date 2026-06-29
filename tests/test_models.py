from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from solvra.config import Settings
from solvra.db import create_session_factory, initialize_database
from solvra.models import (
    Customer,
    LedgerEntry,
    MerchantAccount,
    Payment,
    Refund,
    WebhookEvent,
)


def make_settings(tmp_path) -> Settings:
    database_path = tmp_path / "solvra-models.db"
    return Settings(
        environment="test",
        database_url=f"sqlite:///{database_path.as_posix()}",
    )


def test_core_models_insert_and_relationships_work(tmp_path) -> None:
    engine = initialize_database(make_settings(tmp_path))
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        customer = Customer(
            external_id="cust_001",
            email="customer@example.test",
            name="Example Customer",
        )
        account = MerchantAccount(
            external_id="acct_001",
            name="Primary Merchant",
            currency="usd",
        )
        payment = Payment(
            external_id="pay_001",
            customer=customer,
            merchant_account=account,
            amount=Decimal("42.25"),
            currency="usd",
            status="succeeded",
            description="Test payment",
        )
        refund = Refund(
            external_id="ref_001",
            payment=payment,
            amount=Decimal("10.00"),
            currency="usd",
            reason="requested_by_customer",
            status="succeeded",
        )
        payment_entry = LedgerEntry(
            external_id="ledger_001",
            payment=payment,
            merchant_account=account,
            entry_type="payment",
            amount=Decimal("42.25"),
            currency="usd",
            direction="credit",
        )
        refund_entry = LedgerEntry(
            external_id="ledger_002",
            refund=refund,
            merchant_account=account,
            entry_type="refund",
            amount=Decimal("10.00"),
            currency="usd",
            direction="debit",
        )
        webhook = WebhookEvent(
            external_id="evt_001",
            event_type="payment.succeeded",
            payload={"data": {"object": {"id": "pay_001"}}},
        )

        session.add_all([payment_entry, refund_entry, webhook])
        session.commit()

        loaded_payment = session.scalar(
            select(Payment).where(Payment.external_id == "pay_001"),
        )
        loaded_webhook = session.scalar(
            select(WebhookEvent).where(WebhookEvent.external_id == "evt_001"),
        )

        assert loaded_payment is not None
        assert loaded_payment.customer.external_id == "cust_001"
        assert loaded_payment.merchant_account.external_id == "acct_001"
        assert loaded_payment.refunds[0].external_id == "ref_001"
        assert loaded_payment.ledger_entries[0].external_id == "ledger_001"
        assert loaded_payment.amount == Decimal("42.25")
        assert loaded_payment.refunds[0].amount == Decimal("10.00")
        assert loaded_webhook is not None
        assert loaded_webhook.payload["data"]["object"]["id"] == "pay_001"


def test_unique_external_id_constraints_are_enforced(tmp_path) -> None:
    engine = initialize_database(make_settings(tmp_path))
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        session.add_all(
            [
                Customer(
                    external_id="cust_duplicate",
                    email="one@example.test",
                    name="One",
                ),
                Customer(
                    external_id="cust_duplicate",
                    email="two@example.test",
                    name="Two",
                ),
            ],
        )

        with pytest.raises(IntegrityError):
            session.commit()
