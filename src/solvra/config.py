from dataclasses import dataclass
from os import getenv

from sqlalchemy.engine import make_url

DEFAULT_ENV = "dev"
DEFAULT_DATABASE_URL = "sqlite:///solvra.db"


@dataclass(frozen=True)
class Settings:
    environment: str = DEFAULT_ENV
    database_url: str = DEFAULT_DATABASE_URL

    @property
    def database_url_configured(self) -> bool:
        return bool(self.database_url)

    @property
    def database_backend(self) -> str:
        return make_url(self.database_url).get_backend_name()


def load_settings() -> Settings:
    environment = getenv("SOLVRA_ENV", DEFAULT_ENV).strip()
    database_url = getenv("SOLVRA_DATABASE_URL", DEFAULT_DATABASE_URL).strip()

    return Settings(
        environment=environment or DEFAULT_ENV,
        database_url=database_url or DEFAULT_DATABASE_URL,
    )
