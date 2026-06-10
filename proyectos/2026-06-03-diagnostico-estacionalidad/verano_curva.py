"""
Paso 2: curva de verano (estacionalidad limpia de eventos), 3 anos.

Cohorte estable de salas (abiertas los 3 anos) -> total semanal -> regresion
armonica con dummy de semana-evento (absorbe los spikes de evento para que NO
contaminen la curva estacional). Compara curva limpia vs cruda.

Read-only.
"""
from __future__ import annotations
import sys, os
from pathlib import Path
import datetime as dt
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

TZ = "America/Santiago"
K = 3
MESES = ["Ene","Feb","Mar","Abr","May","Jun","Jul","Ago","Sep","Oct","Nov","Dic"]

# fechas de evento (mismas de paso 1) para marcar semanas-evento
FIXED = [(1,1),(5,1),(5,21),(7,16),(8,15),(9,18),(9,19),(11,1),(12,8),(12,25),(10,31),(2,14)]
MOV = ["2023-04-07","2024-03-29","2025-04-18","2023-05-14","2024-05-12","2025-05-11",
       "2023-06-18","2024-06-16","2025-06-15"]
ev_dates = set()
for y in (2023,2024,2025):
    for m,d in FIXED:
        ev_dates.add(dt.date(y,m,d))
for s in MOV:
    ev_dates.add(dt.date.fromisoformat(s))
# ventana de evento: dia, vispera y 2 dias antes
ev_window = set()
for d in ev_dates:
    for off in (-2,-1,0):
        ev_window.add(d+dt.timedelta(days=off))

def wk_start(d):
    return d - dt.timedelta(days=d.weekday())

# ----------------------------------------------------------------------
o = OdooReader()
g = o.execute('pos.order','read_group',
  [('state','in',['paid','done','invoiced']),('date_order','>=','2023-01-01'),('date_order','<','2026-01-01')],
  ['amount_total:sum'],['crm_team_id','date_order:day'], lazy=False, context={'tz':TZ})
rows=[]
for r in g:
    t=r.get('crm_team_id')
    if not t: continue
    d=dt.date.fromisoformat(r['__range']['date_order:day']['from'][:10])
    rows.append((t[0], d, r.get('amount_total') or 0.0))
df=pd.DataFrame(rows, columns=["team","fecha","venta"])

# cohorte estable: con venta antes de jul-2023 Y despues de oct-2025
early = df[(df.fecha < dt.date(2023,7,1)) & (df.venta>0)]["team"].unique()
late  = df[(df.fecha > dt.date(2025,10,1)) & (df.venta>0)]["team"].unique()
cohort = sorted(set(early) & set(late))
print(f"cohorte estable: {len(cohort)} salas de {df.team.nunique()}")
dfc = df[df.team.isin(cohort)].copy()

# total semanal del cohorte
dfc["week"] = dfc["fecha"].map(wk_start)
wk = dfc.groupby("week")["venta"].sum().reset_index()
wk["is_event"] = wk["fecha_evento"] if False else wk["week"].map(
    lambda w: any((w + dt.timedelta(days=i)) in ev_window for i in range(7)))
# quitar semanas de borde con datos parciales (primera y ultima)
wk = wk[(wk["week"] >= dt.date(2023,5,15)) & (wk["week"] <= dt.date(2025,12,21))].reset_index(drop=True)
wk["iso_week"] = pd.to_datetime(wk["week"]).dt.isocalendar().week.astype(int).clip(upper=52)
wk["t"] = (pd.to_datetime(wk["week"]) - pd.to_datetime(wk["week"]).min()).dt.days / 365.0
print(f"semanas: {len(wk)}  evento: {wk.is_event.sum()}")

def design(iso_w, t, ev=None, k=K, trend=True):
    cols=[np.ones(len(t))]; names=["const"]
    if trend: cols.append(t); names.append("trend")
    for kk in range(1,k+1):
        cols.append(np.sin(2*np.pi*kk*iso_w/52)); names.append(f"sin{kk}")
        cols.append(np.cos(2*np.pi*kk*iso_w/52)); names.append(f"cos{kk}")
    if ev is not None:
        cols.append(ev.astype(float)); names.append("event")
    return np.column_stack(cols), names

y_log = np.log(wk["venta"].values)
isow = wk["iso_week"].values; t = wk["t"].values; ev = wk["is_event"].values

def curve_from(names, b):
    iw=np.arange(1,53)
    Xs,ns=design(iw, np.zeros(52), ev=None, trend=False)
    fi=[j for j,n in enumerate(ns) if n.startswith(("sin","cos"))]
    ci=[names.index(ns[j]) for j in fi]
    s=Xs[:,fi]@b[ci]; s-=s.mean()
    return np.exp(s)

# limpia: con dummy de evento
Xc,nc=design(isow,t,ev=ev); bc,*_=np.linalg.lstsq(Xc,y_log,rcond=None)
curve_clean=curve_from(nc,bc)
# cruda: sin dummy (eventos se cuelan a la curva)
Xr,nr=design(isow,t,ev=None); br,*_=np.linalg.lstsq(Xr,y_log,rcond=None)
curve_raw=curve_from(nr,br)

W2M={w:pd.Timestamp.fromisocalendar(2025,w,4).month for w in range(1,53)}
def to_month(curve):
    mf=np.array([np.mean([curve[w-1] for w in range(1,53) if W2M[w]==m]) for m in range(1,13)])
    return mf/mf.mean()
mc=to_month(curve_clean); mr=to_month(curve_raw)

print("\n"+"="*78)
print("CURVA DE VERANO - TOTAL CADENA (cohorte estable, 3 anos, base 100)")
print("="*78)
print(f"{'':6}"+"".join(f"{m:>6}" for m in MESES))
print("limpia"+"".join(f"{v*100:>6.0f}" for v in mc))
print("cruda "+"".join(f"{v*100:>6.0f}" for v in mr))
print("delta "+"".join(f"{(mr[i]-mc[i])*100:>+6.0f}" for i in range(12)))
print(f"\ntrend anual: {np.exp(bc[nc.index('trend')])-1:+.1%}")
print(f"event dummy (uplift medio semana-evento): {np.exp(bc[nc.index('event')])-1:+.1%}")
print(f"amplitud verano/invierno (limpia): {mc.max()/mc.min():.2f}x  (peak {MESES[mc.argmax()]}, valle {MESES[mc.argmin()]})")
print("\nLECTURA: 'cruda' mete los eventos en la estacionalidad; 'delta' = cuanto")
print("inflan los meses con evento (sep, dic, may) si NO se separan.")

os.makedirs(os.path.join(os.path.dirname(__file__),"resultados"),exist_ok=True)
pd.DataFrame({"mes":MESES,"limpia":mc,"cruda":mr}).to_csv(
    os.path.join(os.path.dirname(__file__),"resultados","verano_curva.csv"),index=False)
print("\n-> resultados/verano_curva.csv")
