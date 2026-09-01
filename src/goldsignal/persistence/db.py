"""Postgres connection helper (Neon-compatible — any standard Postgres works)."""

from __future__ import annotations

import psycopg

from goldsignal.persistence.schema import SCHEMA_SQL


def connect(database_url: str) -> psycopg.Connection:
    if not database_url:
        raise ValueError("database_url must be configured (GOLDSIGNAL_DATABASE_URL)")
    return psycopg.connect(database_url)


def ensure_schema(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute(SCHEMA_SQL)
    conn.commit()
