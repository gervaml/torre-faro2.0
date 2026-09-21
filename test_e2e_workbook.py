import os
from pathlib import Path
from fastapi.testclient import TestClient

WORKBOOK=Path('/mnt/data/SISTEMA TORRE FARO.xlsx')
os.environ.setdefault('TF_ADMIN_USER','admin')
os.environ.setdefault('TF_ADMIN_PASSWORD','test-pass')
from app.main import app

def test_real_workbook_pipeline():
    assert WORKBOOK.exists(), WORKBOOK
    c=TestClient(app)
    r=c.post('/api/auth/login',json={'username':'admin','password':'test-pass'}); assert r.status_code==200, r.text
    h={'Authorization':'Bearer '+r.json()['token']}
    with WORKBOOK.open('rb') as f:
        r=c.post('/api/import/excel/preview',headers=h,files={'file':('SISTEMA TORRE FARO.xlsx',f,'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')})
    assert r.status_code==200, r.text
    j=r.json(); assert len(j['found_authoritative'])==16, j['found_authoritative']
    imp=j['import_id']
    r=c.get(f'/api/import/excel/analyze/{imp}',headers=h); assert r.status_code==200, r.text
    a=r.json(); assert a['summary']['errors']==0, a['summary']
    assert a['sheets']['GASTOS NUEVO']['duplicates']==1657, a['sheets']['GASTOS NUEVO']
    assert a['sheets']['GASTOS NUEVO']['warnings']==3, a['sheets']['GASTOS NUEVO']
    r=c.get(f'/api/import/excel/reconcile/{imp}',headers=h); assert r.status_code==200, r.text
    rec=r.json(); assert rec['ok'] is True, rec
    assert rec['difference_count']==0, rec
    assert rec['workbook_period_from']=='2022-01' and rec['workbook_period_to']=='2024-12', rec
    assert rec['scope_warning'] is True, rec
    print('WORKBOOK E2E OK', {'sheets':16,'expense_duplicates':1660,'reconciliation_differences':0,'workbook_scope':'2022-01..2024-12','system_scope':f"{rec['system_period_from']}..{rec['system_period_to']}"})
