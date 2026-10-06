from pathlib import Path

from click.testing import CliRunner

from discover.config import project_root
from discover.db import get_engine, migration_status, run_migrations
from discover.cli import cli


def test_migrations_apply_on_fresh_db(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    url = f"sqlite:///{db_path.as_posix()}"
    engine = get_engine(url)
    applied = run_migrations(engine)
    assert "001" in applied
    applied_again = run_migrations(engine)
    assert applied_again == []
    statuses = list(migration_status(engine))
    assert statuses
    assert all(applied for _, _, applied in statuses)


def test_cli_migrate_and_preprocess_dry_run(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "cli.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path.as_posix()}")

    runner = CliRunner()
    result = runner.invoke(cli, ["migrate"])
    assert result.exit_code == 0
    assert "001" in result.output or "up to date" in result.output

    result = runner.invoke(cli, ["run", "--stage", "preprocess", "--dry-run"])
    assert result.exit_code == 0
    assert "pipeline_run_id=" in result.output


def test_project_layout() -> None:
    root = project_root()
    assert (root / "migrations" / "001_initial_schema.sql").is_file()
    assert (root / "src" / "discover" / "cli.py").is_file()
    assert (root / "data" / "raw").is_dir()
