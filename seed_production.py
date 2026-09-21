"""Seed a fresh PostgreSQL database from the canonical Torre Faro package.
Refuses to seed a non-empty database unless --force is explicitly supplied.
"""
import argparse, csv, json
from datetime import date
from pathlib import Path
from sqlalchemy import create_engine, text
from app.main import Base, DB_URL, SessionLocal, Project, Partner, Unit, Expense, Param, Movement, Contribution

ROOT=Path(__file__).resolve().parent
parser=argparse.ArgumentParser(); parser.add_argument("--force",action="store_true"); args=parser.parse_args()
engine=create_engine(DB_URL, pool_pre_ping=True)
Base.metadata.create_all(engine)
s=SessionLocal()
try:
    existing=s.execute(text("SELECT COUNT(*) FROM partners")).scalar_one()
    if existing and not args.force:
        raise SystemExit(f"Base no vacía ({existing} socios). No se siembra; usar --force solo si corresponde.")
    if args.force:
        for model in (Contribution, Movement, Expense, Param, Unit, Partner, Project): s.query(model).delete()
        s.commit()

    project=json.loads((ROOT/"data/project.json").read_text())
    s.add(Project(id=1, name=project.get("name","Torre Faro"),
        historical_investment_ars=project.get("historical_investment_ars"), historical_investment_usd=project.get("historical_investment_usd"),
        updated_investment_ars=project.get("updated_investment_ars"), updated_investment_usd=project.get("updated_investment_usd"),
        current_cac=project.get("current_cac"), current_tc=project.get("current_tc"), budget_remaining_usd=project.get("budget_remaining_usd"),
        weighted_m2=project.get("weighted_m2"), a_share=project.get("a_share"), b_share=project.get("b_share"), delivery=date.fromisoformat(project["delivery"]) if project.get("delivery") else None))

    partners=json.loads((ROOT/"data/socios.json").read_text())
    partner_by_name={}
    for i,row in enumerate(partners,1):
        obj=Partner(id=i, name=row.get("name") or row.get("socio") or f"Socio {i}", devengado_ars=float(row.get("devengado_ars",0) or 0), efectivo_ars=float(row.get("efectivo_ars",0) or 0), participation=float(row.get("participation",0) or 0))
        s.add(obj); partner_by_name[obj.name.strip().upper()]=i

    units=json.loads((ROOT/"data/units.json").read_text())
    for i,row in enumerate(units,1):
        s.add(Unit(id=i, code=str(row.get("code") or row.get("unit") or row.get("denom") or i), floor=row.get("floor"), type=row.get("type") or row.get("kind"), denom=row.get("denom"), covered_m2=float(row.get("covered_m2",0) or 0), semi_m2=float(row.get("semi_m2",0) or 0), total_m2=float(row.get("total_m2",0) or 0), weighted_m2=float(row.get("weighted_m2",0) or 0), participation=float(row["participation"]) if row.get("participation") is not None else None))

    cac=json.loads((ROOT/"data/cac.json").read_text()); tc=json.loads((ROOT/"data/tc.json").read_text())
    for period,value in sorted(set(cac)|set(tc)):
        s.add(Param(period=period, cac=float(cac.get(period,0) or 0), tc=float(tc.get(period,0) or 0)))

    for row in json.loads((ROOT/"data/expenses.json").read_text()):
        s.add(Expense(source_row=row.get("source_row"), supplier=row.get("supplier"), date=date.fromisoformat(row["date"]) if row.get("date") else None, period=row.get("period"), ab=row.get("ab"), ars_historical=float(row.get("ars_historical",0) or 0), source="excel_import"))

    for row in json.loads((ROOT/"data/movements.json").read_text()):
        pname=(row.get("partner_name") or "").strip().upper(); s.add(Movement(source_row=row.get("source_row"), date=date.fromisoformat(row["date"]) if row.get("date") else None, concept=row.get("concept") or "Movimiento importado", movement_type="imported", partner_id=partner_by_name.get(pname), ab=row.get("ab"), amount_ars=float(row.get("amount_ars",0) or 0), source="excel_import"))

    for fname,typ in (("Torre_Faro_devengados_normalizados.csv","devengado"),("Torre_Faro_efectivos_normalizados.csv","efectivo")):
        with open(ROOT/"data"/fname,encoding="utf-8-sig",newline="") as fh:
            for row in csv.DictReader(fh):
                pname=row["socio_cuenta"].strip().upper(); period=row["periodo"].strip()
                # Normalize Spanish month labels to YYYY-MM using the source month table.
                months={"ene.":1,"feb.":2,"mar.":3,"abr.":4,"may.":5,"jun.":6,"jul.":7,"ago.":8,"sep.":9,"oct.":10,"nov.":11,"dic.":12}
                bits=period.split(); m=months.get(bits[0].lower(),0); year=int(bits[1]) if len(bits)>1 else 0
                if not m or not year: raise ValueError(f"Período inválido en {fname}: {period}")
                s.add(Contribution(partner_id=partner_by_name.get(pname) or 0, period=f"{year:04d}-{m:02d}", movement_date=None, ab=None, type=typ, amount_ars=float(row["importe"] or 0), source="excel_import"))
    s.commit()
    print("SEED OK: proyecto, 8 socios, 29 unidades, parámetros, gastos, movimientos y aportes cargados.")
finally:
    s.close()
