"""Offline preflight for Torre Faro production artifacts."""
import os
from pathlib import Path
root = Path(__file__).resolve().parent
checks=[]
def check(name, ok, detail=''):
    checks.append((name,bool(ok),detail))

required = [
    ('Dockerfile', root/'Dockerfile'),
    ('docker-compose.yml', root/'docker-compose.yml'),
    ('docker-compose.prod.yml', root/'docker-compose.prod.yml'),
    ('Caddyfile', root/'Caddyfile'),
    ('.env.example', root/'.env.example'),
    ('Migration script', root/'migrate_sqlite_to_postgres.py'),
    ('Seed script', root/'seed_production.py'),
    ('Backup script', root/'deploy/backup_postgres.sh'),
    ('Restore drill script', root/'deploy/restore_drill.sh'),
    ('Healthcheck script', root/'deploy/healthcheck.sh'),
    ('App entrypoint', root/'app/main.py'),
]
for name,path in required: check(name,path.exists())
check('PostgreSQL dependency','psycopg' in (root/'requirements.txt').read_text())
check('API version','version="4.6.0"' in (root/'app/main.py').read_text())
for var in ('POSTGRES_PASSWORD','TF_ADMIN_USER','TF_ADMIN_PASSWORD','TF_AUTH_SECRET','TF_DOMAIN'):
    val=os.getenv(var,'')
    ok=bool(val) and all(x not in val.lower() for x in ('change','example','cambiar'))
    check(f'Runtime secret/domain {var}',ok,'set only at deploy time')

failed=[x for x in checks if not x[1]]
for name,ok,detail in checks:
    print(('OK  ' if ok else 'FAIL')+f' {name}'+(f' — {detail}' if detail else ''))
print(f'\n{len(checks)-len(failed)}/{len(checks)} preflight checks OK')
if os.getenv('ENVIRONMENT')=='production' and failed: raise SystemExit(1)
