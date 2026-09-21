from fastapi.testclient import TestClient
import os
os.environ.setdefault('TF_ADMIN_USER','admin')
os.environ.setdefault('TF_ADMIN_PASSWORD','test-pass')
from app.main import app
c=TestClient(app)
r=c.post('/api/auth/login',json={'username':'admin','password':'test-pass'}); assert r.status_code==200
t={'Authorization':'Bearer '+r.json()['token']}
for path in ['/api/economic/summary','/api/reports/executive','/api/reports/financial']:
    r=c.get(path,headers=t); assert r.status_code==200,(path,r.text)
    assert r.json()
print('economic tests OK')
