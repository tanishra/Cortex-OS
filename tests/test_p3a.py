from sqlalchemy import inspect, text

from cortex.config import settings
from cortex.models import TaskRequest
from cortex.store import db


def test_engine_url_normalization():
    assert db._engine_url() == settings.database_url
    orig = settings.database_url
    try:
        settings.database_url = "postgresql://u:p@h:5432/db"
        assert db._engine_url() == "postgresql+psycopg://u:p@h:5432/db"
    finally:
        settings.database_url = orig


def test_init_db_creates_schema():
    """init_db → alembic upgrade → all tables + version row exist."""
    db.init_db()
    tables = set(inspect(db._ENGINE).get_table_names())
    assert {
        "taskrow",
        "sessionrow",
        "credentialrow",
        "approvalrow",
        "apikeyrow",
        "alembic_version",
    } <= tables


def test_legacy_db_stamped_not_wiped():
    """Drop alembic_version (simulate pre-alembic DB) → init_db stamps, keeps data."""
    db.init_db()
    row, _ = db.create_task(TaskRequest(task="legacy task"))
    with db._ENGINE.begin() as conn:
        conn.execute(text("DROP TABLE alembic_version"))

    db.init_db()
    assert "alembic_version" in inspect(db._ENGINE).get_table_names()
    assert db.get_task(row.id).task == "legacy task"
