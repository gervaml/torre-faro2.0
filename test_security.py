import os
os.environ.setdefault('TF_ADMIN_USER','admin')
os.environ.setdefault('TF_ADMIN_PASSWORD','test-pass')
os.environ.setdefault('TF_AUTH_SECRET','test-secret')
from fastapi.testclient import TestClient
from app.main import app

def test_permissions_endpoint():
    c=TestClient(app)
    r=c.post('/api/auth/login',json={'username':'admin','password':'test-pass'})
    assert r.status_code==200
    token=r.json()['token']
    r=c.get('/api/auth/permissions',headers={'Authorization':f'Bearer {token}'})
    assert r.status_code==200
    assert r.json()['can_admin'] is True

def test_tampered_token_rejected():
    c=TestClient(app)
    r=c.get('/api/auth/me',headers={'Authorization':'Bearer abc.def'})
    assert r.status_code==401
