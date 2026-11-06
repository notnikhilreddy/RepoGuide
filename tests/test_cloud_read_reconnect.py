from unittest.mock import MagicMock

import psycopg
import pytest

from repoguide import cloud_reads


@pytest.mark.parametrize("error", [psycopg.OperationalError, psycopg.InterfaceError])
def test_idle_connection_recovers_before_application_queries(monkeypatch, error):
    stale, healthy = MagicMock(), MagicMock()
    stale.closed = healthy.closed = False
    stale.execute.side_effect = error("connection closed by server")
    monkeypatch.setattr(cloud_reads, "_connection", stale)
    monkeypatch.setenv("READ_DATABASE_URL", "postgresql://fixture@localhost/test")
    connect = MagicMock(return_value=healthy)
    monkeypatch.setattr(psycopg, "connect", connect)
    with cloud_reads.database() as db:
        assert db is healthy
        db.execute("SELECT fixture")
    stale.close.assert_called_once()
    connect.assert_called_once()
    assert healthy.execute.call_args_list[0].args[0] == "SET TRANSACTION READ ONLY"


def test_application_sql_is_never_replayed(monkeypatch):
    connection = MagicMock()
    connection.closed = False
    monkeypatch.setattr(cloud_reads, "_connection", connection)
    connect = MagicMock()
    monkeypatch.setattr(psycopg, "connect", connect)
    attempts = []
    with pytest.raises(psycopg.OperationalError):
        with cloud_reads.database():
            attempts.append("executed")
            raise psycopg.OperationalError("failed after application code began")
    assert attempts == ["executed"]
    connect.assert_not_called()


def test_unavailable_database_has_finite_connection_attempts(monkeypatch):
    monkeypatch.setattr(cloud_reads, "_connection", None)
    monkeypatch.setenv("READ_DATABASE_URL", "postgresql://fixture@localhost/test")
    connect = MagicMock(side_effect=psycopg.OperationalError("unavailable"))
    monkeypatch.setattr(psycopg, "connect", connect)
    with pytest.raises(psycopg.OperationalError):
        with cloud_reads.database():
            pytest.fail("Application must not execute without a connection")
    assert connect.call_count == 2
