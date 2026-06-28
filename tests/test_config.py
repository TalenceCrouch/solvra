from solvra.config import DEFAULT_DATABASE_URL, DEFAULT_ENV, load_settings


def test_default_config_values(monkeypatch) -> None:
    monkeypatch.delenv("SOLVRA_ENV", raising=False)
    monkeypatch.delenv("SOLVRA_DATABASE_URL", raising=False)

    settings = load_settings()

    assert settings.environment == DEFAULT_ENV
    assert settings.database_url == DEFAULT_DATABASE_URL
    assert settings.database_url_configured is True
    assert settings.database_backend == "sqlite"


def test_environment_override_behavior(monkeypatch) -> None:
    monkeypatch.setenv("SOLVRA_ENV", "test")
    monkeypatch.setenv("SOLVRA_DATABASE_URL", "sqlite:///custom.db")

    settings = load_settings()

    assert settings.environment == "test"
    assert settings.database_url == "sqlite:///custom.db"
