"""
Paso 1 del proyecto de factores de evento: identificar eventos con AUMENTO REAL.

Mide uplift por SALA (no agregado) vs baseline limpio del mismo dia-semana.
Detecta abierto/cerrado empiricamente (venta>0). Para irrenunciables aisla el
cohorte que abrio. Usa pos.order diario en hora local Chile, 2023-2025.

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

# Eventos fijos (mes, dia, nombre, irrenunciable). Se generan para 2023-25.
FIXED = [
    (1, 1,  "Ano Nuevo",          True),
    (5, 1,  "Dia del Trabajo",    True),
    (5, 21, "Glorias Navales",    False),
    (7, 16, "Virgen del Carmen",  False),
    (8, 15, "Asuncion",           False),
    (9, 18, "Independencia 18",   True),
    (9, 19, "Glorias Ejercito 19",True),
    (11, 1, "Todos los Santos",   False),
    (12, 8, "Inmaculada",         False),
    (12, 25,"Navidad",            True),
    # eventos comerciales (no feriado, salvo Halloween que coincide con feriado)
    (10, 31,"Halloween",          False),
    (2, 14, "San Valentin",       False),
]
# Movibles hardcode por ano
MOVIBLE = [
    ("Viernes Santo",   False, {2023: "2023-04-07", 2024: "2024-03-29", 2025: "2025-04-18"}),
    ("Dia de la Madre", False, {2023: "2023-05-14", 2024: "2024-05-12", 2025: "2025-05-11"}),
    ("Dia del Padre",   False, {2023: "2023-06-18", 2024: "2024-06-16", 2025: "2025-06-15"}),
]
YEARS = [2023, 2024, 2025]

# construir lista de (nombre, irren, fecha)
events = []
for m, d, name, irr in FIXED:
    for y in YEARS:
        events.append((name, irr, dt.date(y, m, d)))
for name, irr, dd in MOVIBLE:
    for y, s in dd.items():
        events.append((name, irr, dt.date.fromisoformat(s)))
ev_df = pd.DataFrame(events, columns=["evento", "irren", "fecha"])

# ----------------------------------------------------------------------
# Pull venta diaria por team (hora local), 2023-2025
# ----------------------------------------------------------------------
o = OdooReader()
g = o.execute('pos.order', 'read_group',
              [('state', 'in', ['paid', 'done', 'invoiced']),
               ('date_order', '>=', '2023-01-01'), ('date_order', '<', '2026-01-01')],
              ['amount_total:sum'],
              ['crm_team_id', 'date_order:day'],
              lazy=False, context={'tz': TZ})
rows = []
for r in g:
    team = r.get('crm_team_id')
    if not team:
        continue
    d = r['__range']['date_order:day']['from'][:10]    # fecha local
    rows.append((team[0], d, r.get('amount_total') or 0.0))
df = pd.DataFrame(rows, columns=["team", "fecha", "venta"])
df["fecha"] = pd.to_datetime(df["fecha"], format="%Y-%m-%d").dt.date
df["dow"] = pd.to_datetime(df["fecha"]).dt.weekday
print(f"teams: {df['team'].nunique()}  dias: {df['fecha'].nunique()}  "
      f"rango: {df['fecha'].min()} -> {df['fecha'].max()}")

# set de fechas contaminadas (todo evento +/-2 dias y visperas) para excluir del baseline
contam = set()
for _, r in ev_df.iterrows():
    for off in range(-2, 3):
        contam.add(r["fecha"] + dt.timedelta(days=off))

# ----------------------------------------------------------------------
# Uplift por sala
# ----------------------------------------------------------------------
def baseline(team_series, fecha, dow):
    # mediana mismo dia-semana en +/-35 dias, excluyendo dias contaminados
    lo = pd.Timestamp(fecha - dt.timedelta(days=35))
    hi = pd.Timestamp(fecha + dt.timedelta(days=35))
    mask = (team_series.index >= lo) & (team_series.index <= hi)
    sub = team_series[mask]
    sub = sub[[ (idx.weekday() == dow) and (idx.date() not in contam) for idx in pd.to_datetime(sub.index) ]]
    vals = sub[sub > 0].values
    return (np.median(vals) if len(vals) >= 3 else np.nan)

# series por team indexada por fecha
series = {t: g.set_index("fecha")["venta"].sort_index()
          for t, g in df.groupby("team")}
for t in series:
    series[t].index = pd.to_datetime(series[t].index)

recs = []
teams = sorted(series.keys())
for _, ev in ev_df.iterrows():
    f = ev["fecha"]
    fts = pd.Timestamp(f)
    visp = pd.Timestamp(f - dt.timedelta(days=1))
    for t in teams:
        s = series[t]
        # sala "activa" ese periodo: tuvo venta en +/-10 dias fuera del evento
        win = s[(s.index >= fts - pd.Timedelta(days=10)) & (s.index <= fts + pd.Timedelta(days=10))]
        win = win[[abs((idx - fts).days) > 2 for idx in win.index]]
        if (win > 0).sum() < 3:
            continue                          # no operaba ese periodo -> excluir
        v_day = s.get(fts, 0.0)
        v_vis = s.get(visp, np.nan)
        bl_day = baseline(s, f, f.weekday())
        bl_vis = baseline(s, f - dt.timedelta(days=1), (f - dt.timedelta(days=1)).weekday())
        recs.append(dict(
            evento=ev["evento"], irren=ev["irren"], year=f.year, team=t,
            abierto=v_day > 0,
            up_day=(v_day / bl_day if (v_day > 0 and bl_day and bl_day > 0) else np.nan),
            up_vis=(v_vis / bl_vis if (v_vis and v_vis > 0 and bl_vis and bl_vis > 0) else np.nan),
        ))
R = pd.DataFrame(recs)

# ----------------------------------------------------------------------
# Agregado por evento
# ----------------------------------------------------------------------
def agg(gr):
    n_obs = len(gr)
    pct_open = gr["abierto"].mean()
    up_day = gr.loc[gr["abierto"], "up_day"].median()
    up_vis = gr["up_vis"].median()
    return pd.Series(dict(n_obs=n_obs, pct_abierto=pct_open,
                          uplift_dia=up_day, uplift_vispera=up_vis))

summary = R.groupby(["evento", "irren"]).apply(agg, include_groups=False).reset_index()
summary["peak"] = summary[["uplift_dia", "uplift_vispera"]].max(axis=1)
summary = summary.sort_values("peak", ascending=False)

pd.set_option("display.width", 160)
sh = summary.copy()
sh["pct_abierto"] = (sh["pct_abierto"]*100).round(0)
for c in ["uplift_dia", "uplift_vispera", "peak"]:
    sh[c] = sh[c].round(2)
print("\n" + "="*92)
print("EVENTOS POR UPLIFT REAL (por sala abierta, vs baseline mismo dia-semana, 2023-25)")
print("="*92)
print(sh[["evento","irren","n_obs","pct_abierto","uplift_dia","uplift_vispera","peak"]].to_string(index=False))
print("\nLEYENDA: uplift = venta / baseline (1.0 = normal, 2.0 = +100%).")
print("  pct_abierto = % de (sala,ano) que operaron ese dia.")
print("  irren=True y pct_abierto<100 => irrenunciable, solo algunas salas abren.")
print("  uplift_dia se mide SOLO sobre salas que abrieron.")

os.makedirs(os.path.join(os.path.dirname(__file__), "resultados"), exist_ok=True)
summary.to_csv(os.path.join(os.path.dirname(__file__), "resultados", "eventos_uplift.csv"),
               index=False, encoding="utf-8-sig")
R.to_csv(os.path.join(os.path.dirname(__file__), "resultados", "eventos_uplift_detalle.csv"),
         index=False, encoding="utf-8-sig")
print("\n-> resultados/eventos_uplift.csv (+ detalle por sala)")
