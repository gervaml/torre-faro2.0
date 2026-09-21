import os, sys
from fastapi.testclient import TestClient
sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault('TF_ADMIN_USER','admin')
os.environ.setdefault('TF_ADMIN_PASSWORD','test-pass')
from app.main import app
c=TestClient(app)
r=c.post('/api/auth/login',json={'username':'admin','password':'test-pass'})
assert r.status_code==200, r.text
t=r.json()['token']; h={'Authorization':'Bearer '+t}
for path in ['/api/health','/api/health/db','/api/dashboard','/api/integrity','/api/partners','/api/units','/api/contributions/monthly','/api/reports/economic-periods']:
    rr=c.get(path,headers=h); assert rr.status_code==200,(path,rr.status_code,rr.text[:500])
print('SMOKE OK')
