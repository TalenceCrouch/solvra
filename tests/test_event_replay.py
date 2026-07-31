from pathlib import Path

import pytest
from sqlalchemy import func, select
from typer.testing import CliRunner

from solvra.cli import app
from solvra.config import Settings
from solvra.db import create_session_factory, initialize_database
from solvra.events import EventReplayError
from solvra.events.replay import (
    replay_webhook_event_by_id,
    replay_webhook_events_by_type,
)
from solvra.events.service import ingest_webhook_events_file
from solvra.ingest.service import ingest_payments_file
from solvra.models import Customer, Payment, Refund, WebhookEvent

PAYMENT_SAMPLE_PATH = Path("samples/payments.json")
WEBHOOK_SAMPLE_PATH = Path("samples/webhook_events.json")
runner = CliRunner()


def make_settings(tmp_path) -> Settings:
    database_path = tmp_path / "solvra-replay.db"
    return Settings(
        environment="test",
        database_url=f"sqlite:///{database_path.as_posix()}",
    )


def make_env(settings: Settings) -> dict[str, str]:
    return {"SOLVRA_DATABASE_URL": settings.database_url}


def ingest_sample_events(tmp_path) -> Settings:
    settings = make_settings(tmp_path)
    ingest_webhook_events_file(WEBHOOK_SAMPLE_PATH, settings)
    return settings


def domain_counts(settings: Settings) -> tuple[int, int, int, int]:
    engine = initialize_database(settings)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        return (
            session.scalar(select(func.count(Customer.id))) or 0,
            session.scalar(select(func.count(Payment.id))) or 0,
            session.scalar(select(func.count(Refund.id))) or 0,
            session.scalar(select(func.count(WebhookEvent.id))) or 0,
        )


def test_replay_command_appears_in_cli_help() -> None:
    events = runner.invoke(app, ["events", "--help"])
    replay = runner.invoke(app, ["events", "replay", "--help"])

    assert events.exit_code == 0
    assert replay.exit_code == 0
    assert "replay" in events.output
    assert "--type" in replay.output


def test_replay_by_external_id_works_after_ingesting_sample_events(tmp_path) -> None:
    settings = ingest_sample_events(tmp_path)

    result = replay_webhook_event_by_id("evt_demo_001", settings)

    assert result.external_id == "evt_demo_001"
    assert result.event_type == "payment.created"
    assert result.handler_name == "payment.created"
    assert result.status == "processed"
    assert "pay_demo_001" in result.message


def test_replay_by_event_type_works_after_ingesting_sample_events(tmp_path) -> None:
    settings = ingest_sample_events(tmp_path)

    summary = replay_webhook_events_by_type("payment.succeeded", settings)

    assert summary.processed == 1
    assert summary.skipped == 0
    assert summary.failed == 0
    assert [result.external_id for result in summary.results] == ["evt_demo_002"]
    assert summary.results[0].event_type == "payment.succeeded"


def test_replay_by_external_id_cli_displays_replay_result(tmp_path) -> None:
    settings = ingest_sample_events(tmp_path)
    result = runner.invoke(
        app,
        ["events", "replay", "evt_demo_001"],
        env=make_env(settings),
    )

    assert result.exit_code == 0
    assert "evt_demo_001" in result.output
    assert "payment.created" in result.output
    assert "processed" in result.output
    assert "pay_demo_001" in result.output


def test_replay_by_type_cli_displays_matching_events(tmp_path) -> None:
    settings = ingest_sample_events(tmp_path)
    result = runner.invoke(
        app,
        ["events", "replay", "--type", "payment.succeeded"],
        env=make_env(settings),
    )

    assert result.exit_code == 0
    assert "evt_demo_002" in result.output
    assert "payment.succeeded" in result.output
    assert "processed" in result.output


def test_missing_event_id_exits_nonzero(tmp_path) -> None:
    settings = make_settings(tmp_path)
    initialize_database(settings)
    result = runner.invoke(
        app,
        ["events", "replay", "missing_event_id"],
        env=make_env(settings),
    )

    assert result.exit_code == 1
    assert "Webhook event not found" in result.output


def test_unsupported_event_type_exits_nonzero(tmp_path) -> None:
    settings = make_settings(tmp_path)
    initialize_database(settings)
    result = runner.invoke(
        app,
        ["events", "replay", "--type", "payment.settled"],
        env=make_env(settings),
    )

    assert result.exit_code == 1
    assert "Unsupported webhook event type" in result.output


def test_stored_unsupported_event_type_fails_validation(tmp_path) -> None:
    settings = make_settings(tmp_path)
    engine = initialize_database(settings)
    session_factory = create_session_factory(engine)
    with session_factory() as session:
        session.add(
            WebhookEvent(
                external_id="evt_unsupported",
                event_type="payment.settled",
                payload={"payment_external_id": "pay_demo_001"},
            ),
        )
        session.commit()

    with pytest.raises(EventReplayError, match="Unsupported webhook event type"):
        replay_webhook_event_by_id("evt_unsupported", settings)


def test_replay_by_type_handles_empty_database_without_crashing(tmp_path) -> None:
    settings = make_settings(tmp_path)
    initialize_database(settings)
    result = runner.invoke(
        app,
        ["events", "replay", "--type", "payment.succeeded"],
        env=make_env(settings),
    )

    assert result.exit_code == 0
    assert "No webhook events found for type payment.succeeded." in result.output


def test_replay_does_not_create_duplicate_domain_records(tmp_path) -> None:
    settings = make_settings(tmp_path)
    ingest_payments_file(PAYMENT_SAMPLE_PATH, settings)
    ingest_webhook_events_file(WEBHOOK_SAMPLE_PATH, settings)
    before = domain_counts(settings)

    result = runner.invoke(
        app,
        ["events", "replay", "--type", "payment.succeeded"],
        env=make_env(settings),
    )

    assert result.exit_code == 0
    assert domain_counts(settings) == before


def test_existing_cli_workflow_still_works(tmp_path) -> None:
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


def test_future_workflow_commands_are_still_absent() -> None:
    root = runner.invoke(app, ["--help"])
    events = runner.invoke(app, ["events", "--help"])

    assert root.exit_code == 0
    assert events.exit_code == 0
    for command in ("reconcile", "revenue", "risk"):
        assert command not in root.output
        assert command not in events.output

    assert runner.invoke(app, ["reconcile", "run"]).exit_code != 0
    assert runner.invoke(app, ["revenue", "summary"]).exit_code != 0
    assert runner.invoke(app, ["risk", "scan"]).exit_code != 0
