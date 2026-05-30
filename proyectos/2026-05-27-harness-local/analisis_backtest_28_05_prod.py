"""
Analisis backtest productivo 28-05 (CSV exportado de Odoo).

Ventana: 2026-05-04 a 2026-05-18 (3 sem cerradas, cutoffs 03/10/17 mayo).
Cubre las 3 ultimas semanas del backtest local 10w.

Compara WAPE/BIAS productivo vs:
  - mismas 3 semanas del baseline v3.46 LOCAL (sin calib)
  - mismas 3 semanas del local v3.47 simulado con factor M1b

Para evaluar si el motor v3.47 productivo bajo BIAS como predijo el harness.
"""
from __future__ import annotations
from pathlib import Path
import pandas as pd
import warnings
warnings.filterwarnings('ignore')

RESULTS = Path(__file__).parent / "resultados"
CACHE = Path(__file__).parent / "cache"
CSV = Path("OH Forecast Backtest (x_forecast_backtest) 28-05.csv").resolve()
if not CSV.exists():
    CSV = Path(__file__).parent.parent.parent / "OH Forecast Backtest (x_forecast_backtest) 28-05.csv"


def metrics(df, fcst='forecast_qty', real='real_qty'):
    r = df[real].sum()
    if r <= 0:
        return {'n': int(len(df)), 'real': 0.0, 'fcst': 0.0, 'WAPE': 0.0, 'BIAS': 0.0}
    f = df[fcst].sum()
    ae = (df[fcst] - df[real]).abs().sum()
    err = (df[real] - df[fcst]).sum()
    return {
        'n': int(len(df)),
        'real': float(r),
        'fcst': float(f),
        'WAPE': round(ae / r * 100, 2),
        'BIAS': round(err / r * 100, 2),
    }


def main():
    print(f"Leyendo CSV: {CSV}")
    prod = pd.read_csv(CSV, encoding='utf-8', low_memory=False)
    print(f"  {len(prod):,} filas productivo")

    # categ_id viene como string 'Bebidas Alcoholicas / Cervezas / ...'
    # Filtros: excluir cigarros/snack/impulso
    EXCL_KW = ['Cigarrillos', 'Cigarros', 'Tabaco', 'Snack', 'Impulso']
    excl_mask = prod['categ_id'].fillna('').str.contains('|'.join(EXCL_KW), case=False, na=False)
    cerv_mask = prod['categ_id'].fillna('').str.contains('Cervezas', case=False, na=False)

    # No tenemos flag de quiebre en este CSV - filtramos por method != min_stock_or_manual
    # (forecast_model_code='min_stock_or_manual' implica REG-0/3/6 sin forecast util)
    no_min_mask = ~(prod['forecast_model_code'] == 'min_stock_or_manual')

    # Universo limpio: no excluido + no min_stock_or_manual
    clean_mask = (~excl_mask) & no_min_mask

    # ----- Productivo overall -----
    print("\nPRODUCTIVO 28-05 (3 sem: 2026-05-04, 11, 18)")
    print("-" * 100)
    by_week = []
    for w in sorted(prod['target_week_start'].unique()):
        sub = prod[prod['target_week_start'] == w]
        m_all = metrics(sub)
        sub_clean = sub[clean_mask.loc[sub.index]]
        m_clean = metrics(sub_clean)
        sub_cerv = sub[cerv_mask.loc[sub.index]]
        m_cerv = metrics(sub_cerv)
        print(f"  {w}: TODO WAPE={m_all['WAPE']:>5.2f} BIAS={m_all['BIAS']:>+6.2f} (n={m_all['n']:,})  "
              f"| LIMPIO WAPE={m_clean['WAPE']:>5.2f} BIAS={m_clean['BIAS']:>+6.2f}  "
              f"| CERV WAPE={m_cerv['WAPE']:>5.2f} BIAS={m_cerv['BIAS']:>+6.2f}")
        by_week.append({'w': w, 'todo': m_all, 'clean': m_clean, 'cerv': m_cerv})

    # Total 3 semanas
    print(f"\nTOTAL 3 sem (productivo, sin filtros): ", end='')
    m_total = metrics(prod)
    print(f"WAPE={m_total['WAPE']:>5.2f} BIAS={m_total['BIAS']:>+6.2f} (n={m_total['n']:,})")
    print(f"TOTAL 3 sem (sin cig/snack, sin min_stock): ", end='')
    m_total_clean = metrics(prod[clean_mask])
    print(f"WAPE={m_total_clean['WAPE']:>5.2f} BIAS={m_total_clean['BIAS']:>+6.2f}")
    print(f"TOTAL 3 sem (CERVEZAS): ", end='')
    m_total_cerv = metrics(prod[cerv_mask])
    print(f"WAPE={m_total_cerv['WAPE']:>5.2f} BIAS={m_total_cerv['BIAS']:>+6.2f}")

    # ----- Comparar contra LOCAL baseline mismas 3 sem -----
    print("\n" + "=" * 100)
    print("COMPARATIVA contra baseline LOCAL v3.46 (mismas 3 sem)")
    print("=" * 100)
    if not (RESULTS / "simulacion_final_v347_detail.parquet").exists():
        print("  No hay detail.parquet local - omito comparativa.")
        return

    local = pd.read_parquet(RESULTS / "simulacion_final_v347_detail.parquet")
    local = local[local['config'] == 'baseline_or_calib'].copy()
    local['target_week_str'] = local['target_week'].astype(str)
    weeks_prod = set(prod['target_week_start'].astype(str).unique())
    local_3w = local[local['target_week_str'].isin(weeks_prod)].copy()
    print(f"  local baseline 3 sem: {len(local_3w):,} filas")

    cats = pd.read_parquet(CACHE / "catalog_categories.parquet")
    excl_cat_ids = set(cats[cats['complete_name'].str.contains(
        '|'.join(EXCL_KW), case=False, na=False
    )]['categ_id_id'])
    cerv_cat_ids = set(cats[cats['complete_name'].str.contains(
        'Cervezas', case=False, na=False
    )]['categ_id_id'])

    no_q = ~local_3w['is_quiebre']
    no_cig = ~local_3w['categ_id'].isin(excl_cat_ids)
    is_cerv = local_3w['categ_id'].isin(cerv_cat_ids)
    clean_local = no_q & no_cig

    print("\nLOCAL baseline v3.46 - mismas 3 sem:")
    m_local_clean = metrics(local_3w[clean_local], fcst='mu_week', real='qty_sold')
    m_local_cerv = metrics(local_3w[is_cerv & no_q], fcst='mu_week', real='qty_sold')
    print(f"  LIMPIO total: WAPE={m_local_clean['WAPE']:>5.2f} BIAS={m_local_clean['BIAS']:>+6.2f} (n={m_local_clean['n']:,})")
    print(f"  CERVEZAS:     WAPE={m_local_cerv['WAPE']:>5.2f} BIAS={m_local_cerv['BIAS']:>+6.2f}")

    print("\nCOMPARATIVA productivo vs local:")
    print(f"  TOTAL LIMPIO  | productivo WAPE={m_total_clean['WAPE']:>5.2f} BIAS={m_total_clean['BIAS']:>+6.2f}"
          f"  | local v3.46 WAPE={m_local_clean['WAPE']:>5.2f} BIAS={m_local_clean['BIAS']:>+6.2f}"
          f"  | d_WAPE={m_total_clean['WAPE']-m_local_clean['WAPE']:+.2f}pp d_BIAS={m_total_clean['BIAS']-m_local_clean['BIAS']:+.2f}pp")
    print(f"  CERVEZAS      | productivo WAPE={m_total_cerv['WAPE']:>5.2f} BIAS={m_total_cerv['BIAS']:>+6.2f}"
          f"  | local v3.46 WAPE={m_local_cerv['WAPE']:>5.2f} BIAS={m_local_cerv['BIAS']:>+6.2f}"
          f"  | d_WAPE={m_total_cerv['WAPE']-m_local_cerv['WAPE']:+.2f}pp d_BIAS={m_total_cerv['BIAS']-m_local_cerv['BIAS']:+.2f}pp")

    print("\n" + "=" * 100)
    print("INTERPRETACION")
    print("=" * 100)
    d_bias_total = m_total_clean['BIAS'] - m_local_clean['BIAS']
    if d_bias_total < -5:
        print(f"  Productivo BIAS bajo {abs(d_bias_total):.1f}pp vs baseline local v3.46 -> ")
        print(f"  Motor v3.47 con calib esta funcionando.")
    elif abs(d_bias_total) <= 5:
        print(f"  BIAS similar entre productivo y baseline local (d={d_bias_total:+.1f}pp).")
        print(f"  Posibles motivos:")
        print(f"   1. Motor v3.47 aun no copiado (corriendo v3.46)")
        print(f"   2. Calib aplico pero factores muy chicos en estas 3 sem")
        print(f"   3. Categ calib ctx vacio porque target_date posterior a factores")
    else:
        print(f"  Productivo BIAS sube {d_bias_total:+.1f}pp vs baseline -> revisar.")


if __name__ == "__main__":
    main()
