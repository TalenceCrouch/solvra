import json
from copy import deepcopy
from pathlib import Path

import pytest
from sqlalchemy import func, select
from typer.testing import CliRunner

from solvra.cli import app
from solvra.config import Settings
from solvra.db import create_session_factory, initialize_database
from solvra.events import EventValidationError
from solvra.events.schemas import EventDataBatch
from solvra.events.service import (
    ingest_webhook_events_file,
    list_webhook_events,
    load_webhook_event_data,
    webhook_event_detail,
)
from solvra.models import WebhookEvent

SAMPLE_PATH = Path("samples/webhook_events.json")
runner = CliRunner()


def make_settings(tmp_path) -> Settings:
    database_path = tmp_path / "solvra-events.db"
    return Settings(
        environment="test",
        database_url=f"sqlite:///{database_path.as_posix()}",
    )


def make_env(settings: Settings) -> dict[str, str]:
    return {"SOLVRA_DATABASE_URL": settings.database_url}


def load_sample_mapping() -> dict:
    return json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))


def test_sample_webhook_file_exists_and_is_valid_json() -> None:
    batch = load_webhook_event_data(SAMPLE_PATH)

    assert len(batch.events) >= 4
    assert batch.events[0].external_id == "evt_demo_001"


def test_webhook_events_are_persisted_to_temporary_database(tmp_path) -> None:
    settings = make_settings(tmp_path)
    summary = ingest_webhook_events_file(SAMPLE_PATH, settings)
    engine = initialize_database(settings)
    session_factory = create_session_factory(engine)

    with session_factory() as session:
        count = session.scalar(select(func.count(WebhookEvent.id)))
        event = session.scalar(
            select(WebhookEvent).where(WebhookEvent.external_id == "evt_demo_001"),
        )

        assert summary.inserted == 4
        assert summary.skipped == 0
        assert count == 4
        assert event is not None
        assert event.event_type == "payment.created"
        assert event.payload["payment_external_id"] == "pay_demo_001"
        assert event.payload["source"] == "demo_gateway"


def test_webhook_event_ingestion_skips_duplicates(tmp_path) -> None:
    settings = make_settings(tmp_path)

    first = ingest_webhook_events_file(SAMPLE_PATH, settings)
    second = ingest_webhook_events_file(SAMPLE_PATH, settings)

    assert first.inserted == 4
    assert first.skipped == 0
    assert second.inserted == 0
    assert second.skipped == 4


def test_invalid_event_type_fails_validation() -> None:
    data = load_sample_mapping()
    data["events"][0]["event_type"] = "payment.settled"

    with pytest.raises(EventValidationError, match="event_type"):
        EventDataBatch.from_mapping(data)


def test_missing_payload_fails_validation() -> None:
    data = load_sample_mapping()
    del data["events"][0]["payload"]

    with pytest.raises(EventValidationError, match="payload"):
        EventDataBatch.from_mapping(data)


def test_duplicate_event_external_id_fails_validation() -> None:
    data = load_sample_mapping()
    data["events"].append(deepcopy(data["events"][0]))

    with pytest.raises(EventValidationError, match="duplicate event"):
        EventDataBatch.from_mapping(data)


def test_malformed_top_level_json_shape_fails_validation() -> None:
    with pytest.raises(EventValidationError, match="events"):
        EventDataBatch.from_mapping({"items": []})


def test_empty_events_list_fails_validation() -> None:
    with pytest.raises(EventValidationError, match="must not be empty"):
        EventDataBatch.from_mapping({"events": []})


def test_events_list_works_after_ingestion(tmp_path) -> None:
    settings = make_settings(tmp_path)
    ingest_webhook_events_file(SAMPLE_PATH, settings)

    rows = list_webhook_events(settings)

    assert [event.external_id for event in rows] == [
        "evt_demo_001",
        "evt_demo_002",
        "evt_demo_003",
        "evt_demo_004",
    ]
    assert rows[0].source == "demo_gateway"
    assert rows[0].processed == "no"


def test_events_detail_returns_expected_payload(tmp_path) -> None:
    settings = make_settings(tmp_path)
    ingest_webhook_events_file(SAMPLE_PATH, settings)

    event = webhook_event_detail("evt_demo_001", settings)

    assert event is not None
    assert event.external_id == "evt_demo_001"
    assert event.event_type == "payment.created"
    assert event.source == "demo_gateway"
    assert event.payload["payment_external_id"] == "pay_demo_001"
    assert "source" not in event.payload


def test_events_ingest_cli_exits_successfully(tmp_path) -> None:
    settings = make_settings(tmp_path)
    result = runner.invoke(
        app,
        ["events", "ingest", "samples/webhook_events.json"],
        env=make_env(settings),
    )

    assert result.exit_code == 0
    assert "Webhook event ingestion" in result.output


def test_events_list_cli_shows_known_sample_event_ids(tmp_path) -> None:
    settings = make_settings(tmp_path)
    ingest_webhook_events_file(SAMPLE_PATH, settings)
    result = runner.invoke(app, ["events", "list"], env=make_env(settings))

    assert result.exit_code == 0
    assert "evt_demo_001" in result.output
    assert "evt_demo_004" in result.output


def test_events_list_empty_database_does_not_crash(tmp_path) -> None:
    settings = make_settings(tmp_path)
    initialize_database(settings)
    result = runner.invoke(app, ["events", "list"], env=make_env(settings))

    assert result.exit_code == 0
    assert "No webhook events found." in result.output


def test_events_show_cli_displays_expected_details(tmp_path) -> None:
    settings = make_settings(tmp_path)
    ingest_webhook_events_file(SAMPLE_PATH, settings)
    result = runner.invoke(
        app,
        ["events", "show", "evt_demo_001"],
        env=make_env(settings),
    )

    assert result.exit_code == 0
    assert "evt_demo_001" in result.output
    assert "payment.created" in result.output
    assert "demo_gateway" in result.output
    assert "pay_demo_001" in result.output


def test_events_show_missing_id_exits_nonzero(tmp_path) -> None:
    settings = make_settings(tmp_path)
    initialize_database(settings)
    result = runner.invoke(
        app,
        ["events", "show", "missing_event_id"],
        env=make_env(settings),
    )

    assert result.exit_code == 1
    assert "Webhook event not found" in result.output


def test_future_risk_event_workflow_command_is_still_absent() -> None:
    root = runner.invoke(app, ["--help"])
    events = runner.invoke(app, ["events", "--help"])

    assert root.exit_code == 0
    assert events.exit_code == 0
    assert "risk" not in root.output
    assert "risk" not in events.output
