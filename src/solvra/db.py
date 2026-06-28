from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from solvra.config import Settings, load_settings


class Base(DeclarativeBase):
    pass


def create_database_engine(database_url: str) -> Engine:
    return create_engine(database_url, future=True)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def sqlite_database_path(database_url: str) -> Path | None:
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite":
        return None
    if not url.database or url.database == ":memory:":
        return None
    return Path(url.database)


def initialize_database(settings: Settings | None = None) -> Engine:
    active_settings = settings or load_settings()
    database_path = sqlite_database_path(active_settings.database_url)
    if database_path is not None and database_path.parent != Path("."):
        database_path.parent.mkdir(parents=True, exist_ok=True)

    engine = create_database_engine(active_settings.database_url)
    Base.metadata.create_all(engine)
    return engine
