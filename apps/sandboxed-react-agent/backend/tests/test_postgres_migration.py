import sys
import types

from app.persistence.schema import init_schema
from app.session_store import SessionStore


class _FakeCursor:
    def __init__(self, connection: "_FakeConnection") -> None:
        self._connection = connection
        self._rows: list[tuple[str, ...]] = []

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def execute(self, query: str, params: tuple[object, ...] = ()) -> None:
        normalized = " ".join(query.split())
        self._connection.queries.append((normalized, params))
        if "information_schema.columns" in normalized and "table_name = 'sessions'" in normalized:
            self._rows = [("user_id",), ("sandbox_policy_json",)]
            return
        if "information_schema.columns" in normalized and "table_name = 'user_configs'" in normalized:
            self._rows = [("config_json",)]
            return
        if "information_schema.columns" in normalized and "table_name = 'user_workspaces'" in normalized:
            self._rows = [("status_reason",)]
            return
        if "information_schema.columns" in normalized and "table_name = 'workspace_jobs'" in normalized:
            self._rows = [("not_before_at",)]
            return
        self._rows = []

    def fetchall(self) -> list[tuple[str, ...]]:
        return list(self._rows)


class _FakeConnection:
    def __init__(self) -> None:
        self.queries: list[tuple[str, tuple[object, ...]]] = []

    def __enter__(self) -> "_FakeConnection":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self)


def test_init_schema_supports_postgres_cursor_api() -> None:
    connection = _FakeConnection()
    init_schema(lambda: connection)
    assert any(
        "CREATE TABLE IF NOT EXISTS users" in query for query, _ in connection.queries
    )
    assert any("information_schema.columns" in query for query, _ in connection.queries)


def test_connect_postgres_keeps_transactional_mode(monkeypatch) -> None:
    seen: list[str] = []

    class _PsycopgConnection:
        def __init__(self) -> None:
            self.autocommit = False

    def _connect(dsn: str) -> _PsycopgConnection:
        seen.append(dsn)
        return _PsycopgConnection()

    monkeypatch.setitem(sys.modules, "psycopg2", types.SimpleNamespace(connect=_connect))

    store = SessionStore.__new__(SessionStore)
    store.pg_dsn = "host=test-db port=5432 dbname=sandboxed_agent user=postgres password=secret"
    connection = store._connect_postgres()

    assert seen == [store.pg_dsn]
    assert connection.autocommit is False
