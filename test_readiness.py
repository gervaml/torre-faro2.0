import os
os.environ.setdefault('TF_ADMIN_USER','admin')
os.environ.setdefault('TF_ADMIN_PASSWORD','test-pass')
from fastapi.testclient import TestClient
from app.main import app
c=TestClient(app)
r=c.post('/api/auth/login',json={'username':'admin','password':'test-pass'}); assert r.status_code==200
t=r.json()['token']; h={'Authorization':'Bearer '+t}
r=c.get('/api/production/readiness',headers=h); assert r.status_code==200
j=r.json(); assert 'ready' in j and 'checks' in j and 'blocking_issues' in j
assert len(j['checks'])==9
print('READINESS OK', j['ready'])
