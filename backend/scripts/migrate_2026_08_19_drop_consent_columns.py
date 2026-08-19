"""One-off migration: drop columns removed by the consent/endpoint_scope
removal (see CLAUDE.md's "No remote-provider consent gate" deviation entry).

Run once against an existing tuneforge.db created before that change:

    uv run python scripts/migrate_2026_08_19_drop_consent_columns.py

Safe to re-run — checks each column exists before dropping it. Back up the
database yourself first; this script does not do it for you.
"""

from __future__ import annotations

import sqlite3

from tuneforge.settings import Settings


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row[1] == column for row in rows)


def migrate(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    try:
        if _has_column(conn, "provider_profiles", "endpoint_scope"):
            conn.execute("ALTER TABLE provider_profiles DROP COLUMN endpoint_scope")
            print("dropped provider_profiles.endpoint_scope")
        else:
            print("provider_profiles.endpoint_scope already absent, skipping")

        if _has_column(conn, "runs", "remote_consent_granted_at"):
            conn.execute("ALTER TABLE runs DROP COLUMN remote_consent_granted_at")
            print("dropped runs.remote_consent_granted_at")
        else:
            print("runs.remote_consent_granted_at already absent, skipping")

        conn.commit()
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()


if __name__ == "__main__":
    settings = Settings()
    db_path = str(settings.data_dir / "tuneforge.db")
    print(f"migrating {db_path}")
    migrate(db_path)
    print("done")
