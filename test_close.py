import os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
os.environ.setdefault('TF_ADMIN_USER','admin'); os.environ.setdefault('TF_ADMIN_PASSWORD','test-pass')
from fastapi.testclient import TestClient
from app.main import app
c=TestClient(app); r=c.post('/api/auth/login',json={'username':'admin','password':'test-pass'}); assert r.status_code==200
h={'Authorization':'Bearer '+r.json()['token']}
r=c.get('/api/close/2098-01/checks',headers=h); assert r.status_code==200
r=c.get('/api/integrity',headers=h); assert r.status_code==200
print('CLOSE CHECKS OK')
