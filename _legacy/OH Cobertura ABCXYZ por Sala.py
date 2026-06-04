"""
Cobertura ABCXYZ por Sala — Ranking canon para priorizar gaps de cobertura.

Metodologia: Priority Score estilo SAP IBP / Blue Yonder / Oracle RDF
    Priority_Score = Oportunidad_Economica × Confianza × Tried_Penalty

Para cada par (SKU clase A/B/C vivo × sala con gap):

  1. Oportunidad anual ($):
       mu_estimado_sala = factor_normalizado_sku × mu_categoria_sala_target
       opportunity_anual = mu_estimado_sala × margen_unit × 52

     factor_normalizado_sku = mean(mu_sku_sala_i / mu_categ_sala_i)
       sobre salas donde el SKU tiene mu>0 y la categoria tambien.

     Si la sala target tiene < 12 semanas de historia categoria:
       mu_categ_sala_target = mean(mu_categ_sala_i) para bottom-50% otras salas
       (replica logica fair share v3.41).

  2. Confianza ABC × XYZ:
       abc_weight: A=1.00, B=0.60, C=0.25
       xyz_weight: X=1.00, Y=0.70, Z=0.35

  3. Penalizacion "probo y fallo":
       Si active_weeks_local > 0 AND mu_local == 0 -> 0.15
       Si no -> 1.00

  4. Score por (SKU × sala gap):
       score_celda = opportunity_anual × confidence × tried_penalty

  5. Ranking por SKU:
       sku_priority = sum(score_celda for sala in salas_con_gap)

Universo:
  - x_calculo_abc_xyz.eliminar_sino = False
  - ciclo_de_vida IN (mature, ramp_up, intermittent, seasonal)
  - product.product.active = True

Margen unitario:
  - Fuente canon: x_margen_por_producto_ ultimos 6 meses, ponderado por qty.
  - Fallback: list_price - standard_price.

Output: Excel en escritorio del usuario, 2 hojas (Cobertura, Resumen).

Ejecucion: desde el PC del usuario (XML-RPC, no Server Action).
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path
from collections import defaultdict
from statistics import mean

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from shared.odoo_xmlrpc import OdooReader
import pandas as pd

# =====================================================
# Configuracion canon
# =====================================================
ABC_WEIGHT = {'A': 1.00, 'B': 0.60, 'C': 0.25}
XYZ_WEIGHT = {'X': 1.00, 'Y': 0.70, 'Z': 0.35}
TRIED_PENALTY = 0.15
# Cap por crecimiento razonable (canon Blue Yonder/SAP):
# oportunidad_total <= mu_global * margen * 52 * growth_cap(xyz)
GROWTH_CAP = {'X': 3.0, 'Y': 2.0, 'Z': 1.5}
# Confianza estadistica del factor_normalizado segun N salas activas
# (canon SAP IBP: con pocas observaciones, el factor es ruido)
CONFIDENCE_N = {
    0: 0.00,
    1: 0.30,
    2: 0.50,
    3: 0.75,
    4: 0.75,
}  # >= 5 -> 1.00
MARGEN_LOOKBACK_DAYS = 180  # ultimos 6 meses
HIST_CATEG_MIN_WEEKS = 12   # umbral para bottom-N fallback en sala nueva
BOTTOM_FRAC = 0.5            # bottom-50% de salas para fallback (v3.41)
CICLOS_VIVOS = ('mature', 'ramp_up', 'intermittent', 'seasonal')


def confidence_n_factor(n_salas: int) -> float:
    return CONFIDENCE_N.get(n_salas, 1.00)


def main():
    odoo = OdooReader()
    print(odoo)

    # =====================================================
    # 1. UNIVERSO ABCXYZ vivo
    # =====================================================
    print("\n[1/7] Universo ABCXYZ vivo...")
    abc_recs = odoo.search_read(
        'x_calculo_abc_xyz',
        domain=[
            ('x_studio_eliminar_sino', '=', False),
            ('x_studio_ciclo_de_vida', 'in', list(CICLOS_VIVOS)),
        ],
        fields=[
            'x_studio_product_id', 'x_studio_categ_id',
            'x_studio_abc', 'x_studio_xyz', 'x_studio_abcxyz', 'x_studio_rank_abcxyz',
            'x_studio_ciclo_de_vida', 'x_studio_importancia',
            'x_studio_mu_week', 'x_studio_uni_ltimo_trimestre',
        ],
        order='x_studio_rank_abcxyz asc',
    )
    print(f"  {len(abc_recs)} SKUs")
    prod_ids = [r['x_studio_product_id'][0] for r in abc_recs if r.get('x_studio_product_id')]

    # Producto activo
    prods = odoo.search_read(
        'product.product',
        domain=[('id', 'in', prod_ids), ('active', '=', True)],
        fields=['id', 'default_code', 'name', 'list_price', 'standard_price'],
    )
    prod_info = {p['id']: p for p in prods}
    print(f"  {len(prod_info)} activos")

    # =====================================================
    # 2. HM SI Forecast por (producto, sala)
    # =====================================================
    print("\n[2/7] HM SI Forecast por sala...")
    active_pids = list(prod_info.keys())
    si_all = []
    BATCH = 200
    for i in range(0, len(active_pids), BATCH):
        chunk = active_pids[i:i+BATCH]
        si = odoo.search_read(
            'x_hm_si_forecast',
            domain=[('x_studio_product_id', 'in', chunk)],
            fields=[
                'x_studio_product_id', 'x_studio_team_id', 'x_studio_categ_id',
                'x_studio_mu_week', 'x_studio_mu_base',
                'x_studio_active_weeks_local', 'x_studio_forecast_scope',
                'x_studio_ciclo_de_vida', 'x_studio_abcxyz',
            ],
        )
        si_all.extend(si)
    print(f"  {len(si_all)} registros HM SI")

    # Index (pid, tid) -> registro
    si_map = {}
    for r in si_all:
        pid = r['x_studio_product_id'][0] if r.get('x_studio_product_id') else None
        tid = r['x_studio_team_id'][0] if r.get('x_studio_team_id') else None
        if pid and tid:
            si_map[(pid, tid)] = r

    # =====================================================
    # 3. Margen unitario por producto (canon)
    # =====================================================
    print(f"\n[3/7] Margen unitario ultimos {MARGEN_LOOKBACK_DAYS} dias...")
    fecha_desde = (date.today() - timedelta(days=MARGEN_LOOKBACK_DAYS)).isoformat()
    # Agregamos qty y margin_total por producto
    margen_recs = []
    for i in range(0, len(active_pids), BATCH):
        chunk = active_pids[i:i+BATCH]
        m = odoo.search_read(
            'x_margen_por_producto_',
            domain=[
                ('x_studio_producto', 'in', chunk),
                ('x_studio_fecha_desde', '>=', fecha_desde),
            ],
            fields=['x_studio_producto', 'x_studio_qty', 'x_studio_margin_total'],
        )
        margen_recs.extend(m)
    print(f"  {len(margen_recs)} registros de margen consultados")

    margen_agg = defaultdict(lambda: {'qty': 0.0, 'margin': 0.0})
    for r in margen_recs:
        if not r.get('x_studio_producto'):
            continue
        pid = r['x_studio_producto'][0]
        margen_agg[pid]['qty'] += r.get('x_studio_qty') or 0
        margen_agg[pid]['margin'] += r.get('x_studio_margin_total') or 0

    margen_unit_canon = {}
    for pid, agg in margen_agg.items():
        if agg['qty'] > 0:
            margen_unit_canon[pid] = agg['margin'] / agg['qty']
    print(f"  {len(margen_unit_canon)} productos con margen canon (qty>0)")

    def get_margen(pid: int) -> tuple[float, str]:
        if pid in margen_unit_canon:
            return margen_unit_canon[pid], 'canon'
        p = prod_info.get(pid)
        if p:
            fallback = (p.get('list_price') or 0) - (p.get('standard_price') or 0)
            if fallback > 0:
                return fallback, 'list-std'
        return 0.0, 'sin_dato'

    # =====================================================
    # 4. team_id -> sala
    # =====================================================
    print("\n[4/7] Mapeo team_id -> sala...")
    team_ids_set = sorted({r['x_studio_team_id'][0] for r in si_all if r.get('x_studio_team_id')})
    cfgs = odoo.search_read(
        'pos.config',
        domain=[('crm_team_id', 'in', team_ids_set)],
        fields=['crm_team_id', 'name'],
    )
    team_to_sala = {}
    for c in cfgs:
        tid = c['crm_team_id'][0]
        sala = c['name'].split(' Caja ')[0].strip()
        team_to_sala.setdefault(tid, sala)
    salas_orden = sorted(team_to_sala.items(), key=lambda kv: kv[1])
    sala_cols = [s for _, s in salas_orden]
    print(f"  Salas: {sala_cols}")

    # =====================================================
    # 5. mu_categoria por sala + history flag
    # =====================================================
    print("\n[5/7] mu_categoria por (team, categoria) y historia...")
    # mu_categ_sala[team][categ] = suma de mu_week
    mu_categ_sala = defaultdict(lambda: defaultdict(float))
    # active_categ_sala[team][categ] = max(active_weeks_local) entre SKUs de la categ -> proxy historia
    max_aw_categ = defaultdict(lambda: defaultdict(int))
    for r in si_all:
        if not (r.get('x_studio_team_id') and r.get('x_studio_categ_id')):
            continue
        tid = r['x_studio_team_id'][0]
        cid = r['x_studio_categ_id'][0]
        mu = r.get('x_studio_mu_week') or 0
        aw = r.get('x_studio_active_weeks_local') or 0
        mu_categ_sala[tid][cid] += mu
        if aw > max_aw_categ[tid][cid]:
            max_aw_categ[tid][cid] = aw

    def mu_categ_target(target_tid: int, cid: int) -> float:
        if max_aw_categ[target_tid][cid] >= HIST_CATEG_MIN_WEEKS:
            return mu_categ_sala[target_tid][cid]
        # fallback bottom-N% otras salas con mu>0
        otras = [mu_categ_sala[t][cid] for t, _ in salas_orden
                 if t != target_tid and mu_categ_sala[t][cid] > 0]
        if not otras:
            return 0.0
        otras.sort()
        n_bottom = max(1, int(len(otras) * BOTTOM_FRAC))
        return mean(otras[:n_bottom])

    # =====================================================
    # 6. Calculo Priority Score por SKU
    # =====================================================
    print("\n[6/7] Priority Score por SKU...")
    filas = []
    for abc in abc_recs:
        pid = abc['x_studio_product_id'][0] if abc.get('x_studio_product_id') else None
        if pid not in prod_info:
            continue
        p = prod_info[pid]
        abc_letter = (abc.get('x_studio_abc') or '').upper()
        xyz_letter = (abc.get('x_studio_xyz') or '').upper()
        cid = abc['x_studio_categ_id'][0] if abc.get('x_studio_categ_id') else None
        margen_unit, margen_fuente = get_margen(pid)

        confidence = ABC_WEIGHT.get(abc_letter, 0.0) * XYZ_WEIGHT.get(xyz_letter, 0.0)

        # Para factor normalizado: usar salas con mu>0 y mu_categ>0
        shares = []
        for tid, _ in salas_orden:
            r = si_map.get((pid, tid))
            if r is None:
                continue
            mu_local = r.get('x_studio_mu_week') or 0
            if mu_local <= 0:
                continue
            mu_cat = mu_categ_sala[tid].get(cid, 0.0)
            if mu_cat <= 0:
                continue
            shares.append(mu_local / mu_cat)
        factor_normalizado = mean(shares) if shares else 0.0
        n_salas_factor = len(shares)
        conf_n = confidence_n_factor(n_salas_factor)

        row = {
            'rank_abcxyz': abc.get('x_studio_rank_abcxyz') or 99999,
            'sku': p.get('default_code') or '',
            'descripcion': p.get('name') or '',
            'categ': abc['x_studio_categ_id'][1].split(' / ')[-1] if abc.get('x_studio_categ_id') else '',
            'abc': abc_letter,
            'xyz': xyz_letter,
            'abcxyz': abc.get('x_studio_abcxyz') or '',
            'ciclo': abc.get('x_studio_ciclo_de_vida') or '',
            'importancia': abc.get('x_studio_importancia') or '',
            'mu_global': round(abc.get('x_studio_mu_week') or 0, 1),
            'margen_unit': round(margen_unit, 0),
            'margen_fuente': margen_fuente,
            'uni_q4': abc.get('x_studio_uni_ltimo_trimestre') or 0,
        }

        salas_ok = 0
        salas_mu0 = 0
        salas_sin_reg = 0
        aw_total = 0
        aw_count = 0
        opp_uncapped = 0.0
        score_uncapped = 0.0

        for tid, sala in salas_orden:
            r = si_map.get((pid, tid))
            if r is None:
                # Sin registro = nunca probado
                row[sala] = None
                salas_sin_reg += 1
                if factor_normalizado > 0 and margen_unit > 0:
                    mu_cat_t = mu_categ_target(tid, cid) if cid else 0
                    mu_est = factor_normalizado * mu_cat_t * conf_n
                    opp = mu_est * margen_unit * 52
                    opp_uncapped += opp
                    score_uncapped += opp * confidence  # tried_penalty=1
                continue

            mu_local = r.get('x_studio_mu_week') or 0
            aw_local = r.get('x_studio_active_weeks_local') or 0
            row[sala] = round(mu_local, 1)
            aw_total += aw_local
            aw_count += 1

            if mu_local > 0:
                salas_ok += 1
                continue

            salas_mu0 += 1
            if factor_normalizado > 0 and margen_unit > 0:
                mu_cat_t = mu_categ_target(tid, cid) if cid else 0
                mu_est = factor_normalizado * mu_cat_t * conf_n
                opp = mu_est * margen_unit * 52
                tried = TRIED_PENALTY if aw_local > 0 else 1.00
                opp_uncapped += opp
                score_uncapped += opp * confidence * tried

        # Cap canon: oportunidad total <= mu_global * margen * 52 * growth_cap(xyz)
        mu_global_val = abc.get('x_studio_mu_week') or 0
        growth = GROWTH_CAP.get(xyz_letter, 1.5)
        opp_cap = mu_global_val * margen_unit * 52 * growth
        if opp_uncapped > opp_cap and opp_uncapped > 0:
            cap_ratio = opp_cap / opp_uncapped
            cap_aplicado = True
        else:
            cap_ratio = 1.0
            cap_aplicado = False
        opp_anual = opp_uncapped * cap_ratio
        priority_score = score_uncapped * cap_ratio

        row['salas_ok'] = salas_ok
        row['salas_mu0'] = salas_mu0
        row['salas_sin_reg'] = salas_sin_reg
        row['gap_total'] = 12 - salas_ok
        row['factor_norm'] = round(factor_normalizado, 4)
        row['n_salas_factor'] = n_salas_factor
        row['conf_n'] = round(conf_n, 2)
        row['opp_sin_cap'] = round(opp_uncapped, 0)
        row['oportunidad_anual_clp'] = round(opp_anual, 0)
        row['cap_aplicado'] = 'SI' if cap_aplicado else 'NO'
        row['confianza_clase'] = round(confidence, 3)
        row['priority_score'] = round(priority_score, 0)
        row['aw_prom'] = round(aw_total / aw_count, 1) if aw_count else 0

        # Recomendacion
        if row['gap_total'] == 0:
            row['recomendacion'] = 'OK'
        elif abc_letter == 'A' and row['gap_total'] >= 7:
            row['recomendacion'] = 'EXPANSION MASIVA'
        elif abc_letter in ('A', 'B') and 1 <= row['gap_total'] <= 2:
            row['recomendacion'] = 'TERMINAR COBERTURA'
        elif row['salas_mu0'] >= 5 and row['aw_prom'] > 0:
            row['recomendacion'] = 'INVESTIGAR FRACASO'
        elif xyz_letter == 'Z' and row['gap_total'] >= 6:
            row['recomendacion'] = 'BAJA CONFIANZA'
        else:
            row['recomendacion'] = 'REVISAR'

        filas.append(row)

    df = pd.DataFrame(filas)
    df = df.sort_values('priority_score', ascending=False).reset_index(drop=True)

    col_order = [
        'rank_abcxyz', 'sku', 'descripcion', 'categ',
        'abc', 'xyz', 'abcxyz', 'ciclo', 'importancia',
        'mu_global', 'margen_unit', 'margen_fuente', 'uni_q4',
    ] + sala_cols + [
        'salas_ok', 'salas_mu0', 'salas_sin_reg', 'gap_total', 'aw_prom',
        'factor_norm', 'n_salas_factor', 'conf_n',
        'opp_sin_cap', 'oportunidad_anual_clp', 'cap_aplicado',
        'confianza_clase', 'priority_score',
        'recomendacion',
    ]
    df = df[col_order]

    # =====================================================
    # 7. Excel
    # =====================================================
    print("\n[7/7] Generando Excel...")
    fname = f"Cobertura_ABCXYZ_canon_{date.today().isoformat()}.xlsx"
    out = Path.home() / 'Desktop' / fname
    # Si el archivo esta abierto, agregar timestamp incremental
    if out.exists():
        from datetime import datetime
        ts = datetime.now().strftime('%H%M')
        out = Path.home() / 'Desktop' / f"Cobertura_ABCXYZ_canon_{date.today().isoformat()}_{ts}.xlsx"

    # Hoja resumen
    resumen_rows = [
        ['Total SKUs analizados', len(df)],
        ['SKUs con cobertura completa (gap=0)', int((df['gap_total'] == 0).sum())],
        ['SKUs con gap 1-2 salas', int(((df['gap_total'] >= 1) & (df['gap_total'] <= 2)).sum())],
        ['SKUs con gap 3-6 salas', int(((df['gap_total'] >= 3) & (df['gap_total'] <= 6)).sum())],
        ['SKUs con gap 7-11 salas', int(((df['gap_total'] >= 7) & (df['gap_total'] <= 11)).sum())],
        ['SKUs sin cobertura (gap=12)', int((df['gap_total'] == 12).sum())],
        ['', ''],
        ['Oportunidad total anual con cap (CLP)', f"{int(df['oportunidad_anual_clp'].sum()):,}"],
        ['Oportunidad total anual SIN cap (CLP)', f"{int(df['opp_sin_cap'].sum()):,}"],
        ['SKUs con cap aplicado', int((df['cap_aplicado'] == 'SI').sum())],
        ['Priority score total', f"{int(df['priority_score'].sum()):,}"],
        ['', ''],
        ['SKUs con confianza factor=1.00 (>=5 salas)', int((df['conf_n'] == 1.00).sum())],
        ['SKUs con confianza factor=0.75 (3-4 salas)', int((df['conf_n'] == 0.75).sum())],
        ['SKUs con confianza factor=0.50 (2 salas)', int((df['conf_n'] == 0.50).sum())],
        ['SKUs con confianza factor=0.30 (1 sala)', int((df['conf_n'] == 0.30).sum())],
        ['SKUs sin factor calculable (0 salas)', int((df['conf_n'] == 0.00).sum())],
        ['', ''],
        ['SKUs con margen canon', int((df['margen_fuente'] == 'canon').sum())],
        ['SKUs con margen fallback list-std', int((df['margen_fuente'] == 'list-std').sum())],
        ['SKUs sin dato de margen', int((df['margen_fuente'] == 'sin_dato').sum())],
    ]
    df_resumen = pd.DataFrame(resumen_rows, columns=['Metrica', 'Valor'])

    # Top categorias por oportunidad
    top_categ = (
        df.groupby('categ')
        .agg(n_skus=('sku', 'count'),
             gap_prom=('gap_total', 'mean'),
             oportunidad=('oportunidad_anual_clp', 'sum'),
             priority=('priority_score', 'sum'))
        .sort_values('priority', ascending=False)
        .head(20)
        .round(2)
        .reset_index()
    )

    # Distribucion recomendacion
    dist_rec = df['recomendacion'].value_counts().reset_index()
    dist_rec.columns = ['recomendacion', 'n_skus']

    with pd.ExcelWriter(out, engine='openpyxl') as w:
        df.to_excel(w, sheet_name='Cobertura', index=False)
        df_resumen.to_excel(w, sheet_name='Resumen', index=False, startrow=0)
        dist_rec.to_excel(w, sheet_name='Resumen', index=False,
                          startrow=len(df_resumen) + 2)
        top_categ.to_excel(w, sheet_name='Resumen', index=False,
                           startrow=len(df_resumen) + len(dist_rec) + 5)

    print(f"\nOK: {out}")
    print(f"\nTop 15 por priority_score:")
    print(df.head(15)[['rank_abcxyz', 'sku', 'descripcion', 'abcxyz',
                       'mu_global', 'margen_unit', 'gap_total',
                       'oportunidad_anual_clp', 'priority_score',
                       'recomendacion']].to_string(index=False))

    print(f"\nDistribucion recomendacion:")
    print(dist_rec.to_string(index=False))


if __name__ == '__main__':
    main()
