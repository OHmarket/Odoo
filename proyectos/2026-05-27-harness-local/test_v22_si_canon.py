"""
v2.2 SI-canon: replica EXACTA del SI del motor HM-SI.

Motor HM-SI:
  _calc_si_from_weekly(weekly_by_isoweek):
      avg_by_week[w] = mean(totals[w]) sobre años con datos
      global_avg = mean(avg_by_week.values())
      si_w = avg_by_week[w] / global_avg
      clamp [SI_FLOOR=0.05, SI_CEIL=5.0]

Multi-nivel:
  local_categ (>= 12 sem) > categ_global > global

Pero para nuestro caso (cluster categ x abc) lo mas relevante es:
  SI por (categ_id, iso_week) sobre 52+ sem historico.
  Cada SKU del cluster usa el SI de su iso_week.

Algoritmo v2.2:
  1. Para cada (categ_id, abc): build serie weekly historica 52 sem.
  2. Calcular SI_w por iso_week SOBRE ESE cluster (canon HM-SI).
  3. Deflactar cada qty_w = qty_w / SI_w.
  4. nivel_recent_deflated = avg(qty_w_deflated en ultimas 10 sem cerradas)
     nivel_long_deflated   = avg(qty_w_deflated en ultimas 26 sem cerradas)
  5. factor = nivel_recent_deflated / nivel_long_deflated
  6. Clamp [0.80, 1.20]

Esto elimina TOTALMENTE la contaminacion estacional: la deflacion convierte
las series a "demanda base" plana, donde shift de NIVEL real se distingue
de oscilacion estacional.
"""
from __future__ import annotations
from pathlib import Path
from datetime import date, timedelta
import pandas as pd

CACHE = Path(__file__).parent / "cache"
RESULTS = Path(__file__).parent / "resultados"

CUTOFF_MONDAY = date(2026, 5, 25)
WINDOW_RECENT = 10
WINDOW_LONG = 26
SI_HISTORY_WEEKS = 52   # ventana SI historica
MIN_REAL = 500
CLAMP_LO = 0.80
CLAMP_HI = 1.20
APPLY_THRESHOLD = 0.05
SI_FLOOR = 0.05
SI_CEIL = 5.0


def iso_w(d):
    w = d.isocalendar()[1]
    return 52 if w > 52 else w


def calc_si_canon(weekly_totals):
    """Replica EXACTA de _calc_si_from_weekly del motor.

    weekly_totals: dict {iso_w: [qty_year1, qty_year2, ...]}
    Devuelve dict {iso_w: si_factor}.
    """
    avg_by_week = {}
    for w, totals in weekly_totals.items():
        clean = [float(x) for x in totals if x is not None]
        if clean:
            avg_by_week[w] = sum(clean) / len(clean)
    if not avg_by_week:
        return {w: 1.0 for w in range(1, 53)}
    global_avg = sum(avg_by_week.values()) / len(avg_by_week)
    if global_avg <= 0:
        return {w: 1.0 for w in range(1, 53)}
    si_norm = {}
    for w, v in avg_by_week.items():
        raw = v / global_avg
        si_norm[w] = max(SI_FLOOR, min(SI_CEIL, raw))
    for w in range(1, 53):
        if w not in si_norm:
            si_norm[w] = 1.0
    return si_norm


def compute_v22_canon(pos, abc_map, cutoff=CUTOFF_MONDAY):
    """factor = avg(recent deflated) / avg(long deflated) por (categ, abc)."""
    # Map abc por SKU
    pos = pos.copy()
    pos['abc'] = pos['product_id'].map(lambda p: abc_map.get(p, '')).str.slice(0, 1)
    pos = pos[pos['abc'].isin(['A', 'B', 'C'])]
    pos['iso_w'] = pos['week_start'].apply(iso_w)

    # Ventana SI: 52+ sem hacia atras del cutoff
    si_train_from = cutoff - timedelta(weeks=SI_HISTORY_WEEKS + 4)  # margen
    pos_si = pos[pos['week_start'] >= si_train_from]

    # Para cada (categ, abc) calcular SI canon
    si_by_cluster = {}
    for key, grp in pos_si.groupby(['categ_id', 'abc']):
        weekly_totals = {}
        for _, r in grp.iterrows():
            weekly_totals.setdefault(int(r['iso_w']), []).append(float(r['qty_sold']))
        si_by_cluster[(int(key[0]), key[1])] = calc_si_canon(weekly_totals)

    # Ventanas de evaluacion
    weeks_recent = set(cutoff - timedelta(weeks=i) for i in range(1, WINDOW_RECENT + 1))
    weeks_long = set(cutoff - timedelta(weeks=i) for i in range(1, WINDOW_LONG + 1))

    pos_eval = pos[pos['week_start'].isin(weeks_long)].copy()
    # Deflatar cada fila por su SI(categ, abc, iso_w)
    def get_si(row):
        key = (int(row['categ_id']), row['abc'])
        si_dict = si_by_cluster.get(key, {})
        return si_dict.get(int(row['iso_w']), 1.0)
    pos_eval['si'] = pos_eval.apply(get_si, axis=1)
    pos_eval['qty_deflated'] = pos_eval['qty_sold'] / pos_eval['si'].replace(0, 1)

    # Sumar por cluster sobre cada ventana
    pos_eval['in_recent'] = pos_eval['week_start'].isin(weeks_recent)

    out = {}
    for key, grp in pos_eval.groupby(['categ_id', 'abc']):
        cluster_key = (int(key[0]), key[1])
        recent = grp[grp['in_recent']]
        long_g = grp  # todos los del long
        real_recent = float(recent['qty_sold'].sum())
        if real_recent < MIN_REAL:
            continue
        nivel_recent = float(recent['qty_deflated'].sum()) / WINDOW_RECENT
        nivel_long = float(long_g['qty_deflated'].sum()) / WINDOW_LONG
        if nivel_long <= 0:
            continue
        raw = nivel_recent / nivel_long
        clamped = max(CLAMP_LO, min(CLAMP_HI, raw))
        out[cluster_key] = {'raw': raw, 'clamped': clamped, 'n': real_recent}
    return out


def compute_v20(pos, abc_map, cutoff=CUTOFF_MONDAY):
    """v2.0 plano (referencia)."""
    pos = pos.copy()
    pos['abc'] = pos['product_id'].map(lambda p: abc_map.get(p, '')).str.slice(0, 1)
    pos = pos[pos['abc'].isin(['A', 'B', 'C'])]
    weeks_recent = [cutoff - timedelta(weeks=i) for i in range(1, WINDOW_RECENT + 1)]
    weeks_long = [cutoff - timedelta(weeks=i) for i in range(1, WINDOW_LONG + 1)]
    r = pos[pos['week_start'].isin(weeks_recent)].groupby(['categ_id', 'abc'])['qty_sold'].sum()
    l = pos[pos['week_start'].isin(weeks_long)].groupby(['categ_id', 'abc'])['qty_sold'].sum()
    out = {}
    for k, real_r in r.items():
        real_l = l.get(k, 0)
        if real_r < MIN_REAL or real_l <= 0:
            continue
        raw = (real_r / WINDOW_RECENT) / (real_l / WINDOW_LONG)
        clamped = max(CLAMP_LO, min(CLAMP_HI, raw))
        out[(int(k[0]), k[1])] = {'raw': raw, 'clamped': clamped, 'n': real_r}
    return out


def compute_v21_ly(pos, abc_map, cutoff=CUTOFF_MONDAY):
    """v2.1 LY (referencia)."""
    pos = pos.copy()
    pos['abc'] = pos['product_id'].map(lambda p: abc_map.get(p, '')).str.slice(0, 1)
    pos = pos[pos['abc'].isin(['A', 'B', 'C'])]
    weeks_recent = [cutoff - timedelta(weeks=i) for i in range(1, WINDOW_RECENT + 1)]
    weeks_ly = [w - timedelta(weeks=52) for w in weeks_recent]
    r = pos[pos['week_start'].isin(weeks_recent)].groupby(['categ_id', 'abc'])['qty_sold'].sum()
    l = pos[pos['week_start'].isin(weeks_ly)].groupby(['categ_id', 'abc'])['qty_sold'].sum()
    out = {}
    for k, real_r in r.items():
        real_l = l.get(k, 0)
        if real_r < MIN_REAL or real_l <= 0:
            continue
        raw = real_r / real_l
        clamped = max(CLAMP_LO, min(CLAMP_HI, raw))
        out[(int(k[0]), k[1])] = {'raw': raw, 'clamped': clamped, 'n': real_r}
    return out


def summarize(name, factors):
    if not factors:
        return
    active = {k: v for k, v in factors.items() if abs(v['clamped'] - 1.0) >= APPLY_THRESHOLD}
    n = len(active)
    sat_l = sum(1 for v in active.values() if v['clamped'] == CLAMP_LO)
    sat_h = sum(1 for v in active.values() if v['clamped'] == CLAMP_HI)
    inter = n - sat_l - sat_h
    avg = sum(v['clamped'] for v in active.values()) / n if n else 0
    avg_raw = sum(v['raw'] for v in active.values()) / n if n else 0
    print(f"  {name:<25s} n={n:>3d}  sat_lo={sat_l:>3d}  sat_hi={sat_h:>3d}  inter={inter:>3d}  "
          f"avg_clamp={avg:.2f}  avg_raw={avg_raw:.2f}")


def main():
    print(f"Cutoff: {CUTOFF_MONDAY}")
    pos = pd.read_parquet(CACHE / 'pos_weekly.parquet')
    if pos['week_start'].dtype == object:
        pos['week_start'] = pd.to_datetime(pos['week_start']).dt.date
    abcxyz = pd.read_parquet(CACHE / 'abcxyz.parquet')
    abc_map = {int(r['product_id']): str(r['x_studio_abcxyz'] or '').strip().upper()
               for _, r in abcxyz.iterrows() if pd.notna(r['product_id'])}
    print(f"POS: {pos['week_start'].min()} .. {pos['week_start'].max()} ({len(pos):,} filas)")
    print(f"ABC map: {len(abc_map):,} SKUs\n")

    print("Calculando 3 versiones (puede demorar para SI canon)...")
    f_v20 = compute_v20(pos, abc_map)
    print("  v2.0 listo")
    f_v21 = compute_v21_ly(pos, abc_map)
    print("  v2.1 LY listo")
    f_v22 = compute_v22_canon(pos, abc_map)
    print("  v2.2 SI canon listo")

    print("\n" + "=" * 110)
    print("COMPARATIVA fixes")
    print("=" * 110)
    summarize("v2.0 actual (10/26)", f_v20)
    summarize("v2.1 LY (10/LY-10)", f_v21)
    summarize("v2.2 SI canon", f_v22)

    cats = pd.read_parquet(CACHE / 'catalog_categories.parquet').set_index('categ_id_id')['complete_name'].to_dict()

    print("\n" + "=" * 110)
    print("CERVEZAS (categ 1622-1626)")
    print("-" * 110)
    cerv_keys = sorted([k for k in f_v20 if 'Cervezas' in (cats.get(k[0], '') or '')])
    print(f"  {'categ':<48s} {'abc':>3s} {'v2.0':>6s} {'v2.1 LY':>8s} {'v2.2 SI':>8s}  (raw)")
    for k in cerv_keys[:20]:
        nm = (cats.get(k[0], '') or '')[:46]
        v0 = f_v20.get(k, {}).get('clamped')
        v1 = f_v21.get(k, {}).get('clamped')
        v2 = f_v22.get(k, {}).get('clamped')
        r2 = f_v22.get(k, {}).get('raw')
        print(f"  {nm:<48s} {k[1]:>3s} "
              f"{(f'{v0:.2f}' if v0 else '-'):>6s} "
              f"{(f'{v1:.2f}' if v1 else '-'):>8s} "
              f"{(f'{v2:.2f}' if v2 else '-'):>8s}  "
              f"({(f'{r2:.2f}' if r2 else '-')})")

    print("\n" + "=" * 110)
    print("HELADOS, SNACK, CHOCOLATES (donde v2.0 fallo)")
    print("-" * 110)
    snack_kw = ['Helados', 'Snack', 'Chocolate', 'Galleta', 'Caramelo', 'Chicle', 'Mani']
    snack_keys = sorted([k for k in f_v20
                         if any(kw in (cats.get(k[0], '') or '') for kw in snack_kw)])
    print(f"  {'categ':<48s} {'abc':>3s} {'v2.0':>6s} {'v2.1 LY':>8s} {'v2.2 SI':>8s}  (raw)")
    for k in snack_keys[:20]:
        nm = (cats.get(k[0], '') or '')[:46]
        v0 = f_v20.get(k, {}).get('clamped')
        v1 = f_v21.get(k, {}).get('clamped')
        v2 = f_v22.get(k, {}).get('clamped')
        r2 = f_v22.get(k, {}).get('raw')
        print(f"  {nm:<48s} {k[1]:>3s} "
              f"{(f'{v0:.2f}' if v0 else '-'):>6s} "
              f"{(f'{v1:.2f}' if v1 else '-'):>8s} "
              f"{(f'{v2:.2f}' if v2 else '-'):>8s}  "
              f"({(f'{r2:.2f}' if r2 else '-')})")

    print("\n" + "=" * 110)
    print("CIGARROS y ABARROTES (controles - sin estacionalidad fuerte)")
    print("-" * 110)
    abr_kw = ['Cigarr', 'Despensa', 'Aseo', 'Limpieza', 'Detergente']
    abr_keys = sorted([k for k in f_v20
                       if any(kw in (cats.get(k[0], '') or '') for kw in abr_kw)])
    print(f"  {'categ':<48s} {'abc':>3s} {'v2.0':>6s} {'v2.1 LY':>8s} {'v2.2 SI':>8s}  (raw)")
    for k in abr_keys[:10]:
        nm = (cats.get(k[0], '') or '')[:46]
        v0 = f_v20.get(k, {}).get('clamped')
        v1 = f_v21.get(k, {}).get('clamped')
        v2 = f_v22.get(k, {}).get('clamped')
        r2 = f_v22.get(k, {}).get('raw')
        print(f"  {nm:<48s} {k[1]:>3s} "
              f"{(f'{v0:.2f}' if v0 else '-'):>6s} "
              f"{(f'{v1:.2f}' if v1 else '-'):>8s} "
              f"{(f'{v2:.2f}' if v2 else '-'):>8s}  "
              f"({(f'{r2:.2f}' if r2 else '-')})")


if __name__ == "__main__":
    main()
