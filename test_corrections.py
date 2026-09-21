import os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
os.environ.setdefault('TF_ADMIN_USER','admin')
os.environ.setdefault('TF_ADMIN_PASSWORD','test-pass')
from fastapi.testclient import TestClient
from app.main import app

c=TestClient(app)
r=c.post('/api/auth/login',json={'username':'admin','password':'test-pass'}); assert r.status_code==200, r.text
h={'Authorization':'Bearer '+r.json()['token']}
r=c.post('/api/contributions',headers=h,json={'partner_id':1,'ab':'A','date':'2099-01-15','amount_ars':1000,'movement_type':'efectivo','concept':'Prueba'})
assert r.status_code==200, r.text
cid=r.json()['id']
r=c.get(f'/api/audit/contribution/{cid}',headers=h); assert r.status_code==200
old=r.json()['records'][0]['amount_ars']
r=c.post(f'/api/contributions/{cid}/correct',headers=h,json={'amount_ars':old+1,'reason':'Prueba de corrección'})
assert r.status_code==200, r.text
new=r.json()['correction_id']; assert new!=cid
r=c.get(f'/api/audit/contribution/{new}',headers=h); assert r.status_code==200
D=r.json(); assert any(x['id']==cid for x in D['records']); assert any(x['id']==new for x in D['records']); assert any(x['action']=='correct' for x in D['events'])
print('CORRECTION OK')
