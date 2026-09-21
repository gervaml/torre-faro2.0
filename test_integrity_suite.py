import os
os.environ.setdefault('TF_ADMIN_USER','admin')
os.environ.setdefault('TF_ADMIN_PASSWORD','test-pass')
from fastapi.testclient import TestClient
from app.main import app

def auth():
    c=TestClient(app); r=c.post('/api/auth/login',json={'username':'admin','password':'test-pass'}); assert r.status_code==200
    return c, {'Authorization':'Bearer '+r.json()['token']}

def test_integrity_report_is_actionable():
    c,h=auth(); r=c.get('/api/integrity',headers=h); assert r.status_code==200
    j=r.json(); assert 'issues' in j
    assert j['total']==7
    assert len(j['issues']['units_without_participation'])==9
    assert len(j['issues']['contributions_non_positive'])==2
    assert len(j['issues']['expenses_zero_or_invalid'])==3

def test_closed_period_endpoint_shape():
    c,h=auth(); periods=c.get('/api/periods',headers=h).json()
    assert isinstance(periods,list) and all(isinstance(p,str) for p in periods)
