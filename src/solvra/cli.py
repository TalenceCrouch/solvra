import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from solvra import __version__
from solvra.config import load_settings
from solvra.db import initialize_database

APP_NAME = "Solvra"
APP_SUBTITLE = "Echelon Proxy"

app = typer.Typer(help="Solvra payments operations CLI.")
console = Console()


@app.callback()
def main() -> None:
    """Solvra payments operations CLI."""


@app.command()
def status() -> None:
    """Show current Solvra runtime status."""
    settings = load_settings()

    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold")
    table.add_column()
    table.add_row("app name", APP_NAME)
    table.add_row("subtitle", APP_SUBTITLE)
    table.add_row("environment", settings.environment)
    table.add_row(
        "database URL configured",
        "yes" if settings.database_url_configured else "no",
    )
    table.add_row("database backend", settings.database_backend)
    table.add_row("version", __version__)

    console.print(Panel(table, title=APP_NAME, subtitle=APP_SUBTITLE))


@app.command("init-db")
def init_db() -> None:
    """Initialize the configured database."""
    settings = load_settings()
    initialize_database(settings)

    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold")
    table.add_column()
    table.add_row("environment", settings.environment)
    table.add_row("database backend", settings.database_backend)

    console.print(Panel(table, title="Database initialized"))


if __name__ == "__main__":
    app()
