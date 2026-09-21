"""One-shot, validated migration from SQLite to PostgreSQL.

Usage:
  DATABASE_URL='postgresql+psycopg://...' SQLITE_PATH=torre_faro.db python migrate_sqlite_to_postgres.py
  ... python migrate_sqlite_to_postgres.py --dry-run

The destination is intended to be a fresh production database. The script
runs all table writes in one transaction, validates row counts, and rolls back
on any failure.
"""
import argparse, os
from pathlib import Path
from sqlalchemy import create_engine, MetaData, select, insert, text

parser = argparse.ArgumentParser()
parser.add_argument('--dry-run', action='store_true', help='validate source only; do not connect to PostgreSQL')
args = parser.parse_args()

sqlite_path = Path(os.getenv('SQLITE_PATH', 'torre_faro.db')).resolve()
if not sqlite_path.exists():
    raise SystemExit(f'SQLite no existe: {sqlite_path}')

src = create_engine(f'sqlite:///{sqlite_path}')
source_meta = MetaData(); source_meta.reflect(bind=src)
source_counts = {}
with src.connect() as conn:
    for name, table in source_meta.tables.items():
        source_counts[name] = conn.execute(select(table.c if False else table)).fetchall().__len__()

print(f'Source: {sqlite_path}')
for name, count in source_counts.items():
    print(f'  {name}: {count}')

if args.dry_run:
    print('DRY RUN OK: fuente legible y tablas detectadas.')
    raise SystemExit(0)

dst_url = os.environ.get('DATABASE_URL')
if not dst_url or not dst_url.startswith(('postgresql://','postgresql+psycopg://')):
    raise SystemExit('DATABASE_URL debe apuntar a PostgreSQL')

dst = create_engine(dst_url, pool_pre_ping=True)
target_meta = MetaData(); target_meta.reflect(bind=dst)

with dst.begin() as conn:
    for name, table in source_meta.tables.items():
        target = target_meta.tables.get(name)
        if target is None:
            raise RuntimeError(f'Tabla ausente en destino: {name}')
        rows = conn.execution_options(isolation_level='AUTOCOMMIT') if False else None
        with src.connect() as sconn:
            data = sconn.execute(select(table)).mappings().all()
        conn.execute(target.delete())
        if data:
            conn.execute(insert(target), [dict(r) for r in data])
        actual = conn.execute(text(f'SELECT COUNT(*) FROM "{name}"')).scalar_one()
        if actual != len(data):
            raise RuntimeError(f'{name}: esperado {len(data)}, obtenido {actual}')
        print(f'{name}: {actual} filas OK')
print('MIGRACIÓN OK: transacción confirmada y conteos validados.')
