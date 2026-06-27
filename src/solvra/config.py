from dataclasses import dataclass
from os import getenv

DEFAULT_ENVIRONMENT = "dev"


@dataclass(frozen=True)
class Settings:
    environment: str = DEFAULT_ENVIRONMENT
    database_url: str | None = None

    @property
    def database_url_configured(self) -> bool:
        return bool(self.database_url)


def load_settings() -> Settings:
    environment = getenv("SOLVRA_ENVIRONMENT", DEFAULT_ENVIRONMENT).strip()
    database_url = getenv("DATABASE_URL", "").strip()

    return Settings(
        environment=environment or DEFAULT_ENVIRONMENT,
        database_url=database_url or None,
    )
