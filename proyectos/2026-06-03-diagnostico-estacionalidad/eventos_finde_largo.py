"""
Efecto 'sanguche' / fin de semana largo en feriados.

Cada feriado cae distinto dia segun el ano (3 anos). Clasifica la ocurrencia por
configuracion de calendario y compara el PEAK de uplift de la ventana [d-2..d]
(donde sea que caiga el spike). Cuantifica el multiplicador de finde largo.

Read-only. Solo feriados (dias no laborables); excluye comerciales (San Valentin,
Madre, Padre) que no arman finde.
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

# Solo FERIADOS (no laborables). (mes,dia,nombre)
FER = [(1,1,"Ano Nuevo"),(5,1,"Dia del Trabajo"),(5,21,"Glorias Navales"),
       (7,16,"Virgen del Carmen"),(8,15,"Asuncion"),(9,18,"Independencia 18"),
       (9,19,"Glorias Ejercito 19"),(10,31,"Iglesias/Halloween"),
       (11,1,"Todos los Santos"),(12,8,"Inmaculada"),(12,25,"Navidad")]
MOV = {"Viernes Santo":{2023:"2023-04-07",2024:"2024-03-29",2025:"2025-04-18"}}
YEARS=[2023,2024,2025]

occ=[]  # (nombre, fecha)
for m,d,n in FER:
    for y in YEARS: occ.append((n,dt.date(y,m,d)))
for n,dd in MOV.items():
    for y,s in dd.items(): occ.append((n,dt.date.fromisoformat(s)))
hol_set={f for _,f in occ}

DOW=["Lun","Mar","Mie","Jue","Vie","Sab","Dom"]
def tipo(f):
    wd=f.weekday()
    if wd in (1,3): return "sanguche (Mar/Jue)"     # puente
    if wd in (0,4): return "finde largo (Lun/Vie)"
    if wd==2:       return "aislado (Mie)"
    return "cae en finde (Sab/Dom)"

def block_efectivo(f):
    # dias no laborables consecutivos: finde + feriados + puente heuristico
    nolab=set(hol_set)
    wd=f.weekday()
    if wd==1: nolab.add(f-dt.timedelta(days=1))   # puente lunes
    if wd==3: nolab.add(f+dt.timedelta(days=1))   # puente viernes
    def is_off(d): return d.weekday()>=5 or d in nolab
    L=1; x=f-dt.timedelta(days=1)
    while is_off(x): L+=1; x-=dt.timedelta(days=1)
    x=f+dt.timedelta(days=1)
    while is_off(x): L+=1; x+=dt.timedelta(days=1)
    return L

# ---- pull diario por team ----
o=OdooReader()
g=o.execute('pos.order','read_group',
  [('state','in',['paid','done','invoiced']),('date_order','>=','2023-01-01'),('date_order','<','2026-01-01')],
  ['amount_total:sum'],['crm_team_id','date_order:day'], lazy=False, context={'tz':TZ})
rows=[]
for r in g:
    t=r.get('crm_team_id')
    if not t: continue
    d=dt.date.fromisoformat(r['__range']['date_order:day']['from'][:10])
    rows.append((t[0],d,r.get('amount_total') or 0.0))
df=pd.DataFrame(rows,columns=["team","fecha","venta"])
series={t:gg.set_index("fecha")["venta"].sort_index() for t,gg in df.groupby("team")}

contam=set()
for _,f in occ:
    for k in range(-2,3): contam.add(f+dt.timedelta(days=k))

def baseline(s, f):
    lo,hi=f-dt.timedelta(days=35),f+dt.timedelta(days=35)
    sub=s[(s.index>=lo)&(s.index<=hi)]
    vals=[v for idx,v in sub.items() if idx.weekday()==f.weekday() and idx not in contam and v>0]
    return np.median(vals) if len(vals)>=3 else np.nan

recs=[]
for nombre,f in occ:
    for t,s in series.items():
        win=s[(s.index>=f-dt.timedelta(days=10))&(s.index<=f+dt.timedelta(days=10))]
        if (win[[abs((i-f).days)>2 for i in win.index]]>0).sum()<3: continue  # no operaba
        ups=[]
        for off in (-2,-1,0):
            d=f+dt.timedelta(days=off)
            v=s.get(d,0.0); bl=baseline(s,d)
            if v>0 and bl and bl>0: ups.append(v/bl)
        if not ups: continue
        recs.append(dict(nombre=nombre,fecha=f,year=f.year,team=t,
                         tipo=tipo(f),dow=DOW[f.weekday()],block=block_efectivo(f),
                         peak=max(ups)))
R=pd.DataFrame(recs)

print("="*70)
print("MULTIPLICADOR FINDE LARGO (peak ventana visp-dia, por configuracion)")
print("="*70)
bt=R.groupby("tipo")["peak"].agg(["median","count"]).round(2).sort_values("median",ascending=False)
print(bt.to_string())
print("\nPor largo del bloque no-laboral efectivo (dias):")
bb=R.groupby("block")["peak"].agg(["median","count"]).round(2)
print(bb.to_string())

print("\n" + "="*70)
print("MISMO EVENTO, DISTINTO ANO/DIA (los grandes)")
print("="*70)
for n in ["Independencia 18","Navidad","Virgen del Carmen","Glorias Navales","Asuncion"]:
    sub=R[R.nombre==n]
    if sub.empty: continue
    print(f"\n{n}:")
    for y in YEARS:
        ss=sub[sub.year==y]
        if ss.empty: continue
        print(f"  {y}  {ss.iloc[0]['dow']}  block={ss.iloc[0]['block']}d  "
              f"{ss.iloc[0]['tipo']:22s}  peak_med={ss['peak'].median():.2f}x (n={len(ss)})")

os.makedirs(os.path.join(os.path.dirname(__file__),"resultados"),exist_ok=True)
R.to_csv(os.path.join(os.path.dirname(__file__),"resultados","eventos_finde_largo.csv"),index=False,encoding="utf-8-sig")
print("\n-> resultados/eventos_finde_largo.csv")
