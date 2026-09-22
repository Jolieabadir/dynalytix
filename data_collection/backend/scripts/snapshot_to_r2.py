#!/usr/bin/env python3
"""
Nightly snapshot: dump every table in the public schema to CSV in R2.

Supabase's free tier has no point-in-time recovery, so this is the backup.
One object per table under

    snapshots/YYYY-MM-DD/<table>.csv

Dumps every base table in `public` (discovered from information_schema, so a
new table is picked up without editing this file), header row first, values
rendered by Postgres' own CSV encoder (COPY ... TO STDOUT WITH CSV HEADER),
which keeps JSONB, arrays and timestamps round-trippable.

Usage:
    python scripts/snapshot_to_r2.py              # today's date (UTC)
    python scripts/snapshot_to_r2.py --date 2026-09-22
    python scripts/snapshot_to_r2.py --dry-run    # print what would upload

Reads DATABASE_URL and the R2_* variables from the environment. Exit status
is non-zero if any table failed to upload. Never prints a credential.

Scheduling: see railway.cron.md next to this file.
"""
import argparse
import io
import os
import pathlib
import sys
from datetime import datetime, timezone
from typing import Callable, Iterable, List, Optional

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import psycopg  # noqa: E402

from src.storage import r2  # noqa: E402

SNAPSHOT_PREFIX = 'snapshots'

# Never snapshot these even though they live in public: supabase's own
# bookkeeping, or anything that is not a real table.
SKIP_TABLES = {'schema_migrations', 'supabase_migrations'}


def snapshot_key(date_str: str, table: str) -> str:
    """R2 key for one table's CSV on one day."""
    return f'{SNAPSHOT_PREFIX}/{date_str}/{table}.csv'


def list_public_tables(conn) -> List[str]:
    """Every base table in the public schema, sorted, minus SKIP_TABLES."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' "
            "ORDER BY table_name"
        )
        return [row[0] for row in cur.fetchall() if row[0] not in SKIP_TABLES]


def dump_table_csv(conn, table: str) -> bytes:
    """The table as CSV bytes (header first), via COPY TO STDOUT."""
    # table comes from information_schema, but quote it anyway.
    ident = psycopg.sql.Identifier(table)
    query = psycopg.sql.SQL('COPY {} TO STDOUT WITH (FORMAT csv, HEADER true)').format(ident)
    buffer = io.BytesIO()
    with conn.cursor() as cur:
        with cur.copy(query) as copy:
            for chunk in copy:
                buffer.write(bytes(chunk))
    return buffer.getvalue()


def snapshot(
    dsn: str,
    date_str: Optional[str] = None,
    upload: Callable[[str, bytes], None] = None,
    tables: Optional[Iterable[str]] = None,
    log=print,
) -> List[str]:
    """Dump every public table and upload each. Returns the keys written.

    `upload(key, body)` defaults to r2.put_object with text/csv; tests pass
    a recorder. Raises RuntimeError if any table failed, after attempting
    all of them.
    """
    date_str = date_str or datetime.now(timezone.utc).strftime('%Y-%m-%d')
    if upload is None:
        def upload(key: str, body: bytes) -> None:
            r2.put_object(key, body, content_type='text/csv')

    written: List[str] = []
    failures: List[str] = []
    with psycopg.connect(dsn) as conn:
        names = list(tables) if tables is not None else list_public_tables(conn)
        for table in names:
            key = snapshot_key(date_str, table)
            try:
                body = dump_table_csv(conn, table)
                upload(key, body)
                written.append(key)
                log(f'  {key}  ({len(body)} bytes)')
            except Exception as exc:  # keep going; report at the end
                failures.append(f'{table}: {type(exc).__name__}: {exc}')
                log(f'  FAILED {table}: {type(exc).__name__}')
                # a failed COPY leaves the transaction aborted
                conn.rollback()

    if failures:
        raise RuntimeError('Snapshot incomplete: ' + '; '.join(failures))
    return written


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--date', help='YYYY-MM-DD folder to write (default: today, UTC)')
    parser.add_argument('--dry-run', action='store_true', help='dump but do not upload')
    args = parser.parse_args(argv)

    dsn = os.environ.get('DATABASE_URL')
    if not dsn:
        print('DATABASE_URL is not set', file=sys.stderr)
        return 2
    if not args.dry_run and not r2.is_configured():
        print('R2 is not configured (R2_ACCOUNT_ID / R2_ACCESS_KEY_ID / '
              'R2_SECRET_ACCESS_KEY / R2_BUCKET)', file=sys.stderr)
        return 2

    upload = None
    if args.dry_run:
        def upload(key: str, body: bytes) -> None:  # noqa: F811
            pass

    date_str = args.date or datetime.now(timezone.utc).strftime('%Y-%m-%d')
    print(f'Snapshot {date_str}{" (dry run)" if args.dry_run else ""}:')
    try:
        written = snapshot(dsn, date_str, upload=upload)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f'{len(written)} tables written under {SNAPSHOT_PREFIX}/{date_str}/')
    return 0


if __name__ == '__main__':
    sys.exit(main())
