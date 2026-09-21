import os, subprocess, sys, time, urllib.request, json
BASE='http://127.0.0.1:8011'
env=os.environ.copy(); env.update({'TF_ENV':'development','TF_ADMIN_USER':'admin','TF_ADMIN_PASSWORD':'admin','TF_AUTH_SECRET':'e2e-secret','DATABASE_URL':'sqlite:///./torre_faro_e2e.db'})
proc=subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8011'],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
def req(path, method='GET', data=None, token=None):
    headers={'Content-Type':'application/json'}
    if token: headers['Authorization']='Bearer '+token
    r=urllib.request.Request(BASE+path,method=method,headers=headers,data=(json.dumps(data).encode() if data else None))
    with urllib.request.urlopen(r,timeout=5) as x: return x.status,json.loads(x.read())
try:
    for _ in range(30):
        try: req('/api/health'); break
        except Exception: time.sleep(.2)
    status,login=req('/api/auth/login','POST',{'username':'admin','password':'admin'})
    token=login['token']
    checks=[]
    for path in ['/api/dashboard','/api/reports/executive','/api/integrity','/api/production/readiness','/api/system/status']:
        code,_=req(path,token=token); checks.append((path,code))
    assert all(c==200 for _,c in checks), checks
    print('E2E 5/5 OK')
finally:
    proc.terminate(); proc.wait(timeout=5)
