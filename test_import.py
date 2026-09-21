import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from app.main import _norm, _num, _find_col
import pandas as pd

def test_helpers():
    df=pd.DataFrame({'Proveedor':['X'],'Fecha':['2026-01-01'],'Importe':[100],'A/B':['A']})
    assert _find_col(df,['proveedor'])=='Proveedor'
    assert _find_col(df,['fecha'])=='Fecha'
    assert _num('100')==100
    assert _norm(' A ')=='a'
