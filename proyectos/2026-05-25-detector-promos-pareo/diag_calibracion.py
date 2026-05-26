"""
Diagnostico Task 1: por que DOLBEK no se detecta + calibrar baseline_min.

Simula el filtro v5.8 sobre eventos cervecera/alcoholes y reporta:
1. Cobertura del filtro v5.8 actual (cuantos pasan)
2. Por que SKUs especificos (DOLBEK, CUSQUENA) quedan fuera
3. Distribucion de baseline_8w (para elegir baseline_min)
4. Cobertura del filtro v5.9 propuesto con varios baseline_min
"""
from __future__ import annotations

import sys
from pathlib import Path
from collections import defaultdict

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from shared.odoo_xmlrpc import OdooReader

odoo = OdooReader()
print(odoo)
print()

# ---------------------------------------------------------------
# 1) Bajar eventos cervecera/alcoholes 6 meses
# ---------------------------------------------------------------
print("Bajando x_loyalty_promo_event (6 meses, cervezas/alcoholes)...")
events_all = odoo.search_read(
    'x_loyalty_promo_event',
    [('x_studio_period_start', '>=', '2025-12-01')],
    fields=[
        'x_studio_product_variant_id', 'x_studio_period_start',
        'x_studio_program_name', 'x_studio_minimum_qty',
        'x_studio_lift_qty', 'x_studio_qty_actual', 'x_studio_qty_baseline_8w',
        'x_studio_price_delta_pct', 'x_studio_categ_id',
        'x_studio_weeks_active', 'x_studio_promo_effect',
    ],
)
# Filtrar cervezas/alcoholes/destilados
beer_keys = ['cerveza', 'destilado', 'vino', 'coctel', 'licor', 'espumante']
events = []
for e in events_all:
    cat = e.get('x_studio_categ_id')
    cat_name = (cat[1] if isinstance(cat, list) else '').lower()
    if any(k in cat_name for k in beer_keys):
        events.append(e)
print(f"Total events en cervezas/alcoholes: {len(events):,}")
print(f"  Distribucion por min_qty:")
mq_dist = defaultdict(int)
for e in events:
    mq_dist[int(e.get('x_studio_minimum_qty') or 0)] += 1
for mq in sorted(mq_dist):
    print(f"    min_qty={mq}: {mq_dist[mq]:,}")


# ---------------------------------------------------------------
# 2) Simular filtro v5.8: emite si min_qty<=2 AND lift>=2.5
# ---------------------------------------------------------------
def _v58_pasa(e):
    mq = int(e.get('x_studio_minimum_qty') or 0)
    lift = e.get('x_studio_lift_qty') or 0
    if mq <= 2:
        return lift >= 2.5, 'PROMO_PAREO_LIFT_EXTREMO' if lift >= 2.5 else None
    if mq in (3, 4):
        wa = int(e.get('x_studio_weeks_active') or 0)
        if wa <= 1 and lift >= 1.8:
            return True, 'DISPARO_MIXTO_W1'
        return False, None
    if mq >= 6:
        wa = int(e.get('x_studio_weeks_active') or 0)
        if wa <= 1 and lift >= 1.5:
            return True, 'DISPARO_STOCKUP_W1'
        if wa >= 3 and 0.5 < lift < 0.8:
            return True, 'SATURACION_STOCKUP_W%d' % wa
        return False, None
    return False, None


v58_pass = []
v58_fail = []
for e in events:
    ok, tipo = _v58_pasa(e)
    if ok:
        v58_pass.append((e, tipo))
    else:
        v58_fail.append(e)

print()
print(f"Filtro v5.8 sobre {len(events):,} eventos cervecera/alcoholes:")
print(f"  PASAN: {len(v58_pass):,}")
print(f"  RECHAZADOS: {len(v58_fail):,}")
tipos_pass = defaultdict(int)
for _, t in v58_pass:
    tipos_pass[t] += 1
for t, n in sorted(tipos_pass.items(), key=lambda x: -x[1]):
    print(f"    -> {t}: {n:,}")


# ---------------------------------------------------------------
# 3) Verificar contra x_price_coreccion real (cuantos efectivamente se emitieron)
# ---------------------------------------------------------------
print()
print(f"Verificando contra x_price_coreccion real (Sample 30 events que PASARIAN v5.8):")
for e, tipo in v58_pass[:30]:
    pid = e['x_studio_product_variant_id'][0] if isinstance(e['x_studio_product_variant_id'], list) else 0
    wk = e['x_studio_period_start']
    # Buscar en x_price_coreccion (typo intencional, una r)
    found = odoo.search_count('x_price_coreccion',
        [('x_studio_product_id', '=', pid), ('x_studio_target_week_start', '=', wk)])
    flag = 'OK' if found else 'FALTA <--'
    lift = e.get('x_studio_lift_qty') or 0
    bl = e.get('x_studio_qty_baseline_8w') or 0
    print(f"  pid={pid:>5d} wk={wk:<11s} mq={int(e.get('x_studio_minimum_qty',0)):>2d} lift={lift:>5.2f} bl={bl:>5.0f} tipo_esperado={tipo:<30s} en_coreccion={flag}")


# ---------------------------------------------------------------
# 4) DOLBEK 28486 detalle: por que no aparece
# ---------------------------------------------------------------
print()
print("=" * 75)
print(" DOLBEK MAQUI (28486) - investigacion")
print("=" * 75)
dolbek_events = [e for e in events if (e.get('x_studio_product_variant_id') and
                 (e['x_studio_product_variant_id'][0] if isinstance(e['x_studio_product_variant_id'], list) else e['x_studio_product_variant_id']) == 28486)]
print(f"Eventos DOLBEK en loyalty (6 meses): {len(dolbek_events)}")
for e in sorted(dolbek_events, key=lambda x: x['x_studio_period_start']):
    ok, tipo = _v58_pasa(e)
    print(f"  wk={e['x_studio_period_start']} min_qty={int(e.get('x_studio_minimum_qty',0))} lift={e.get('x_studio_lift_qty',0):.2f} wa={int(e.get('x_studio_weeks_active',0))} bl={e.get('x_studio_qty_baseline_8w',0):.0f} -> v5.8 {'EMITE' if ok else 'NO'} ({tipo})")

# Buscar en x_price_coreccion para DOLBEK
print(f"\nDOLBEK en x_price_coreccion (todas las entradas):")
in_corr = odoo.search_read('x_price_coreccion',
    [('x_studio_product_id', '=', 28486)],
    fields=['x_studio_target_week_start', 'x_studio_factor_corr', 'x_studio_tipo_alerta', 'x_studio_active'])
print(f"  encontradas: {len(in_corr)}")
for c in in_corr:
    print(f"    wk={c['x_studio_target_week_start']} tipo={c['x_studio_tipo_alerta']} factor={c['x_studio_factor_corr']:.3f} active={c.get('x_studio_active')}")


# ---------------------------------------------------------------
# 5) CUSQUENA 10844 detalle
# ---------------------------------------------------------------
print()
print("=" * 75)
print(" CUSQUENA 10844 - investigacion")
print("=" * 75)
cusquena = [e for e in events if (e.get('x_studio_product_variant_id') and
            (e['x_studio_product_variant_id'][0] if isinstance(e['x_studio_product_variant_id'], list) else e['x_studio_product_variant_id']) == 10844)]
print(f"Eventos CUSQUENA en loyalty: {len(cusquena)}")
for e in sorted(cusquena, key=lambda x: x['x_studio_period_start']):
    ok, tipo = _v58_pasa(e)
    print(f"  wk={e['x_studio_period_start']} min_qty={int(e.get('x_studio_minimum_qty',0))} lift={e.get('x_studio_lift_qty',0):.2f} bl={e.get('x_studio_qty_baseline_8w',0):.0f} -> v5.8 {'EMITE' if ok else 'NO'}")


# ---------------------------------------------------------------
# 6) Calibrar baseline_min: cobertura v5.9 con varios thresholds
# ---------------------------------------------------------------
print()
print("=" * 75)
print(" Task 1.2: Calibrar baseline_min para v5.9")
print("=" * 75)
print()

# Subset: min_qty<=2 (donde queremos relajar)
mq2 = [e for e in events if int(e.get('x_studio_minimum_qty') or 0) <= 2]
print(f"Eventos min_qty<=2 totales: {len(mq2):,}")

# Distribucion baseline en mq<=2
baselines = sorted(e.get('x_studio_qty_baseline_8w') or 0 for e in mq2)
if baselines:
    p10 = baselines[len(baselines)//10]
    p25 = baselines[len(baselines)//4]
    p50 = baselines[len(baselines)//2]
    p75 = baselines[3*len(baselines)//4]
    print(f"Distribucion baseline en mq<=2: p10={p10:.1f} p25={p25:.1f} p50={p50:.1f} p75={p75:.1f}")

# Cuantos pasan v5.9 con cada baseline_min ∈ {1, 3, 5, 8, 10, 15}
print()
print(f"Cobertura v5.9 (min_qty<=2, lift>=1.5, baseline>=N):")
print(f"  {'baseline_min':<14s} {'pasan_v59':>10s} {'extremos_v58':>14s} {'NUEVOS (mod)':>14s}")
for bl_min in [1, 3, 5, 8, 10, 15]:
    n_v59 = sum(1 for e in mq2 if (e.get('x_studio_lift_qty') or 0) >= 1.5 and (e.get('x_studio_qty_baseline_8w') or 0) >= bl_min)
    n_v58_ext = sum(1 for e in mq2 if (e.get('x_studio_lift_qty') or 0) >= 2.5)
    n_new = sum(1 for e in mq2 if 1.5 <= (e.get('x_studio_lift_qty') or 0) < 2.5 and (e.get('x_studio_qty_baseline_8w') or 0) >= bl_min)
    print(f"  {bl_min:<14d} {n_v59:>10,} {n_v58_ext:>14,} {n_new:>14,}")


# ---------------------------------------------------------------
# 7) Spot check: 20 nuevos eventos que v5.9 emitiria (lift 1.5-2.5, baseline>=5)
# ---------------------------------------------------------------
print()
print("=" * 75)
print(" Sample 20 NUEVOS eventos que v5.9 (baseline_min=5) emitiria")
print("=" * 75)
nuevos = [e for e in mq2
          if 1.5 <= (e.get('x_studio_lift_qty') or 0) < 2.5
          and (e.get('x_studio_qty_baseline_8w') or 0) >= 5]
nuevos.sort(key=lambda e: -(e.get('x_studio_lift_qty') or 0))
print(f"Total nuevos eventos: {len(nuevos):,}")
print(f"{'sku':>5s} {'wk':<12s} {'lift':>5s} {'bl':>4s} {'effect':>7s} program (truncado)")
for e in nuevos[:30]:
    pid = e['x_studio_product_variant_id'][0] if isinstance(e['x_studio_product_variant_id'], list) else 0
    prog = (e.get('x_studio_program_name') or '')[:55]
    eff = e.get('x_studio_promo_effect') or ''
    print(f"  {pid:>5d} {str(e['x_studio_period_start']):<12s} {e.get('x_studio_lift_qty',0):>5.2f} {e.get('x_studio_qty_baseline_8w',0):>4.0f} {eff[:7]:>7s}  {prog}")
