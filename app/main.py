
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy import create_engine, Column, Integer, String, Float, Date, Text, ForeignKey, func, Boolean, text
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from pydantic import BaseModel
from datetime import date, datetime, timezone
from pathlib import Path
import json, os, tempfile, uuid, hmac, hashlib, base64, io, secrets, subprocess, shutil

ROOT=Path(__file__).resolve().parent.parent
DB_URL=os.getenv("DATABASE_URL","sqlite:///./torre_faro.db")
connect_args={"check_same_thread":False} if DB_URL.startswith("sqlite") else {}
engine=create_engine(DB_URL,connect_args=connect_args,pool_pre_ping=True,pool_recycle=1800)
SessionLocal=sessionmaker(bind=engine,autocommit=False,autoflush=False)
Base=declarative_base()

AUTH_USER=os.getenv("TF_ADMIN_USER","admin")
AUTH_PASSWORD=os.getenv("TF_ADMIN_PASSWORD","cambiar-esta-clave")
if os.getenv("TF_ENV","development").lower() in {"production","prod"} and AUTH_PASSWORD=="cambiar-esta-clave": raise RuntimeError("TF_ADMIN_PASSWORD debe cambiarse en producción")
AUTH_SECRET=os.getenv("TF_AUTH_SECRET","dev-only-change-me")
if os.getenv("TF_ENV","development").lower() in {"production","prod"} and AUTH_SECRET=="dev-only-change-me": raise RuntimeError("TF_AUTH_SECRET es obligatorio y debe cambiarse en producción")
AUTH_ROLE=os.getenv("TF_ADMIN_ROLE","admin").lower()
ROLE_RANK={"viewer":1,"editor":2,"admin":3}

def _token(user):
    payload=base64.urlsafe_b64encode(json.dumps({"u":user,"r":AUTH_ROLE,"t":datetime.now(timezone.utc).replace(tzinfo=None).timestamp()}).encode()).decode().rstrip("=")
    sig=hmac.new(AUTH_SECRET.encode(),payload.encode(),hashlib.sha256).hexdigest()
    return payload+"."+sig

def _require_role(request, minimum="viewer"):
    identity=_auth(request)
    if ROLE_RANK.get(identity.get("role","viewer"),0) < ROLE_RANK[minimum]:
        raise HTTPException(403,"Permisos insuficientes")
    return identity

def _auth(request):
    token=request.headers.get("Authorization","").replace("Bearer ","")
    if not token or "." not in token: raise HTTPException(401,"Autenticación requerida")
    payload,sig=token.rsplit(".",1)
    expected=hmac.new(AUTH_SECRET.encode(),payload.encode(),hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig,expected): raise HTTPException(401,"Token inválido")
    try:
        data=json.loads(base64.urlsafe_b64decode(payload+"=="))
        if data.get("u")!=AUTH_USER or data.get("r")!=AUTH_ROLE or datetime.now(timezone.utc).replace(tzinfo=None).timestamp()-float(data.get("t",0))>43200: raise ValueError()
    except Exception: raise HTTPException(401,"Sesión vencida")
    return {"user":data["u"],"role":data.get("r",AUTH_ROLE)}

class Project(Base):
    __tablename__="projects"
    id=Column(Integer,primary_key=True)
    name=Column(String,unique=True)
    historical_investment_ars=Column(Float)
    historical_investment_usd=Column(Float)
    updated_investment_ars=Column(Float)
    updated_investment_usd=Column(Float)
    current_cac=Column(Float)
    current_tc=Column(Float)
    budget_remaining_usd=Column(Float)
    weighted_m2=Column(Float)
    a_share=Column(Float)
    b_share=Column(Float)
    delivery=Column(Date)

class Partner(Base):
    __tablename__="partners"
    id=Column(Integer,primary_key=True)
    name=Column(String,unique=True)
    devengado_ars=Column(Float,default=0)
    efectivo_ars=Column(Float,default=0)
    participation=Column(Float,default=0)

class Unit(Base):
    __tablename__="units"
    id=Column(Integer,primary_key=True)
    code=Column(String,unique=True)
    floor=Column(String)
    type=Column(String)
    denom=Column(String)
    covered_m2=Column(Float)
    semi_m2=Column(Float)
    total_m2=Column(Float)
    weighted_m2=Column(Float)
    participation=Column(Float)

class Param(Base):
    __tablename__="parameters"
    id=Column(Integer,primary_key=True)
    period=Column(String,unique=True)
    cac=Column(Float)
    tc=Column(Float)

class Expense(Base):
    __tablename__="expenses"
    id=Column(Integer,primary_key=True)
    source_row=Column(Integer)
    supplier=Column(String)
    date=Column(Date)
    period=Column(String)
    ab=Column(String)
    ars_historical=Column(Float)
    created_at=Column(String)
    source=Column(String,default="excel_import")
    corrected_from_id=Column(Integer,nullable=True)

class Movement(Base):
    __tablename__="movements"
    id=Column(Integer,primary_key=True)
    source_row=Column(Integer)
    date=Column(Date)
    concept=Column(Text)
    movement_type=Column(String,default="imported")
    partner_id=Column(Integer,ForeignKey("partners.id"),nullable=True)
    ab=Column(String,nullable=True)
    amount_ars=Column(Float)
    created_at=Column(String)
    source=Column(String,default="excel_import")
    correction_of_id=Column(Integer,nullable=True)

class Contribution(Base):
    __tablename__="contributions"
    id=Column(Integer,primary_key=True)
    partner_id=Column(Integer,ForeignKey("partners.id"),nullable=False)
    period=Column(String,nullable=False)
    movement_date=Column(Date,nullable=True)
    ab=Column(String,nullable=True)
    type=Column(String,nullable=False)
    amount_ars=Column(Float,nullable=False)
    source=Column(String,default="excel_import")
    source_row=Column(Integer,nullable=True)
    concept=Column(Text,default="")
    created_at=Column(String)
    correction_of_id=Column(Integer,nullable=True)

class MonthlyClose(Base):
    __tablename__="monthly_closes"
    id=Column(Integer,primary_key=True)
    period=Column(String,unique=True,nullable=False)
    status=Column(String,default="open")
    closed_at=Column(String,nullable=True)
    closed_by=Column(String,nullable=True)
    notes=Column(Text,default="")

class CloseSnapshot(Base):
    __tablename__="close_snapshots"
    id=Column(Integer,primary_key=True)
    period=Column(String,unique=True,nullable=False)
    created_at=Column(String,nullable=False)
    created_by=Column(String,nullable=False)
    payload=Column(Text,nullable=False)

class AuditEvent(Base):
    __tablename__="audit_events"
    id=Column(Integer,primary_key=True)
    entity=Column(String,nullable=False)
    entity_id=Column(Integer,nullable=True)
    action=Column(String,nullable=False)
    reason=Column(Text,default="")
    actor=Column(String,default="system")
    created_at=Column(String,nullable=False)
    old_value=Column(Text,nullable=True)
    new_value=Column(Text,nullable=True)

class BudgetAdjustment(Base):
    __tablename__="budget_adjustments"
    id=Column(Integer,primary_key=True)
    date=Column(Date)
    amount_usd=Column(Float)
    reason=Column(String)
    created_at=Column(String)

Base.metadata.create_all(engine)

app=FastAPI(title="Torre Faro API",version="4.6.0")

@app.middleware("http")
async def auth_middleware(request:Request, call_next):
    path=request.url.path
    if path.startswith("/api/") and path not in ("/api/health","/api/auth/login"):
        try: _auth(request)
        except HTTPException as e:
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=e.status_code,content={"detail":e.detail})
    return await call_next(request)

class LoginIn(BaseModel):
    username:str
    password:str

@app.post("/api/auth/login")
def login(x:LoginIn):
    if not hmac.compare_digest(x.username,AUTH_USER) or not hmac.compare_digest(x.password,AUTH_PASSWORD):
        raise HTTPException(401,"Usuario o contraseña incorrectos")
    return {"token":_token(x.username),"user":x.username,"role":AUTH_ROLE,"expires_hours":12}

@app.get("/api/auth/me")
def me(request:Request):
    return _auth(request)

@app.get("/api/auth/permissions")
def permissions(request:Request):
    identity=_auth(request)
    role=identity.get("role","viewer")
    return {"user":identity.get("user"),"role":role,"can_view":True,"can_edit":ROLE_RANK.get(role,0)>=ROLE_RANK["editor"],"can_admin":ROLE_RANK.get(role,0)>=ROLE_RANK["admin"]}

@app.get("/api/backup")
def backup(request:Request):
    _auth(request)
    stamp=datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y%m%d_%H%M%S")
    if DB_URL.startswith("sqlite"):
        dbpath=Path("./torre_faro.db")
        if not dbpath.exists(): raise HTTPException(404,"Base de datos no encontrada")
        return FileResponse(dbpath,media_type="application/octet-stream",filename=f"torre_faro_backup_{stamp}.db")
    if DB_URL.startswith("postgresql"):
        pg_dump=shutil.which("pg_dump")
        if not pg_dump: raise HTTPException(500,"pg_dump no está instalado en el servidor")
        out=Path(tempfile.gettempdir())/f"torre_faro_backup_{stamp}.sql"
        try:
            subprocess.run([pg_dump,DB_URL,"--format=custom","--file",str(out)],check=True,capture_output=True,text=True,timeout=120)
        except subprocess.CalledProcessError as e:
            raise HTTPException(500,f"No se pudo generar el backup: {e.stderr[-500:]}")
        return FileResponse(out,media_type="application/octet-stream",filename=out.name,background=None)
    raise HTTPException(400,"Motor de base de datos no soportado para backup")

@app.get("/api/health/db")
def health_db(request:Request, s:Session=Depends(lambda: SessionLocal())):
    _auth(request)
    try:
        s.execute(__import__('sqlalchemy').text("SELECT 1"))
        return {"status":"ok","database":"postgresql" if DB_URL.startswith("postgresql") else "sqlite"}
    finally:
        s.close()

def db(): 
    s=SessionLocal()
    try: yield s
    finally: s.close()

def seed():
    s=SessionLocal()
    if s.query(Project).count()==0:
        p=json.load(open(ROOT/"data/project.json",encoding="utf8"))
        s.add(Project(name=p["name"],**{k:(date.fromisoformat(v) if k=="delivery" else v) for k,v in p.items() if k!="name"}))
        for x in json.load(open(ROOT/"data/socios.json",encoding="utf8")): s.add(Partner(name=x["name"],devengado_ars=x["devengado_ars"],efectivo_ars=x["efectivo_ars"],participation=x["participation"]))
        for x in json.load(open(ROOT/"data/units.json",encoding="utf8")): s.add(Unit(code=x["unit"],floor=x["floor"],type=x["type"],denom=x["denom"],covered_m2=x["covered_m2"],semi_m2=x["semi_m2"],total_m2=x["total_m2"],weighted_m2=x["weighted_m2"],participation=x["participation"]))
        cac=json.load(open(ROOT/"data/cac.json")); tc=json.load(open(ROOT/"data/tc.json"))
        for period,val in cac.items(): s.add(Param(period=period,cac=val,tc=tc.get(period)))
        for x in json.load(open(ROOT/"data/expenses.json",encoding="utf8")):
            ex=dict(x)
            if isinstance(ex.get("date"),str): ex["date"]=date.fromisoformat(ex["date"])
            s.add(Expense(**ex,created_at=datetime.now(timezone.utc).replace(tzinfo=None).isoformat()))
        for x in json.load(open(ROOT/"data/movements.json",encoding="utf8")):
            s.add(Movement(**{k:v for k,v in {**x,"date":date.fromisoformat(x["date"]),"created_at":datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),"movement_type":"imported"}.items() if k in {"source_row","date","concept","movement_type","ab","amount_ars","created_at","source","correction_of_id"}}))
        # Authoritative contribution history: import normalized devengados/efectivos and map account names to partners.
        s.flush()
        name_map={p.name.strip().upper():p.id for p in s.query(Partner).all()}
        import pandas as pd
        month_map={"ene":1,"feb":2,"mar":3,"abr":4,"may":5,"jun":6,"jul":7,"ago":8,"sep":9,"oct":10,"nov":11,"dic":12}
        def parse_period(raw):
            raw=str(raw).strip().lower()
            if len(raw)>=7 and raw[4]=="-" and raw[:4].isdigit(): return raw[:7]
            parts=raw.replace(".","").split()
            if len(parts)==2 and parts[0] in month_map and parts[1].isdigit(): return f"{int(parts[1]):04d}-{month_map[parts[0]]:02d}"
            if "-" in raw and len(raw)==6 and raw[:3] in month_map: return f"20{raw[4:6]}-{month_map[raw[:3]]:02d}"
            return None
        for fn,typ in [("Torre_Faro_devengados_normalizados.csv","devengado"),("Torre_Faro_efectivos_normalizados.csv","efectivo")]:
            df=pd.read_csv(ROOT/"data"/fn)
            for _,r in df.iterrows():
                per=parse_period(r["periodo"])
                if not per: continue
                account=str(r["socio_cuenta"]).strip()
                if account.upper()=="TOTAL": continue
                is_b=account.upper().endswith(" B")
                base_name=account[:-2].strip() if is_b else account
                pid=name_map.get(base_name.upper())
                if not pid: continue
                s.add(Contribution(partner_id=pid,period=per,ab="B" if is_b else "A",type=typ,amount_ars=float(r["importe"]),source_row=int(r["fila_excel_origen"]),source="excel_import",created_at=datetime.now(timezone.utc).replace(tzinfo=None).isoformat()))
        s.commit()
    s.close()
seed()


@app.post("/api/import/excel/preview")
async def excel_preview(file: UploadFile = File(...)):
    """Stage an Excel workbook and return a non-destructive preview/validation."""
    import pandas as pd
    if not file.filename.lower().endswith((".xlsx", ".xlsm", ".xls")):
        raise HTTPException(400, "El archivo debe ser Excel (.xlsx/.xlsm/.xls)")
    raw=await file.read()
    if len(raw)>25*1024*1024:
        raise HTTPException(400, "El archivo supera el límite de 25 MB")
    path=Path(tempfile.gettempdir())/f"tf_import_{uuid.uuid4().hex}.xlsx"
    path.write_bytes(raw)
    try:
        xl=pd.ExcelFile(path)
        authoritative=["Check List mensual","CAC  y TC","RESUMEN TORRE FARO","Asignación deptos comunes","Propuesta Torre Faro","% por Dpto","Unidades y M²","APORTES DEV. VS EFECT. ARS","APORTES DEV. VS EFECT. USD","Ctas Ctes USD HIST","Ctas Ctes","FG"," Aportes USD"," Aportes $ CAC","Resumen Gastos Nuevo","GASTOS NUEVO"]
        found=[x for x in authoritative if x in xl.sheet_names]
        missing=[x for x in authoritative if x not in xl.sheet_names]
        sheets=[]
        for name in found:
            df=pd.read_excel(path,sheet_name=name,header=None,nrows=8)
            sheets.append({"name":name,"rows":int(pd.read_excel(path,sheet_name=name,header=None).shape[0]),"cols":int(pd.read_excel(path,sheet_name=name,header=None).shape[1]),"preview":df.fillna("").astype(str).values.tolist()[:8]})
        token=uuid.uuid4().hex
        staging=ROOT/"data"/"imports"; staging.mkdir(exist_ok=True)
        (staging/f"{token}.xlsx").write_bytes(raw)
        return {"import_id":token,"filename":file.filename,"size_bytes":len(raw),"found_authoritative":found,"missing_authoritative":missing,"sheets":sheets,"status":"preview_only"}
    finally:
        path.unlink(missing_ok=True)



def _norm(v):
    if v is None: return ""
    try:
        if v != v: return ""
    except Exception:
        pass
    return str(v).strip().lower()

def _num(v):
    try:
        if v is None or str(v).strip()=="": return None
        return float(v)
    except Exception:
        return None

def _expense_historical_cols(df):
    # GASTOS NUEVO keeps the source/historical amount in the first block;
    # the coefficient beside it is used to derive the CAC-adjusted value.
    cols={_norm(c):c for c in df.columns}
    if all(k in cols for k in ('proveedor','fecha','a o b','importe')):
        return cols['proveedor'], cols['fecha'], cols['a o b'], cols['importe']
    return (_find_col(df,['proveedor']),_find_col(df,['fecha']),_find_col(df,['a/b','a o b']),_find_col(df,['importe','monto','ars']))


def _find_col(df, candidates):
    cols={_norm(c):c for c in df.columns}
    for c in candidates:
        if _norm(c) in cols: return cols[_norm(c)]
    for c in df.columns:
        n=_norm(c)
        if any(x in n for x in candidates): return c
    return None

@app.get("/api/import/excel/analyze/{import_id}")
def excel_analyze(import_id:str,s:Session=Depends(db)):
    """Deep validation without writing business data."""
    import pandas as pd
    path=ROOT/"data"/"imports"/f"{import_id}.xlsx"
    if not path.exists(): raise HTTPException(404,"Importación no encontrada o vencida")
    xl=pd.ExcelFile(path)
    result={"import_id":import_id,"status":"analyzed","sheets":{},"summary":{"new":0,"duplicates":0,"errors":0,"warnings":0}}

    # Expenses: identify columns flexibly, validate required fields and fingerprint against DB.
    if "GASTOS NUEVO" in xl.sheet_names:
        raw=pd.read_excel(path,sheet_name="GASTOS NUEVO",header=3)
        supplier_col,date_col,ab_col,amount_col=_expense_historical_cols(raw)
        rows=[]; errors=duplicates=warnings=0; new=0
        existing={(e.date.isoformat() if e.date else "",_norm(e.supplier),round(e.ars_historical,2),e.ab or "") for e in s.query(Expense).all()}
        for i,r in raw.iterrows():
            # Ignore completely empty rows.
            vals=list(r.values)
            if all(_norm(v)=="" or _norm(v)=="nan" for v in vals): continue
            sup=_norm(r[supplier_col]) if supplier_col else ""
            dt=None
            if date_col:
                try: dt=pd.to_datetime(r[date_col],errors="coerce")
                except Exception: dt=None
            amt=_num(r[amount_col]) if amount_col else None
            ab=_norm(r[ab_col]).upper() if ab_col else ""
            errs=[]
            if not sup: errs.append("falta proveedor")
            if dt is None or pd.isna(dt): errs.append("fecha inválida")
            if amt is None: errs.append("importe inválido")
            elif amt==0: errs.append("importe cero (se omite)")
            elif amt<0: errs.append("importe negativo")
            if ab and ab not in ("A","B"): errs.append("A/B inválido")
            iso=dt.date().isoformat() if dt is not None and not pd.isna(dt) else ""
            fp=(iso,sup,round(amt,2) if amt is not None else None,ab)
            dup=fp in existing
            if errs:
                if errs == ["importe cero (se omite)"]: warnings += 1
                else: errors += 1
            elif dup: duplicates+=1
            else: new+=1
            if errs or dup:
                rows.append({"excel_row":int(i)+2,"status":"error" if errs else "duplicate","issues":errs or ["posible duplicado"],"supplier":sup,"date":iso,"amount_ars":amt,"ab":ab})
        result["sheets"]["GASTOS NUEVO"]={"rows_scanned":len(raw),"new":new,"duplicates":duplicates,"errors":errors,"warnings":warnings,"sample_issues":rows[:100],"columns":{"supplier":str(supplier_col) if supplier_col is not None else None,"date":str(date_col) if date_col is not None else None,"amount":str(amount_col) if amount_col is not None else None,"ab":str(ab_col) if ab_col is not None else None}}
        result["summary"]["new"]+=new; result["summary"]["duplicates"]+=duplicates; result["summary"]["errors"]+=errors; result["summary"]["warnings"]+=warnings

    # Contributions: validate presence of partner/period/amount columns where possible; do not commit automatically yet.
    if " Aportes $ CAC" in xl.sheet_names:
        raw=pd.read_excel(path,sheet_name=" Aportes $ CAC",header=None)
        result["sheets"][" Aportes $ CAC"]={"rows_scanned":len(raw),"status":"review_required","note":"La hoja requiere identificar inequívocamente período, socio, A/B e importe antes de afectar el libro histórico."}
        result["summary"]["warnings"]+=1
    return result


def _parse_month_header(v):
    """Parse Excel month labels such as 'ene. 2022', 'ene 2022' or YYYY-MM."""
    if v is None: return None
    x=str(v).strip().lower().replace('.', '')
    months={'ene':1,'feb':2,'mar':3,'abr':4,'may':5,'jun':6,'jul':7,'ago':8,'sep':9,'oct':10,'nov':11,'dic':12}
    if len(x)==7 and x[4]=='-' and x[:4].isdigit(): return x
    parts=x.split()
    if len(parts)==2 and parts[0][:3] in months and parts[1].isdigit():
        return f"{int(parts[1]):04d}-{months[parts[0][:3]]:02d}"
    return None

def _read_matrix_contributions(path):
    """Read the authoritative ARS historical contribution matrix from Excel.
    Returns normalized rows without mutating the DB."""
    import pandas as pd
    sheet='APORTES DEV. VS EFECT. ARS'
    if sheet not in pd.ExcelFile(path).sheet_names: return []
    raw=pd.read_excel(path,sheet_name=sheet,header=None)
    # Month labels are on the row containing 'Total'.
    header_row=None
    for i in range(min(20,len(raw))):
        vals=[_norm(v) for v in raw.iloc[i].tolist()]
        if 'total' in vals:
            header_row=i; break
    if header_row is None: return []
    periods={j:_parse_month_header(raw.iat[header_row,j]) for j in range(raw.shape[1])}
    periods={j:p for j,p in periods.items() if p}
    tmp=SessionLocal()
    try:
        partners={p.name.strip().upper():p.id for p in tmp.query(Partner).all()}
    finally:
        tmp.close()
    rows=[]
    # The first historical devengado block ends at its TOTAL row; do not read the later
    # efectivo / CAC-adjusted sections of the same worksheet.
    block_end=len(raw)
    for i in range(header_row+1,len(raw)):
        probes=[raw.iat[i,j] for j in range(min(3,raw.shape[1]))]
        if any(_norm(v) == 'total' for v in probes):
            block_end=i
            break
    for i in range(header_row+1,block_end):
        label=raw.iat[i,0]
        if label is None or _norm(label) in ('','total'): continue
        label=str(label).strip(); upper=label.upper()
        # Stop at non-account sections / totals.
        base=label[:-2].strip() if upper.endswith(' B') else label
        pid=partners.get(base.upper())
        if not pid: continue
        ab='B' if upper.endswith(' B') else 'A'
        for j,per in periods.items():
            amt=_num(raw.iat[i,j])
            if amt is not None and abs(amt)>0:
                rows.append((pid,per,ab,'devengado',round(amt,2),i+1,j+1))
    return rows

@app.get('/api/import/excel/reconcile/{import_id}')
def excel_reconcile(import_id:str, request:Request, s:Session=Depends(db)):
    """Compare the uploaded workbook's historical contribution matrix against the system ledger."""
    _auth(request)
    import pandas as pd
    path=ROOT/'data'/'imports'/f'{import_id}.xlsx'
    if not path.exists(): raise HTTPException(404,'Importación no encontrada o vencida')
    rows=_read_matrix_contributions(path)
    # Aggregate workbook and system by partner/period/A-B/type.
    wb={}
    for pid,per,ab,typ,amt,er,ec in rows: wb[(pid,per,typ)]=wb.get((pid,per,typ),0)+amt
    # Devengado is the authoritative monthly matrix in the workbook. Effective contributions are reconciled from the normalized historical CSV loaded into the staged system.
    dbrows=s.query(Contribution).filter_by(type="devengado").all()
    dbm={}
    for c in dbrows: dbm[(c.partner_id,c.period,c.type)]=dbm.get((c.partner_id,c.period,c.type),0)+round(c.amount_ars,2)
    common=set(wb)&set(dbm); diffs=[]
    for k in sorted(common,key=lambda x:(x[1],x[0],x[2])):
        w=wb.get(k,0); d=dbm.get(k,0); delta=round(d-w,2)
        if abs(delta)>=0.01:
            diffs.append({'partner_id':k[0],'period':k[1],'type':k[2],'workbook_ars':round(w,2),'system_ars':round(d,2),'delta_ars':delta})
    wb_periods=sorted({k[1] for k in wb}); db_periods=sorted({k[1] for k in dbm})
    system_only=sorted(set(db_periods)-set(wb_periods))
    return {'import_id':import_id,'status':'reconciled','rows_read':len(rows),'workbook_keys':len(wb),'system_keys':len(dbm),
            'workbook_period_from':wb_periods[0] if wb_periods else None,'workbook_period_to':wb_periods[-1] if wb_periods else None,
            'system_period_from':db_periods[0] if db_periods else None,'system_period_to':db_periods[-1] if db_periods else None,
            'system_only_periods':system_only,'differences':diffs[:500],'difference_count':len(diffs),'ok':not diffs,
            'scope_warning':bool(system_only)}

@app.post("/api/import/excel/commit/{import_id}")
def excel_commit(import_id:str,request:Request,s:Session=Depends(db)):
    """Commit validated expense rows; never overwrite existing history."""
    _require_role(request,"editor")
    import pandas as pd
    path=ROOT/"data"/"imports"/f"{import_id}.xlsx"
    if not path.exists(): raise HTTPException(404,"Importación no encontrada o vencida")
    xl=pd.ExcelFile(path); committed=[]; skipped=[]; errors=[]
    if "GASTOS NUEVO" in xl.sheet_names:
        raw=pd.read_excel(path,sheet_name="GASTOS NUEVO",header=3)
        supplier_col,date_col,ab_col,amount_col=_expense_historical_cols(raw)
        if not supplier_col or not date_col or not amount_col:
            errors.append("No se pudieron identificar columnas obligatorias de GASTOS NUEVO")
        else:
            existing={(e.date.isoformat() if e.date else "",_norm(e.supplier),round(e.ars_historical,2),e.ab or "") for e in s.query(Expense).all()}
            for i,r in raw.iterrows():
                vals=list(r.values)
                if all(_norm(v)=="" or _norm(v)=="nan" for v in vals): continue
                sup=_norm(r[supplier_col]); dt=pd.to_datetime(r[date_col],errors="coerce"); amt=_num(r[amount_col]); ab=_norm(r[ab_col]).upper() if ab_col else ""
                if not sup or pd.isna(dt) or amt is None or amt<=0 or (ab and ab not in ("A","B")):
                    skipped.append({"excel_row":int(i)+2,"reason":"datos inválidos"}); continue
                d=dt.date(); fp=(d.isoformat(),sup,round(amt,2),ab)
                if fp in existing:
                    skipped.append({"excel_row":int(i)+2,"reason":"duplicado"}); continue
                period=d.strftime("%Y-%m")
                if s.query(MonthlyClose).filter_by(period=period,status="closed").first():
                    skipped.append({"excel_row":int(i)+2,"reason":f"período {period} cerrado"}); continue
                e=Expense(source_row=int(i)+2,supplier=str(r[supplier_col]).strip(),date=d,period=period,ab=ab or None,ars_historical=amt,created_at=datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),source="excel_import")
                s.add(e); existing.add(fp); committed.append({"excel_row":int(i)+2,"supplier":e.supplier,"date":d.isoformat(),"amount_ars":amt})
    if " Aportes $ CAC" in xl.sheet_names:
        skipped.append({"sheet":" Aportes $ CAC","reason":"requiere mapeo inequívoco antes de afectar históricos"})
    s.add(AuditEvent(entity="excel_import",entity_id=None,action="commit",reason=f"import_id={import_id}; committed={len(committed)}; skipped={len(skipped)}",actor="admin",created_at=datetime.now(timezone.utc).replace(tzinfo=None).isoformat()))
    s.commit()
    return {"import_id":import_id,"status":"committed","committed_count":len(committed),"skipped_count":len(skipped),"committed":committed[:200],"skipped":skipped[:200],"errors":errors}

app.mount("/static",StaticFiles(directory=str(ROOT/"static")),name="static")

@app.get("/api/integrity")
def integrity(request:Request, s:Session=Depends(db)):
    """Run non-destructive consistency checks over the financial core."""
    _require_role(request,"viewer")
    checks=[]
    def add(code,label,ok,detail=""):
        checks.append({"code":code,"label":label,"ok":bool(ok),"detail":detail})
    # Master data
    units=s.query(Unit).all()
    partners=s.query(Partner).all()
    add("units_count","29 unidades operativas",len(units)==29,f"Encontradas: {len(units)}")
    add("partners_count","8 socios",len(partners)==8,f"Encontrados: {len(partners)}")
    # Participation
    parts=[u.participation for u in units if u.participation is not None]
    missing=sum(1 for u in units if u.participation is None)
    add("unit_participation_complete","Participación de unidades completa",missing==0,f"Sin participación: {missing}")
    if parts:
        total=sum(parts)
        add("unit_participation_sum","Participación de unidades = 100%",abs(total-1)<1e-6,f"Suma: {total:.8f}")
    # Contributions
    contrib=s.query(Contribution).all()
    invalid=sum(1 for x in contrib if x.amount_ars is None or x.amount_ars<=0 or not x.period or len(x.period)!=7)
    add("contributions_valid","Aportes con importe/período válidos",invalid==0,f"Inválidos: {invalid}")
    # Expenses
    expenses=s.query(Expense).all()
    invalid_exp=sum(1 for x in expenses if x.ars_historical is None or x.ars_historical<=0 or x.date is None)
    add("expenses_valid","Gastos con importe/fecha válidos",invalid_exp==0,f"Inválidos: {invalid_exp}")
    # Closed periods must not have normal post-close manual records
    closed={x.period for x in s.query(MonthlyClose).filter_by(status="closed").all()}
    blocked=sum(1 for x in contrib if x.period in closed and x.source=="manual")
    add("closed_periods","Períodos cerrados sin aportes manuales posteriores",blocked==0,f"Aportes manuales detectados: {blocked}")
    failed=sum(1 for x in checks if not x["ok"])
    issues={
        "units_without_participation":[x.code for x in units if x.participation is None],
        "contributions_non_positive":[{"id":x.id,"period":x.period,"partner_id":x.partner_id,"amount_ars":x.amount_ars,"type":x.type} for x in contrib if x.amount_ars is None or x.amount_ars<=0],
        "expenses_zero_or_invalid":[{"id":x.id,"supplier":x.supplier,"date":str(x.date) if x.date else None,"ars_historical":x.ars_historical} for x in expenses if x.ars_historical is None or x.ars_historical<=0 or x.date is None],
    }
    return {"status":"ok" if failed==0 else "attention","checks":checks,"failed":failed,"total":len(checks),"issues":issues,"generated_at":datetime.now(timezone.utc).replace(tzinfo=None).isoformat()}

@app.get("/api/integrity/summary")
def integrity_summary(request:Request, s:Session=Depends(db)):
    _require_role(request,"viewer")
    units=s.query(Unit).all(); contrib=s.query(Contribution).all(); expenses=s.query(Expense).all()
    return {
        "units_without_participation":[u.code for u in units if u.participation is None],
        "contributions_non_positive":[{"id":c.id,"period":c.period,"amount_ars":c.amount_ars,"type":c.type} for c in contrib if c.amount_ars is None or c.amount_ars<=0],
        "expenses_zero_or_invalid":[{"id":e.id,"supplier":e.supplier,"amount_ars":e.ars_historical} for e in expenses if e.ars_historical is None or e.ars_historical<=0],
        "counts":{"units":len(units),"contributions":len(contrib),"expenses":len(expenses)}
    }

@app.get("/api/production/readiness")
def production_readiness(request:Request, s:Session=Depends(db)):
    _require_role(request,"admin")
    checks=[]
    env=os.getenv("TF_ENV","development").lower()
    db_kind="postgresql" if DB_URL.startswith("postgresql") else "sqlite"
    checks.append({"check":"environment","ok":env in {"production","prod"},"detail":env})
    checks.append({"check":"database","ok":db_kind=="postgresql", "detail":db_kind})
    try:
        s.execute(text("SELECT 1"))
        db_ok=True
    except Exception as exc:
        db_ok=False
        db_detail=str(exc)
    checks.append({"check":"database_connection","ok":db_ok,"detail":"conexión OK" if db_ok else db_detail})
    units=s.query(Unit).all()
    missing_units=[u.code for u in units if u.participation is None or u.participation<=0]
    checks.append({"check":"units","ok":len(units)==29 and not missing_units,"detail":f"{len(units)} unidades; sin participación válida: {len(missing_units)}"})
    p=s.query(Project).first()
    checks.append({"check":"project_parameters","ok":bool(p and p.current_cac and p.current_tc and p.current_cac>0 and p.current_tc>0),"detail":"CAC y TC configurados" if p and p.current_cac and p.current_tc else "Faltan parámetros"})
    partners=s.query(Partner).all()
    checks.append({"check":"partners","ok":len(partners)==8,"detail":f"{len(partners)} socios"})
    expenses=s.query(Expense).all()
    bad_exp=[e.id for e in expenses if e.ars_historical is None or e.ars_historical<=0]
    checks.append({"check":"expenses","ok":not bad_exp,"detail":f"{len(expenses)} gastos; inválidos: {len(bad_exp)}"})
    contrib=s.query(Contribution).all()
    bad_contrib=[c.id for c in contrib if c.amount_ars is None or c.amount_ars<=0]
    checks.append({"check":"contributions","ok":not bad_contrib,"detail":f"{len(contrib)} aportes; no positivos: {len(bad_contrib)}"})
    secret_ok=env not in {"production","prod"} or (AUTH_PASSWORD not in {"cambiar-esta-clave", ""} and AUTH_SECRET not in {"dev-only-change-me", ""})
    checks.append({"check":"secrets","ok":secret_ok,"detail":"secretos de producción configurados" if secret_ok else "faltan secretos de producción"})
    ready=all(c["ok"] for c in checks)
    return {"ready":ready,"checks":checks,"blocking_issues":[c for c in checks if not c["ok"]],"version":"4.6.0"}

@app.get("/")
def home(): return FileResponse(ROOT/"static/index.html")

@app.get("/api/system/status")
def system_status(request:Request, s:Session=Depends(db)):
    identity=_auth(request)
    if ROLE_RANK.get(identity.get("role","viewer"),0) < ROLE_RANK["admin"]:
        raise HTTPException(403,"Permiso insuficiente")
    db_kind="postgresql" if DB_URL.startswith("postgresql") else "sqlite"
    return {
        "version":"4.6.0",
        "environment":os.getenv("TF_ENV","development"),
        "database":db_kind,
        "counts":{
            "partners":s.query(Partner).count(),
            "units":s.query(Unit).count(),
            "expenses":s.query(Expense).count(),
            "movements":s.query(Movement).count(),
            "contributions":s.query(Contribution).count(),
            "audit_events":s.query(AuditEvent).count(),
            "closed_periods":s.query(MonthlyClose).filter(MonthlyClose.status=="closed").count(),
        }
    }

@app.get("/api/health")
def health(): return {"status":"ok","database":DB_URL.split(":")[0]}

def calc_exp(e,p,pr=None):
    if not p or not p.cac or not p.tc: return {"ars_cac":None,"usd_historical":None,"usd_current":None}
    if pr is None: pr=Project(current_cac=p.cac,current_tc=p.tc)
    ars=e.ars_historical*pr.current_cac/p.cac
    uh=e.ars_historical/p.tc
    uc=ars/pr.current_tc
    return {"ars_cac":ars,"usd_historical":uh,"usd_current":uc}

@app.get("/api/dashboard")
def dashboard(request:Request=None, s:Session=Depends(db)):
    if request is not None:
        _require_role(request,"viewer")
    p=s.query(Project).first()
    adj=s.query(func.coalesce(func.sum(BudgetAdjustment.amount_usd),0)).scalar() or 0
    expenses=s.query(Expense).all()
    new=0
    for e in expenses:
        if e.source=="manual":
            par=s.query(Param).filter_by(period=e.period).first()
            new+=calc_exp(e,par,p)["usd_current"] or 0
    budget=p.budget_remaining_usd-new+adj
    progress=p.updated_investment_usd/(p.updated_investment_usd+budget)
    return {"project":p.name,"historical_usd":p.historical_investment_usd,"updated_usd":p.updated_investment_usd,
            "budget_remaining_usd":budget,"progress":progress,"cost_m2":p.updated_investment_usd/p.weighted_m2,
            "partners":s.query(Partner).count(),"units":s.query(Unit).count(),"expenses":s.query(Expense).count()}

@app.get("/api/partners")
def partners(s:Session=Depends(db)):
    out=[]
    for p in s.query(Partner).order_by(Partner.name):
        dev=s.query(func.coalesce(func.sum(Contribution.amount_ars),0)).filter_by(partner_id=p.id,type="devengado").scalar() or 0
        eff=s.query(func.coalesce(func.sum(Contribution.amount_ars),0)).filter_by(partner_id=p.id,type="efectivo").scalar() or 0
        out.append({"id":p.id,"name":p.name,"participation":p.participation,"devengado_ars":dev,"efectivo_ars":eff,"pending_ars":dev-eff,"fulfilled":min(1,eff/dev) if dev else 0})
    return out

@app.get("/api/units")
def units(s:Session=Depends(db)):
    p=s.query(Project).first()
    return [{"code":u.code,"floor":u.floor,"type":u.type,"denom":u.denom,"covered_m2":u.covered_m2,
             "semi_m2":u.semi_m2,"weighted_m2":u.weighted_m2,"participation":u.participation,
             "investment_usd":(p.updated_investment_usd*u.participation if u.participation is not None else None),
             "usd_m2":(p.updated_investment_usd*u.participation/u.weighted_m2 if u.weighted_m2 and u.participation is not None else None)}
            for u in s.query(Unit).order_by(Unit.id)]


class ContributionIn(BaseModel):
    partner_id:int
    ab:str
    date:date
    amount_ars:float
    movement_type:str
    concept:str=""

    @property
    def period(self):
        return self.date.strftime("%Y-%m")

@app.get("/api/contributions")
def contributions(s:Session=Depends(db)):
    # Contribution is the authoritative economic ledger; Movement is the operational mirror.
    rows=s.query(Contribution).order_by(Contribution.movement_date.desc(),Contribution.id.desc()).all()
    partners={p.id:p.name for p in s.query(Partner).all()}
    return [{"id":c.id,"date":c.movement_date,"period":c.period,"partner_id":c.partner_id,"partner":partners.get(c.partner_id),
             "ab":c.ab,"amount_ars":c.amount_ars,"type":c.type,"concept":c.concept,"source":c.source} for c in rows]

@app.post("/api/contributions")
def add_contribution(x:ContributionIn,request:Request,s:Session=Depends(db)):
    _require_role(request,"editor")
    if x.ab not in ("A","B"): raise HTTPException(400,"A/B inválido")
    if x.movement_type not in ("devengado","efectivo"): raise HTTPException(400,"Tipo inválido")
    if x.amount_ars <= 0: raise HTTPException(400,"El importe debe ser mayor a cero")
    if not s.get(Partner,x.partner_id): raise HTTPException(400,"Socio inexistente")
    period=x.date.strftime("%Y-%m")
    closed=s.query(MonthlyClose).filter_by(period=period,status="closed").first()
    if closed: raise HTTPException(409,f"El período {period} está cerrado; registre una corrección")
    m=Movement(date=x.date,concept=x.concept or x.movement_type,movement_type=x.movement_type,
               partner_id=x.partner_id,ab=x.ab,amount_ars=x.amount_ars,
               created_at=datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),source="manual")
    c=Contribution(partner_id=x.partner_id,period=period,ab=x.ab,type=x.movement_type,
                   amount_ars=x.amount_ars,source="manual",created_at=datetime.now(timezone.utc).replace(tzinfo=None).isoformat())
    s.add(m); s.add(c); s.flush()
    s.add(AuditEvent(entity="contribution",entity_id=c.id,action="create",actor="admin",
                     created_at=datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),reason=x.concept or x.movement_type))
    s.commit();s.refresh(c)
    return {"id":c.id,"period":period}


class ContributionCorrectionIn(BaseModel):
    amount_ars: float | None = None
    ab: str | None = None
    date: str | None = None
    concept: str | None = None
    reason: str

@app.post("/api/contributions/{contribution_id}/correct")
def correct_contribution(contribution_id:int, x:ContributionCorrectionIn, request:Request, s:Session=Depends(db)):
    """Correct a contribution without mutating the historical record."""
    _require_role(request,"editor")
    original=s.get(Contribution,contribution_id)
    if not original: raise HTTPException(404,"Aporte inexistente")
    if not x.reason.strip(): raise HTTPException(400,"El motivo de corrección es obligatorio")
    new_date=date.fromisoformat(x.date) if x.date else (date.fromisoformat(original.period+"-01") if original.period else None)
    if new_date is None: raise HTTPException(400,"No se pudo determinar la fecha")
    period=new_date.strftime("%Y-%m")
    if s.query(MonthlyClose).filter_by(period=period,status="closed").first():
        raise HTTPException(409,f"El período {period} está cerrado")
    new_amount=original.amount_ars if x.amount_ars is None else x.amount_ars
    new_ab=original.ab if x.ab is None else x.ab
    if new_amount<=0: raise HTTPException(400,"El importe debe ser mayor a cero")
    if new_ab not in ("A","B"): raise HTTPException(400,"A/B inválido")
    corrected=Contribution(partner_id=original.partner_id,period=period,ab=new_ab,type=original.type,
                           amount_ars=new_amount,source="correction",source_row=original.source_row,
                           created_at=datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),correction_of_id=original.id)
    s.add(corrected); s.flush()
    s.add(AuditEvent(entity="contribution",entity_id=corrected.id,action="correct",actor="admin",
                     created_at=datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),reason=x.reason.strip(),
                     old_value=json.dumps({"id":original.id,"period":original.period,"ab":original.ab,"amount_ars":original.amount_ars},ensure_ascii=False),
                     new_value=json.dumps({"id":corrected.id,"period":corrected.period,"ab":corrected.ab,"amount_ars":corrected.amount_ars},ensure_ascii=False)))
    s.commit(); s.refresh(corrected)
    return {"status":"corrected","original_id":original.id,"correction_id":corrected.id,"period":corrected.period}

@app.get("/api/audit/contribution/{contribution_id}")
def contribution_audit(contribution_id:int, request:Request, s:Session=Depends(db)):
    _require_role(request,"viewer")
    ids={contribution_id}
    root=s.get(Contribution,contribution_id)
    if root and root.correction_of_id: ids.add(root.correction_of_id)
    rows=s.query(Contribution).filter((Contribution.id.in_(ids)) | (Contribution.correction_of_id.in_(ids))).order_by(Contribution.id).all()
    events=s.query(AuditEvent).filter_by(entity="contribution").filter(AuditEvent.entity_id.in_([r.id for r in rows])).order_by(AuditEvent.id).all()
    return {"records":[{"id":r.id,"period":r.period,"ab":r.ab,"type":r.type,"amount_ars":r.amount_ars,"source":r.source,"correction_of_id":r.correction_of_id} for r in rows],
            "events":[{"id":e.id,"action":e.action,"reason":e.reason,"actor":e.actor,"created_at":e.created_at,"old_value":e.old_value,"new_value":e.new_value} for e in events]}

@app.get("/api/partner/{partner_id}/summary")
def partner_summary(partner_id:int,s:Session=Depends(db)):
    p=s.get(Partner,partner_id)
    if not p: raise HTTPException(404,"Socio inexistente")
    dev=s.query(func.coalesce(func.sum(Contribution.amount_ars),0)).filter_by(partner_id=partner_id,type="devengado").scalar() or 0
    eff=s.query(func.coalesce(func.sum(Contribution.amount_ars),0)).filter_by(partner_id=partner_id,type="efectivo").scalar() or 0
    return {"partner":p.name,"devengado_ars":dev,"efectivo_ars":eff,"pending_ars":dev-eff,
            "fulfilled":min(1,eff/dev) if dev else 0}

@app.get("/api/contributions/monthly")
def contributions_monthly(period:str|None=None,s:Session=Depends(db)):
    q=s.query(Contribution)
    if period: q=q.filter_by(period=period)
    partners_map={p.id:p.name for p in s.query(Partner)}
    rows={}
    for c in q.all():
        key=(c.period,c.partner_id)
        rows.setdefault(key,{"period":c.period,"partner_id":c.partner_id,"partner":partners_map.get(c.partner_id),"devengado_ars":0,"efectivo_ars":0})
        rows[key][c.type+"_ars"]+=c.amount_ars
    out=[]
    for x in rows.values():
        x["pending_ars"]=x["devengado_ars"]-x["efectivo_ars"]
        out.append(x)
    return sorted(out,key=lambda x:(x["period"],x["partner"]))

@app.get("/api/contributions/by-ab")
def contributions_by_ab(period:str|None=None,s:Session=Depends(db)):
    q=s.query(Contribution)
    if period: q=q.filter_by(period=period)
    out={}
    for c in q.all():
        key=(c.period,c.ab or "SIN_AB")
        out.setdefault(key,{"period":c.period,"ab":c.ab or "SIN_AB","devengado_ars":0,"efectivo_ars":0})
        out[key][c.type+"_ars"]+=c.amount_ars
    for x in out.values(): x["pending_ars"]=x["devengado_ars"]-x["efectivo_ars"]
    return sorted(out.values(),key=lambda x:(x["period"],x["ab"]))

@app.get("/api/contributions/reconciliation")
def contributions_reconciliation(s:Session=Depends(db)):
    out=[]
    for p in s.query(Partner).order_by(Partner.name):
        dev=s.query(func.coalesce(func.sum(Contribution.amount_ars),0)).filter_by(partner_id=p.id,type="devengado").scalar() or 0
        eff=s.query(func.coalesce(func.sum(Contribution.amount_ars),0)).filter_by(partner_id=p.id,type="efectivo").scalar() or 0
        out.append({"partner_id":p.id,"partner":p.name,"master_devengado_ars":p.devengado_ars,
                    "ledger_devengado_ars":dev,"delta_devengado_ars":dev-p.devengado_ars,
                    "master_efectivo_ars":p.efectivo_ars,"ledger_efectivo_ars":eff,
                    "delta_efectivo_ars":eff-p.efectivo_ars,
                    "ok":abs(dev-p.devengado_ars)<0.01 and abs(eff-p.efectivo_ars)<0.01})
    return {"partners":out,"ok":all(x["ok"] for x in out)}

@app.get("/api/close/check")
def close_check(period:str,s:Session=Depends(db)):
    # A month is ready only when the essential parameters exist and data integrity checks pass.
    par=s.query(Param).filter_by(period=period).first()
    if not par: return {"period":period,"ready":False,"checks":[{"name":"CAC/TC del período","ok":False,"detail":"Falta parámetro"}]}
    ex=s.query(Expense).filter(Expense.period==period).all()
    missing=[e.id for e in ex if not e.supplier or e.ars_historical<=0 or e.ab not in ("A","B")]
    controls=controls_internal(s,period)
    return {"period":period,"ready":all(x["ok"] for x in controls),"checks":controls,"expenses":len(ex),"invalid_expenses":missing}

@app.post("/api/close/{period}/close")
def close_period(period:str,request:Request,s:Session=Depends(db)):
    identity=_require_role(request,"admin")
    actor=identity["user"]
    if not __import__('re').fullmatch(r"\d{4}-\d{2}",period):
        raise HTTPException(400,"Período inválido. Use YYYY-MM")
    existing=s.query(MonthlyClose).filter_by(period=period).first()
    if existing and existing.status=="closed":
        raise HTTPException(409,f"El período {period} ya está cerrado")
    checks=controls_internal(s,period)
    failed=[x for x in checks if not x["ok"]]
    if failed:
        raise HTTPException(400,{"message":"El período no supera los controles","checks":checks})
    # Snapshot is the immutable evidence of exactly what was closed.
    import json as _json
    dev=s.query(func.coalesce(func.sum(Contribution.amount_ars),0)).filter_by(period=period,type="devengado").scalar() or 0
    eff=s.query(func.coalesce(func.sum(Contribution.amount_ars),0)).filter_by(period=period,type="efectivo").scalar() or 0
    exp=s.query(func.coalesce(func.sum(Expense.ars_historical),0)).filter(Expense.period==period).scalar() or 0
    payload={"period":period,"devengado_ars":dev,"efectivo_ars":eff,"pending_ars":dev-eff,"expenses_ars":exp,"checks":checks}
    if not existing:
        existing=MonthlyClose(period=period)
        s.add(existing); s.flush()
    existing.status="closed"; existing.closed_at=datetime.now(timezone.utc).replace(tzinfo=None).isoformat(); existing.closed_by=actor
    snap=CloseSnapshot(period=period,created_at=datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),created_by=actor,payload=_json.dumps(payload,ensure_ascii=False,sort_keys=True))
    s.add(snap); s.flush()
    s.add(AuditEvent(entity="monthly_close",entity_id=existing.id,action="close",actor=actor,created_at=datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),reason=f"Cierre {period}",new_value=_json.dumps(payload,ensure_ascii=False,sort_keys=True)))
    s.commit()
    return {"period":period,"status":"closed","snapshot_id":snap.id,"snapshot":payload}

@app.get("/api/close/{period}")
def close_status(period:str,s:Session=Depends(db)):
    row=s.query(MonthlyClose).filter_by(period=period).first()
    snap=s.query(CloseSnapshot).filter_by(period=period).first()
    import json as _json
    return {"period":period,"status":row.status if row else "open","closed_at":row.closed_at if row else None,"closed_by":row.closed_by if row else None,
            "snapshot":(_json.loads(snap.payload) if snap else None),"snapshot_id":snap.id if snap else None}

@app.get("/api/close/{period}/checks")
def close_checks(period:str,request:Request,s:Session=Depends(db)):
    _require_role(request,"viewer")
    row=s.query(MonthlyClose).filter_by(period=period).first()
    return {"period":period,"status":row.status if row else "open","checks":controls_internal(s,period)}

def contribution_reconciliation_internal(s):
    bad=[]
    for p in s.query(Partner):
        dev=s.query(func.coalesce(func.sum(Contribution.amount_ars),0)).filter_by(partner_id=p.id,type="devengado").scalar() or 0
        eff=s.query(func.coalesce(func.sum(Contribution.amount_ars),0)).filter_by(partner_id=p.id,type="efectivo").scalar() or 0
        if abs(dev-p.devengado_ars)>=0.01 or abs(eff-p.efectivo_ars)>=0.01: bad.append(p.name)
    return {"ok":not bad,"detail":"Todos los socios concilian" if not bad else "Diferencias: "+", ".join(bad)}

def controls_internal(s,period=None):
    p=s.query(Project).first(); units=s.query(Unit).all()
    period_ok=True if period is None else s.query(Param).filter_by(period=period).first() is not None
    total_part=sum((u.participation or 0) for u in units)
    checks=[
      {"name":"CAC actual","ok":bool(p and p.current_cac and p.current_cac>0),"detail":str(p.current_cac if p else None)},
      {"name":"TC actual","ok":bool(p and p.current_tc and p.current_tc>0),"detail":str(p.current_tc if p else None)},
      {"name":"29 unidades","ok":len(units)==29,"detail":str(len(units))},
      {"name":"Participaciones definidas","ok":all(u.participation is not None for u in units),"detail":f"{sum(u.participation is not None for u in units)}/{len(units)} unidades con % definido; suma {total_part:.4%}"},
      {"name":"CAC/TC del período","ok":period_ok,"detail":period or "global"},
    ]
    if period:
        q=s.query(Contribution).filter_by(period=period)
        bad_contrib=sum(1 for c in q.all() if c.amount_ars<=0 or c.ab not in ("A","B") or c.type not in ("devengado","efectivo"))
        checks.append({"name":"Aportes del período","ok":q.count()>0 and bad_contrib==0,"detail":f"{q.count()} movimientos; inválidos: {bad_contrib}"})
        exq=s.query(Expense).filter(Expense.period==period)
        bad_exp=sum(1 for e in exq.all() if not e.supplier or e.ars_historical<=0 or e.ab not in ("A","B"))
        checks.append({"name":"Gastos del período","ok":bad_exp==0,"detail":f"{exq.count()} registros; inválidos: {bad_exp}"})
    else:
        rec=contribution_reconciliation_internal(s)
        checks.append({"name":"Conciliación aportes","ok":rec["ok"],"detail":rec["detail"]})
    return checks

@app.get("/api/audit")
def audit(s:Session=Depends(db)):
    # Immutable-event style audit feed: every manually created record is visible with timestamp/source.
    events=[]
    for e in s.query(Expense).filter_by(source="manual").order_by(Expense.id.desc()):
        events.append({"date":e.created_at,"entity":"expense","id":e.id,"action":"create","source":e.source})
    for m in s.query(Movement).filter_by(source="manual").order_by(Movement.id.desc()):
        events.append({"date":m.created_at,"entity":"movement","id":m.id,"action":"create","source":m.source})
    for a in s.query(BudgetAdjustment).order_by(BudgetAdjustment.id.desc()):
        events.append({"date":a.created_at,"entity":"budget","id":a.id,"action":"adjust","source":"manual"})
    return events


class ExpenseCorrectionIn(BaseModel):
    corrected_ars_historical:float
    reason:str

@app.post("/api/expenses/{expense_id}/correct")
def correct_expense(expense_id:int,x:ExpenseCorrectionIn,request:Request,s:Session=Depends(db)):
    _require_role(request,"editor")
    e=s.get(Expense,expense_id)
    if not e: raise HTTPException(404,"Gasto inexistente")
    if not x.reason.strip(): raise HTTPException(400,"El motivo es obligatorio")
    ne=Expense(source_row=e.source_row,supplier=e.supplier,date=e.date,period=e.period,ab=e.ab,
               ars_historical=x.corrected_ars_historical,created_at=datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
               source="correction",corrected_from_id=e.id)
    s.add(ne); s.flush()
    s.add(AuditEvent(entity="expense",entity_id=ne.id,action="correct",actor=_auth(request)["user"],created_at=datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),reason=x.reason.strip(),old_value=json.dumps({"id":e.id,"ars_historical":e.ars_historical}),new_value=json.dumps({"id":ne.id,"ars_historical":ne.ars_historical})))
    s.commit();s.refresh(ne)
    return {"id":ne.id,"corrected_from_id":e.id}

@app.get("/api/periods")
def periods(s:Session=Depends(db)):
    vals=sorted(set(p.period for p in s.query(Param)),reverse=True)
    return vals


@app.get("/api/reports/economic-periods")
def economic_periods(s:Session=Depends(db)):
    p=s.query(Project).first()
    periods=sorted(set([x.period for x in s.query(Contribution.period).all()] + [x.period for x in s.query(Expense.period).all() if x.period]), reverse=False)
    out=[]
    for per in periods:
        par=s.query(Param).filter_by(period=per).first()
        dev=s.query(func.coalesce(func.sum(Contribution.amount_ars),0)).filter_by(period=per,type="devengado").scalar() or 0
        eff=s.query(func.coalesce(func.sum(Contribution.amount_ars),0)).filter_by(period=per,type="efectivo").scalar() or 0
        ex=s.query(Expense).filter_by(period=per).all()
        expense_hist=sum(e.ars_historical or 0 for e in ex)
        expense_cac=(sum(calc_exp(e,par,p)["ars_cac"] or 0 for e in ex) if par and par.cac else None)
        expense_usd=(sum(calc_exp(e,par,p)["usd_current"] or 0 for e in ex) if par and par.cac and par.tc else None)
        dev_usd_hist=(dev/par.tc if par and par.tc else None)
        eff_usd_hist=(eff/par.tc if par and par.tc else None)
        dev_usd_current=(dev*p.current_cac/par.cac/p.current_tc if par and par.cac and par.tc else None)
        eff_usd_current=(eff*p.current_cac/par.cac/p.current_tc if par and par.cac and par.tc else None)
        out.append({"period":per,"cac":par.cac if par else None,"tc":par.tc if par else None,
                    "devengado_ars":dev,"efectivo_ars":eff,"pending_ars":dev-eff,
                    "devengado_usd_historical":dev_usd_hist,"efectivo_usd_historical":eff_usd_hist,
                    "devengado_usd_current":dev_usd_current,"efectivo_usd_current":eff_usd_current,
                    "expenses_ars_historical":expense_hist,"expenses_ars_cac":expense_cac,"expenses_usd_current":expense_usd,
                    "close_status":(s.query(MonthlyClose).filter_by(period=per).first().status if s.query(MonthlyClose).filter_by(period=per).first() else "open")})
    return out


@app.get("/api/reports/dashboard-series")
def dashboard_series(s:Session=Depends(db)):
    """Time-series used by the executive dashboard. All values are calculated from persisted records."""
    project=s.query(Project).first()
    periods=sorted(set([x.period for x in s.query(Contribution.period).all()] + [x.period for x in s.query(Expense.period).all() if x.period]))
    out=[]
    cum_dev=cum_eff=cum_exp=0.0
    for per in periods:
        par=s.query(Param).filter_by(period=per).first()
        dev=s.query(func.coalesce(func.sum(Contribution.amount_ars),0)).filter_by(period=per,type="devengado").scalar() or 0
        eff=s.query(func.coalesce(func.sum(Contribution.amount_ars),0)).filter_by(period=per,type="efectivo").scalar() or 0
        ex=s.query(Expense).filter_by(period=per).all()
        exp_hist=sum(e.ars_historical or 0 for e in ex)
        exp_cur=sum((calc_exp(e,par,p)["usd_current"] or 0) for e in ex) if par and par.cac and par.tc else None
        cum_dev+=dev; cum_eff+=eff
        if exp_cur is not None: cum_exp+=exp_cur
        out.append({"period":per,"devengado_ars":dev,"efectivo_ars":eff,
                    "pending_ars":dev-eff,"cum_devengado_ars":cum_dev,"cum_efectivo_ars":cum_eff,
                    "expenses_ars_historical":exp_hist,"expenses_usd_current":exp_cur,
                    "cum_expenses_usd_current":cum_exp if exp_cur is not None else None,
                    "cac":par.cac if par else None,"tc":par.tc if par else None,
                    "close_status":(s.query(MonthlyClose).filter_by(period=per).first().status if s.query(MonthlyClose).filter_by(period=per).first() else "open")})
    return {"current_cac":project.current_cac,"current_tc":project.current_tc,"series":out}

@app.get("/api/economic/summary")
def economic_summary(s:Session=Depends(db)):
    """Single source of truth for the economic engine: historical, CAC-adjusted and USD views."""
    p=s.query(Project).first()
    if not p: raise HTTPException(404,"Proyecto inexistente")
    # Current parameters are explicit project parameters; historical parameters are period-specific.
    params={x.period:x for x in s.query(Param).all()}
    dev_rows=s.query(Contribution).filter_by(type="devengado").all()
    eff_rows=s.query(Contribution).filter_by(type="efectivo").all()
    dev_hist=sum(x.amount_ars for x in dev_rows)
    eff_hist=sum(x.amount_ars for x in eff_rows)
    def convert(rows):
        hist=sum(x.amount_ars for x in rows)
        adj=0.0; usd_hist=0.0; usd_current=0.0; missing=[]
        for x in rows:
            par=params.get(x.period)
            if not par or not par.cac or not par.tc:
                missing.append(x.period); continue
            adj += x.amount_ars * p.current_cac / par.cac
            usd_hist += x.amount_ars / par.tc
            usd_current += (x.amount_ars * p.current_cac / par.cac) / p.current_tc
        return {"ars_historical":hist,"ars_cac_current":adj,"usd_historical":usd_hist,
                "usd_current":usd_current,"periods_missing_parameters":sorted(set(missing))}
    dev=convert(dev_rows); eff=convert(eff_rows)
    pending={k:dev[k]-eff[k] for k in ("ars_historical","ars_cac_current","usd_historical","usd_current")}
    expenses=[]
    for e in s.query(Expense).all():
        par=params.get(e.period)
        if par and par.cac and par.tc:
            expenses.append(calc_exp(e,par,p))
    expense_usd_current=sum(x["usd_current"] or 0 for x in expenses)
    budget_adjustments=s.query(func.coalesce(func.sum(BudgetAdjustment.amount_usd),0)).scalar() or 0
    budget_remaining=p.budget_remaining_usd-budget_adjustments-expense_usd_current
    progress=p.updated_investment_usd/(p.updated_investment_usd+budget_remaining) if p.updated_investment_usd+budget_remaining else None
    return {"parameters":{"current_cac":p.current_cac,"current_tc":p.current_tc},
            "investment":{"historical_ars":p.historical_investment_ars,"historical_usd":p.historical_investment_usd,
                           "updated_ars":p.updated_investment_ars,"updated_usd":p.updated_investment_usd},
            "contributions":{"devengado":dev,"efectivo":eff,"pending":pending},
            "expenses":{"usd_current":expense_usd_current,"count":s.query(Expense).count()},
            "budget":{"base_remaining_usd":p.budget_remaining_usd,"manual_adjustments_usd":budget_adjustments,
                       "operational_remaining_usd":budget_remaining},
            "progress":{"economic":progress,"cost_per_weighted_m2":p.updated_investment_usd/p.weighted_m2 if p.weighted_m2 else None}}

@app.get("/api/reports/executive")
def executive_report(s:Session=Depends(db)):
    """Executive report combining project, partner, unit and monthly economic views."""
    eco=economic_summary(s)
    monthly=economic_periods(s)
    by_partner=[]
    for partner in s.query(Partner).order_by(Partner.name):
        dev=sum(x.amount_ars for x in s.query(Contribution).filter_by(partner_id=partner.id,type="devengado").all())
        eff=sum(x.amount_ars for x in s.query(Contribution).filter_by(partner_id=partner.id,type="efectivo").all())
        by_partner.append({"id":partner.id,"name":partner.name,"participation":partner.participation,
                           "devengado_ars":dev,"efectivo_ars":eff,"pending_ars":dev-eff,
                           "fulfilled":min(1,eff/dev) if dev else 0})
    return {"project":"Torre Faro","generated_at":datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),"economic":eco,
            "partners":by_partner,"units":units_report(s),"monthly":monthly}

@app.get("/api/reports/financial")
def financial_report(s:Session=Depends(db)):
    p=s.query(Project).first()
    partners=s.query(Partner).all()
    units=s.query(Unit).all()
    dev=sum((s.query(func.coalesce(func.sum(Contribution.amount_ars),0)).filter_by(partner_id=x.id,type="devengado").scalar() or 0) for x in partners)
    eff=sum((s.query(func.coalesce(func.sum(Contribution.amount_ars),0)).filter_by(partner_id=x.id,type="efectivo").scalar() or 0) for x in partners)
    b=dashboard(None, s)
    return {
      "investment":{"historical_usd":p.historical_investment_usd,"updated_usd":p.updated_investment_usd},
      "contributions":{"devengado_ars":dev,"efectivo_ars":eff,"pending_ars":dev-eff,
                       "fulfilled":min(1,eff/dev) if dev else 0},
      "budget":{"remaining_usd":b["budget_remaining_usd"]},
      "progress":{"economic":b["progress"]},
      "units":{"count":len(units),"weighted_m2":p.weighted_m2,"cost_per_weighted_m2":b["cost_m2"]},
      "partners":[{"name":x.name,"participation":x.participation,
                   "devengado_ars":(s.query(func.coalesce(func.sum(Contribution.amount_ars),0)).filter_by(partner_id=x.id,type="devengado").scalar() or 0),
                   "efectivo_ars":(s.query(func.coalesce(func.sum(Contribution.amount_ars),0)).filter_by(partner_id=x.id,type="efectivo").scalar() or 0)} for x in partners]
    }

@app.get("/api/reports/units")
def units_report(s:Session=Depends(db)):
    return units(s)

class QueryIn(BaseModel):
    question:str

@app.post("/api/ai/query")
def controlled_query(x:QueryIn,s:Session=Depends(db)):
    q=x.question.lower().strip()
    p=s.query(Project).first()
    partners=s.query(Partner).all()
    units_all=s.query(Unit).all()
    if "cuánto" in q or "cuanto" in q:
        if "m²" in q or "m2" in q:
            return {"answer":f"El costo actual por m² ponderado es USD {p.updated_investment_usd/p.weighted_m2:,.0f}.",
                    "metric":"cost_m2","value":p.updated_investment_usd/p.weighted_m2}
        if "falta invertir" in q or "presupuesto" in q:
            b=dashboard(None, s); return {"answer":f"El presupuesto restante operativo es USD {b['budget_remaining_usd']:,.0f}.",
                                      "metric":"budget_remaining","value":b["budget_remaining_usd"]}
        if "invertido" in q or "inversión" in q or "inversion" in q:
            return {"answer":f"La inversión actualizada es USD {p.updated_investment_usd:,.0f}.",
                    "metric":"updated_investment","value":p.updated_investment_usd}
        for partner in partners:
            if partner.name.lower() in q:
                pending=partner.devengado_ars-partner.efectivo_ars
                return {"answer":f"A {partner.name} le resta aportar ARS {pending:,.0f}.",
                        "metric":"partner_pending","value":pending,"partner":partner.name}
        for u in units_all:
            if u.code.lower() in q:
                value=(p.updated_investment_usd*u.participation if u.participation is not None else None)
                return {"answer":(f"La inversión actualizada asignada a la unidad {u.code} es USD {value:,.0f}." if value is not None else f"La unidad {u.code} no tiene participación definida en la fuente maestra."),
                        "metric":"unit_investment","value":value,"unit":u.code}
    if "socios" in q:
        return {"answer":"Hay 8 socios registrados.","metric":"partners","value":len(partners)}
    if "unidades" in q or "departamentos" in q:
        return {"answer":"Hay 29 unidades operativas registradas.","metric":"units","value":len(units_all)}
    return {"answer":"No encontré una métrica segura para esa consulta. Usá inversión, presupuesto, m², socio o unidad.","metric":None,"value":None}

@app.get("/api/summary")
def summary(s:Session=Depends(db)):
    p=s.query(Project).first()
    partners=s.query(Partner).all()
    units=s.query(Unit).all()
    dev=sum((s.query(func.coalesce(func.sum(Contribution.amount_ars),0)).filter_by(partner_id=x.id,type="devengado").scalar() or 0) for x in partners)
    eff=sum((s.query(func.coalesce(func.sum(Contribution.amount_ars),0)).filter_by(partner_id=x.id,type="efectivo").scalar() or 0) for x in partners)
    return {"project":p.name,"partners":len(partners),"units":len(units),
            "devengado_ars":dev,"efectivo_ars":eff,"pending_ars":dev-eff,
            "updated_usd":p.updated_investment_usd,"budget_remaining_usd":p.budget_remaining_usd}

class ExpenseIn(BaseModel):
    supplier:str; date:date; ab:str; ars_historical:float

@app.get("/api/expenses")
def expenses(s:Session=Depends(db),q:str=""):
    es=s.query(Expense).order_by(Expense.date.desc(),Expense.id.desc()).all()
    out=[]
    for e in es:
        if q and q.lower() not in e.supplier.lower(): continue
        par=s.query(Param).filter_by(period=e.period).first()
        x=calc_exp(e,par)
        out.append({"id":e.id,"supplier":e.supplier,"date":e.date,"period":e.period,"ab":e.ab,"ars_historical":e.ars_historical,**x,"source":e.source})
    return out

@app.post("/api/expenses")
def add_expense(x:ExpenseIn,request:Request,s:Session=Depends(db)):
    _require_role(request,"editor")
    if x.ab not in ("A","B"): raise HTTPException(400,"A/B inválido")
    period=x.date.strftime("%Y-%m")
    if not s.query(Param).filter_by(period=period).first(): raise HTTPException(400,"Falta CAC/TC para el período")
    e=Expense(source_row=None,supplier=x.supplier,date=x.date,period=period,ab=x.ab,ars_historical=x.ars_historical,created_at=datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),source="manual")
    s.add(e); s.flush()
    s.add(AuditEvent(entity="expense",entity_id=e.id,action="create",actor=_auth(request)["user"],created_at=datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),reason="Carga manual",new_value=json.dumps({"supplier":e.supplier,"date":e.date.isoformat(),"ab":e.ab,"ars_historical":e.ars_historical})))
    s.commit();s.refresh(e)
    return {"id":e.id}

class AdjustmentIn(BaseModel):
    amount_usd:float; reason:str

@app.get("/api/budget")
def budget(s:Session=Depends(db)):
    p=s.query(Project).first()
    ad=s.query(func.coalesce(func.sum(BudgetAdjustment.amount_usd),0)).scalar() or 0
    new=0
    for e in s.query(Expense).filter_by(source="manual"):
        par=s.query(Param).filter_by(period=e.period).first(); new+=calc_exp(e,par,p)["usd_current"] or 0
    return {"base_usd":p.budget_remaining_usd,"manual_expenses_usd":new,"adjustments_usd":ad,"current_usd":p.budget_remaining_usd-new+ad,
            "history":[{"date":a.date,"amount_usd":a.amount_usd,"reason":a.reason} for a in s.query(BudgetAdjustment).order_by(BudgetAdjustment.id.desc())]}

@app.post("/api/budget/adjustments")
def add_adjustment(x:AdjustmentIn,request:Request,s:Session=Depends(db)):
    identity=_require_role(request,"admin")
    if not x.reason.strip(): raise HTTPException(400,"El motivo es obligatorio")
    a=BudgetAdjustment(date=date.today(),amount_usd=x.amount_usd,reason=x.reason,created_at=datetime.now(timezone.utc).replace(tzinfo=None).isoformat())
    s.add(a); s.flush()
    s.add(AuditEvent(entity="budget",entity_id=a.id,action="adjust",actor=identity["user"],created_at=datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),reason=x.reason.strip(),new_value=json.dumps({"amount_usd":x.amount_usd})))
    s.commit();return {"id":a.id}

@app.get("/api/parameters")
def parameters(s:Session=Depends(db)):
    return [{"period":p.period,"cac":p.cac,"tc":p.tc} for p in s.query(Param).order_by(Param.period.desc())]

class ParamIn(BaseModel):
    period:str;cac:float;tc:float

@app.post("/api/parameters")
def set_parameter(x:ParamIn,request:Request,s:Session=Depends(db)):
    identity=_require_role(request,"admin")
    if x.cac<=0 or x.tc<=0: raise HTTPException(400,"CAC y TC deben ser mayores a cero")
    p=s.query(Param).filter_by(period=x.period).first()
    old={"cac":p.cac,"tc":p.tc} if p else None
    if p: p.cac=x.cac;p.tc=x.tc
    else: s.add(Param(period=x.period,cac=x.cac,tc=x.tc))
    s.flush()
    s.add(AuditEvent(entity="parameter",entity_id=p.id if p else None,action="upsert",actor=identity["user"],created_at=datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),reason=f"Actualización de parámetros {x.period}",old_value=json.dumps(old),new_value=json.dumps({"cac":x.cac,"tc":x.tc})))
    s.commit();return {"ok":True}

@app.get("/api/movements")
def movements(s:Session=Depends(db)):
    return [{"id":m.id,"date":m.date,"concept":m.concept,"type":m.movement_type,"ab":m.ab,"amount_ars":m.amount_ars} for m in s.query(Movement).order_by(Movement.date.desc(),Movement.id.desc()).all()]

@app.get("/api/controls")
def controls(s:Session=Depends(db)):
    out=controls_internal(s)
    ex=s.query(Expense).all()
    missing=sum(1 for e in ex if not s.query(Param).filter_by(period=e.period).first())
    out.append({"name":"Gastos con CAC/TC","ok":missing==0,"detail":f"{missing} observaciones"})
    norma=next((x for x in s.query(Partner) if x.name=="Norma Neif"),None)
    bad=bool(norma and norma.efectivo_ars>norma.devengado_ars)
    out.append({"name":"Control socio Norma Neif","ok":not bad,"detail":"Efectivo supera devengado; revisar" if bad else "OK"})
    dev=s.query(func.coalesce(func.sum(Contribution.amount_ars),0)).filter_by(type="devengado").scalar() or 0
    eff=s.query(func.coalesce(func.sum(Contribution.amount_ars),0)).filter_by(type="efectivo").scalar() or 0
    out.append({"name":"Aportes históricos cargados","ok":dev>0 and eff>0,"detail":f"Devengado ARS {dev:,.0f} / Efectivo ARS {eff:,.0f}"})
    return out
