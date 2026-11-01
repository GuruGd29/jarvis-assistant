"""Bring the database up to date: run every file in sql/ in order. Each one only creates what is missing
(CREATE ... IF NOT EXISTS), so it is safe to run after every update and on a new install.

  jarvis-migrate
"""
import psycopg

from . import config


def main() -> None:
    files = sorted((config.SYSTEM_DIR / "sql").glob("*.sql"))
    with psycopg.connect(config.DB_DSN, autocommit=True) as conn:
        for sql in files:
            conn.execute(sql.read_text())
    print(f"Database up to date ({len(files)} schema files).")
