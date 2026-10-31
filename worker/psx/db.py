from __future__ import annotations

import json
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

from .config import DATABASE_URL


def connect(autocommit: bool = False) -> psycopg.Connection:
    return psycopg.connect(DATABASE_URL, row_factory=dict_row, autocommit=autocommit)


@contextmanager
def service():
    """Privileged connection for background jobs and ingestion (bypasses RLS, like Supabase service_role)."""
    with connect() as conn:
        yield conn


@contextmanager
def as_user(user_id: str):
    """Connection scoped to a user: switches to the 'authenticated' role so RLS policies apply."""
    with connect() as conn:
        with conn.transaction():
            conn.execute("select set_config('request.jwt.claims', %s, true)", (json.dumps({"sub": user_id, "role": "authenticated"}),))
            conn.execute("set local role authenticated")
            yield conn
