"""
Validacion de x_demanda_normalizada via XML-RPC.

Corre desde tu PC: python "proyectos/2026-05-25-normalizacion-demanda/validar_overlay.py"
"""
from __future__ import annotations

import sys
from pathlib import Path
from collections import defaultdict

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from shared.odoo_xmlrpc import OdooReader

MODEL = 'x_demanda_normalizada'

# Salas (mismas que pipeline) -> nombre legible
TEAM_NAME = {
    5: 'PA790', 6: 'LL200', 7: 'FU120', 8: 'PA645', 9: 'PA763', 10: 'LA812',
    11: 'SJ121', 12: 'PA706', 13: 'MEHEX', 16: 'CO899', 17: 'IM495', 18: 'ML402',
}


def main():
    odoo = OdooReader()
    print(odoo)
    print()

    # ------------------------------------------------------------
    # 1) Count total
    # ------------------------------------------------------------
    total = odoo.search_count(MODEL, [])
    print(f"[1] Total registros: {total:,}")
    if total == 0:
        print("  Modelo vacio. Confirmar que el productivo corrio.")
        return

    # ------------------------------------------------------------
    # 2) Sample para inspeccionar campos y valores
    # ------------------------------------------------------------
    sample = odoo.search_read(MODEL, [], limit=1)
    print(f"\n[2] Campos en una fila: {sorted(sample[0].keys())}")
    print(f"    Sample: {sample[0]}")

    # ------------------------------------------------------------
    # 3) Distribucion por metodo
    # ------------------------------------------------------------
    n_inflate = odoo.search_count(MODEL, [('x_studio_metodo', '=', 'inflate')])
    n_fallback = odoo.search_count(MODEL, [('x_studio_metodo', '=', 'fallback_neighbor')])
    print(f"\n[3] Metodo: inflate={n_inflate:,} | fallback={n_fallback:,} | "
          f"ratio={n_inflate/(n_fallback or 1):.1f}:1")

    # ------------------------------------------------------------
    # 4) Distribucion por perfil_level
    # ------------------------------------------------------------
    print("\n[4] Perfil weekday usado:")
    for lvl in ['sku', 'categ', 'sala']:
        n = odoo.search_count(MODEL, [('x_studio_perfil_level', '=', lvl)])
        print(f"    {lvl:6s}: {n:,} ({100*n/total:.1f}%)")

    # ------------------------------------------------------------
    # 5) Sanity: filas con qty_norm <= qty_obs (deben ser 0)
    # ------------------------------------------------------------
    # XML-RPC no soporta comparaciones entre 2 campos directamente.
    # Bajamos sample y chequeamos.
    print("\n[5] Sanity check qty_norm > qty_obs (todas):")
    all_recs = odoo.search_read(MODEL, [], fields=['x_studio_qty_obs', 'x_studio_qty_norm'])
    bad = [r for r in all_recs if r['x_studio_qty_norm'] <= r['x_studio_qty_obs'] + 1e-9]
    print(f"    filas con qty_norm <= qty_obs: {len(bad)} (debe ser 0)")
    if bad:
        print(f"    Sample: {bad[:3]}")

    # ------------------------------------------------------------
    # 6) Sumas globales y uplift
    # ------------------------------------------------------------
    sum_obs = sum(r['x_studio_qty_obs'] for r in all_recs)
    sum_norm = sum(r['x_studio_qty_norm'] for r in all_recs)
    uplift_abs = sum_norm - sum_obs
    uplift_pct = (sum_norm / sum_obs - 1) * 100 if sum_obs > 0 else 0
    print(f"\n[6] Sumas globales:")
    print(f"    sum qty_obs  = {sum_obs:>15,.1f}")
    print(f"    sum qty_norm = {sum_norm:>15,.1f}")
    print(f"    uplift abs   = {uplift_abs:>15,.1f} unidades")
    print(f"    uplift %     = +{uplift_pct:.2f}%")

    # ------------------------------------------------------------
    # 7) Distribucion del factor (multiplicador)
    # ------------------------------------------------------------
    print("\n[7] Distribucion del factor (qty_norm/qty_obs):")
    factor_recs = odoo.search_read(MODEL, [], fields=['x_studio_factor', 'x_studio_metodo'])
    buckets = defaultdict(int)
    for r in factor_recs:
        f = r['x_studio_factor']
        if f == 0:
            buckets['0 (fallback con qty_obs=0)'] += 1
        elif f < 1.1:
            buckets['1.0-1.1'] += 1
        elif f < 1.25:
            buckets['1.1-1.25'] += 1
        elif f < 1.5:
            buckets['1.25-1.5'] += 1
        elif f < 2.0:
            buckets['1.5-2.0'] += 1
        elif f < 2.5:
            buckets['2.0-2.5'] += 1
        else:
            buckets['2.5 (capped)'] += 1
    for b in ['0 (fallback con qty_obs=0)', '1.0-1.1', '1.1-1.25', '1.25-1.5',
              '1.5-2.0', '2.0-2.5', '2.5 (capped)']:
        n = buckets[b]
        if n:
            print(f"    {b:<32s}: {n:>7,} ({100*n/total:.1f}%)")

    # ------------------------------------------------------------
    # 8) Distribucion del avail
    # ------------------------------------------------------------
    print("\n[8] Distribucion de avail (disponibilidad ponderada):")
    avail_recs = odoo.search_read(MODEL, [], fields=['x_studio_avail'])
    bucket_avail = defaultdict(int)
    for r in avail_recs:
        a = r['x_studio_avail']
        if a < 0.10: b = '0.00-0.10'
        elif a < 0.20: b = '0.10-0.20'
        elif a < 0.30: b = '0.20-0.30'
        elif a < 0.40: b = '0.30-0.40'
        elif a < 0.60: b = '0.40-0.60'
        elif a < 0.80: b = '0.60-0.80'
        else:          b = '0.80-1.00'
        bucket_avail[b] += 1
    for b in ['0.00-0.10', '0.10-0.20', '0.20-0.30', '0.30-0.40',
              '0.40-0.60', '0.60-0.80', '0.80-1.00']:
        n = bucket_avail[b]
        if n:
            print(f"    avail {b}: {n:>7,} ({100*n/total:.1f}%)")

    # ------------------------------------------------------------
    # 9) Por team_id (sala)
    # ------------------------------------------------------------
    print("\n[9] Por sala (team_id):")
    per_team = defaultdict(lambda: {'n': 0, 'obs': 0.0, 'norm': 0.0})
    team_recs = odoo.search_read(MODEL, [], fields=['x_studio_team_id', 'x_studio_qty_obs', 'x_studio_qty_norm'])
    for r in team_recs:
        tid = r['x_studio_team_id'][0] if r.get('x_studio_team_id') else None
        if tid is None:
            continue
        per_team[tid]['n'] += 1
        per_team[tid]['obs'] += r['x_studio_qty_obs']
        per_team[tid]['norm'] += r['x_studio_qty_norm']
    print(f"    {'team':>5s} {'sala':<8s} {'n_celdas':>10s} {'sum_obs':>12s} {'sum_norm':>12s} {'uplift%':>10s}")
    for tid in sorted(per_team.keys()):
        s = per_team[tid]
        up = (s['norm']/s['obs'] - 1)*100 if s['obs'] > 0 else 0
        print(f"    {tid:>5d} {TEAM_NAME.get(tid, '?'):<8s} {s['n']:>10,} {s['obs']:>12,.0f} {s['norm']:>12,.0f} +{up:>8.1f}%")

    # ------------------------------------------------------------
    # 10) Top 10 mayor uplift absoluto (unidades extras a inflar)
    # ------------------------------------------------------------
    print("\n[10] Top 10 mayor uplift absoluto (unidades):")
    top_recs = odoo.search_read(MODEL, [], fields=[
        'x_studio_team_id', 'x_studio_product_id', 'x_studio_week_start',
        'x_studio_qty_obs', 'x_studio_qty_norm', 'x_studio_avail',
        'x_studio_factor', 'x_studio_metodo',
    ])
    for r in top_recs:
        r['_delta'] = r['x_studio_qty_norm'] - r['x_studio_qty_obs']
    top_recs.sort(key=lambda r: r['_delta'], reverse=True)
    print(f"    {'team':>5s} {'sku':>6s} {'week':10s} {'obs':>8s} {'norm':>8s} {'delta':>8s} {'avail':>7s} {'fac':>5s} {'met':>16s}")
    for r in top_recs[:10]:
        tid = r['x_studio_team_id'][0] if r.get('x_studio_team_id') else 0
        pid = r['x_studio_product_id'][0] if r.get('x_studio_product_id') else 0
        print(f"    {tid:>5d} {pid:>6d} {r['x_studio_week_start']:10s} "
              f"{r['x_studio_qty_obs']:>8.1f} {r['x_studio_qty_norm']:>8.1f} "
              f"{r['_delta']:>+8.1f} {r['x_studio_avail']:>7.3f} "
              f"{r['x_studio_factor']:>5.2f} {r['x_studio_metodo']:>16s}")


if __name__ == '__main__':
    main()
