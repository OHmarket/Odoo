"""
Validar empiricamente los 3 fixes propuestos al SA Calib v2.0:

v2.0 actual: factor = avg(recent 10sem) / avg(long 26sem)
             PROBLEMA: long incluye verano dic-feb -> factor saturado en 0.80 post-verano

v2.1 LY:     factor = avg(recent 10sem) / avg(mismas 10sem LY)
             Controla estacionalidad por construccion.

v2.2 SI-adj: factor = avg(recent 10sem) / avg(long 26sem ajustado por SI iso_week)
             Canon SAP IBP: deflactar long por su patron estacional.

v2.3 short:  factor = avg(recent 10sem) / avg(long 13sem)
             Misma temporada (3 meses) - mas crudo pero simple.

Cutoff de prueba: 2026-05-25 (lunes esta semana en produccion) - REAL, no historico.

Para cada opcion mide:
 - Distribucion factor (saturados low/high)
 - Promedio
 - Top 10 cambios drasticos

NO predice BIAS/WAPE (no tenemos ground truth de proxima semana).
Solo evalua si los factores son razonables operativamente.
"""
from __future__ import annotations
from pathlib import Path
from datetime import date, timedelta
import pandas as pd

CACHE = Path(__file__).parent / "cache"
RESULTS = Path(__file__).parent / "resultados"

EXCLUDE_KEYWORDS = []  # V2 actual no excluye

# Cutoff REAL (produccion 2026-05-28 corre con cutoff = lunes de la semana actual)
CUTOFF_MONDAY = date(2026, 5, 25)

MIN_REAL = 500
CLAMP_LO = 0.80
CLAMP_HI = 1.20
APPLY_THRESHOLD = 0.05


def iso_week(d):
    return d.isocalendar()[1]


def compute_v20(pos_agg, n_recent=10, n_long=26):
    """v2.0 actual: recent vs long absoluto."""
    weeks_recent = [CUTOFF_MONDAY - timedelta(weeks=i) for i in range(1, n_recent + 1)]
    weeks_long = [CUTOFF_MONDAY - timedelta(weeks=i) for i in range(1, n_long + 1)]
    r = pos_agg[pos_agg['week_start'].isin(weeks_recent)].groupby(['categ_id', 'abc'])['qty_sold'].sum()
    l = pos_agg[pos_agg['week_start'].isin(weeks_long)].groupby(['categ_id', 'abc'])['qty_sold'].sum()
    out = {}
    for key, real_r in r.items():
        real_l = l.get(key, 0)
        if real_r < MIN_REAL or real_l <= 0:
            continue
        raw = (real_r / n_recent) / (real_l / n_long)
        clamped = max(CLAMP_LO, min(CLAMP_HI, raw))
        out[key] = {'raw': raw, 'clamped': clamped, 'n': real_r}
    return out


def compute_v21_ly(pos_agg, n_recent=10):
    """v2.1 LY: recent vs mismas 10 sem ano anterior."""
    weeks_recent = [CUTOFF_MONDAY - timedelta(weeks=i) for i in range(1, n_recent + 1)]
    weeks_ly = [w - timedelta(weeks=52) for w in weeks_recent]
    r = pos_agg[pos_agg['week_start'].isin(weeks_recent)].groupby(['categ_id', 'abc'])['qty_sold'].sum()
    l = pos_agg[pos_agg['week_start'].isin(weeks_ly)].groupby(['categ_id', 'abc'])['qty_sold'].sum()
    out = {}
    for key, real_r in r.items():
        real_l = l.get(key, 0)
        if real_r < MIN_REAL or real_l <= 0:
            continue
        raw = real_r / real_l   # ambos sobre 10 sem -> ratio directo
        clamped = max(CLAMP_LO, min(CLAMP_HI, raw))
        out[key] = {'raw': raw, 'clamped': clamped, 'n': real_r}
    return out


def compute_v22_si_adjusted(pos_agg, n_recent=10, n_long=26):
    """v2.2 SI-adj: deflactar long por SI iso_week.

    Calcula SI por (categ, abc, iso_week) sobre 52 sem historico.
    Luego: nivel_long_ajustado = sum(qty_w / SI_w) / sum(1/SI_w)
    """
    # SI por (categ, abc, iso_week) usando 52 sem historico
    weeks_si_train = [CUTOFF_MONDAY - timedelta(weeks=i) for i in range(1, 53)]
    train = pos_agg[pos_agg['week_start'].isin(weeks_si_train)].copy()
    train['iso_w'] = train['week_start'].apply(iso_week)
    si_by_caw = train.groupby(['categ_id', 'abc', 'iso_w'])['qty_sold'].mean().reset_index()
    si_by_caw.columns = ['categ_id', 'abc', 'iso_w', 'avg_qty']
    # SI = avg_qty(iso_w) / avg_qty(global) por (categ, abc)
    si_global = train.groupby(['categ_id', 'abc'])['qty_sold'].mean().reset_index()
    si_global.columns = ['categ_id', 'abc', 'global_avg']
    si_by_caw = si_by_caw.merge(si_global, on=['categ_id', 'abc'])
    si_by_caw['si'] = (si_by_caw['avg_qty'] / si_by_caw['global_avg'].replace(0, 1)).clip(0.05, 5.0)
    si_lookup = {(int(r['categ_id']), r['abc'], int(r['iso_w'])): r['si']
                 for _, r in si_by_caw.iterrows()}

    weeks_recent = [CUTOFF_MONDAY - timedelta(weeks=i) for i in range(1, n_recent + 1)]
    weeks_long = [CUTOFF_MONDAY - timedelta(weeks=i) for i in range(1, n_long + 1)]

    # SI-deflated por (categ, abc, week) sobre long
    long_data = pos_agg[pos_agg['week_start'].isin(weeks_long)].copy()
    long_data['iso_w'] = long_data['week_start'].apply(iso_week)
    long_data['si_w'] = [
        si_lookup.get((int(c), a, int(w)), 1.0)
        for c, a, w in zip(long_data['categ_id'], long_data['abc'], long_data['iso_w'])
    ]
    long_data['qty_deflated'] = long_data['qty_sold'] / long_data['si_w'].replace(0, 1)
    long_dedef = long_data.groupby(['categ_id', 'abc'])['qty_deflated'].mean().reset_index()

    # Recent SIN deflatar (queremos comparar nivel observado contra nivel "ideal" si todas
    # las semanas fueran promedio estacional)
    recent_data = pos_agg[pos_agg['week_start'].isin(weeks_recent)]
    recent = recent_data.groupby(['categ_id', 'abc'])['qty_sold'].sum().reset_index()
    recent['nivel_recent'] = recent['qty_sold'] / n_recent

    merged = recent.merge(long_dedef, on=['categ_id', 'abc'])
    out = {}
    for _, r in merged.iterrows():
        key = (int(r['categ_id']), r['abc'])
        if r['qty_sold'] < MIN_REAL or r['qty_deflated'] <= 0:
            continue
        raw = r['nivel_recent'] / r['qty_deflated']
        clamped = max(CLAMP_LO, min(CLAMP_HI, raw))
        out[key] = {'raw': raw, 'clamped': clamped, 'n': r['qty_sold']}
    return out


def main():
    print(f"Cutoff: {CUTOFF_MONDAY}")

    pos = pd.read_parquet(CACHE / 'pos_weekly.parquet')
    if pos['week_start'].dtype == object:
        pos['week_start'] = pd.to_datetime(pos['week_start']).dt.date
    print(f"POS: {pos['week_start'].min()} .. {pos['week_start'].max()} ({len(pos):,} filas)")

    # ABCXYZ map
    abcxyz = pd.read_parquet(CACHE / 'abcxyz.parquet')
    abc_map = {int(r['product_id']): str(r['x_studio_abcxyz'] or '').strip().upper()
               for _, r in abcxyz.iterrows() if pd.notna(r['product_id'])}
    pos['abc'] = pos['product_id'].map(lambda p: abc_map.get(p, '')).str.slice(0, 1)
    pos = pos[pos['abc'].isin(['A', 'B', 'C'])]
    print(f"  pos post-abc filter: {len(pos):,} filas")

    f_v20 = compute_v20(pos)
    f_v21 = compute_v21_ly(pos)
    f_v22 = compute_v22_si_adjusted(pos)
    f_v23 = compute_v20(pos, n_recent=10, n_long=13)  # short 13 vez de 26

    cats = pd.read_parquet(CACHE / 'catalog_categories.parquet').set_index('categ_id_id')['complete_name'].to_dict()

    print("\n" + "=" * 110)
    print("COMPARATIVA fixes")
    print("=" * 110)
    print(f"{'opcion':<32s} {'n_act':>6s} {'sat_low':>8s} {'sat_hi':>7s} {'inter':>6s} {'avg':>5s}")
    print("-" * 110)
    for name, f in [('v2.0 actual (10/26)', f_v20),
                    ('v2.1 LY (10/LY-10)', f_v21),
                    ('v2.2 SI-adj (10/26-deflated)', f_v22),
                    ('v2.3 short (10/13)', f_v23)]:
        # filtrar por threshold (igual que el SA)
        active = {k: v for k, v in f.items() if abs(v['clamped'] - 1.0) >= APPLY_THRESHOLD}
        n = len(active)
        sat_l = sum(1 for v in active.values() if v['clamped'] == CLAMP_LO)
        sat_h = sum(1 for v in active.values() if v['clamped'] == CLAMP_HI)
        inter = n - sat_l - sat_h
        avg = sum(v['clamped'] for v in active.values()) / n if n else 0
        print(f"{name:<32s} {n:>6d} {sat_l:>8d} {sat_h:>7d} {inter:>6d} {avg:>5.2f}")
    print()
    print("=" * 110)
    print("Foco CERVEZAS — comparar factor por opcion (categ 1622-1626)")
    print("-" * 110)
    cerv_keys = []
    for k in f_v20:
        cn = cats.get(k[0], '')
        if 'Cervezas' in cn:
            cerv_keys.append(k)
    cerv_keys = sorted(cerv_keys)
    print(f"{'categ':<48s} {'abc':>3s} {'v2.0':>5s} {'v2.1_LY':>8s} {'v2.2_SI':>8s} {'v2.3_13':>8s}")
    for k in cerv_keys[:20]:
        cat_name = (cats.get(k[0], '?') or '')[:46]
        v20 = f_v20.get(k, {}).get('clamped', '-')
        v21 = f_v21.get(k, {}).get('clamped', '-')
        v22 = f_v22.get(k, {}).get('clamped', '-')
        v23 = f_v23.get(k, {}).get('clamped', '-')
        v20s = f"{v20:.2f}" if isinstance(v20, float) else v20
        v21s = f"{v21:.2f}" if isinstance(v21, float) else v21
        v22s = f"{v22:.2f}" if isinstance(v22, float) else v22
        v23s = f"{v23:.2f}" if isinstance(v23, float) else v23
        print(f"{cat_name:<48s} {k[1]:>3s} {v20s:>5s} {v21s:>8s} {v22s:>8s} {v23s:>8s}")

    print()
    print("=" * 110)
    print("HELADOS y SNACK (donde v2.0 fallo mas grave - factor 0.42 raw)")
    print("-" * 110)
    snack_kw = ['Helados', 'Snack', 'Chocolate', 'Galleta', 'Caramelo']
    snack_keys = []
    for k in f_v20:
        cn = cats.get(k[0], '') or ''
        if any(kw in cn for kw in snack_kw):
            snack_keys.append(k)
    snack_keys = sorted(snack_keys)
    print(f"{'categ':<48s} {'abc':>3s} {'v2.0':>5s} {'v2.1_LY':>8s} {'v2.2_SI':>8s} {'v2.3_13':>8s}")
    for k in snack_keys[:15]:
        cat_name = (cats.get(k[0], '?') or '')[:46]
        v20 = f_v20.get(k, {}).get('clamped', '-')
        v21 = f_v21.get(k, {}).get('clamped', '-')
        v22 = f_v22.get(k, {}).get('clamped', '-')
        v23 = f_v23.get(k, {}).get('clamped', '-')
        v20s = f"{v20:.2f}" if isinstance(v20, float) else v20
        v21s = f"{v21:.2f}" if isinstance(v21, float) else v21
        v22s = f"{v22:.2f}" if isinstance(v22, float) else v22
        v23s = f"{v23:.2f}" if isinstance(v23, float) else v23
        print(f"{cat_name:<48s} {k[1]:>3s} {v20s:>5s} {v21s:>8s} {v22s:>8s} {v23s:>8s}")


if __name__ == "__main__":
    main()
