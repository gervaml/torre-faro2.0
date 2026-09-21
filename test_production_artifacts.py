import os, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
r = subprocess.run([sys.executable, str(ROOT/'migrate_sqlite_to_postgres.py'), '--dry-run'], cwd=ROOT, capture_output=True, text=True)
assert r.returncode == 0, r.stdout + r.stderr
r2 = subprocess.run([sys.executable, str(ROOT/'production_check.py')], cwd=ROOT, capture_output=True, text=True)
assert r2.returncode == 0, r2.stdout + r2.stderr
assert 'preflight checks OK' in r2.stdout
print('Production artifact tests: OK')
