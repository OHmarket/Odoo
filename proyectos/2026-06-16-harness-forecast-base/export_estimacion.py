"""
export_estimacion — Exporta el run vigente de x_hm_si_forecast (estimacion de
demanda productiva) via XML-RPC read-only, en chunks (no carga el POS). Escribe:
  resultados/estimacion_<fecha>.parquet  (tecnico, para analisis)
  resultados/estimacion_<fecha>.csv       (Excel es-CL: sep=';', decimal=',', utf-8-sig)
"""
from __future__ import annotations
import sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader  # noqa: E402

MODEL = 'x_hm_si_forecast'
FIELDS = [
    'x_studio_product_id', 'x_studio_team_id', 'x_studio_categ_id',
    'x_studio_week_start', 'x_studio_mu_week', 'x_studio_sigma_week',
    'x_studio_forecast_model_code', 'x_studio_series_type', 'x_studio_ciclo_de_vida',
]
CHUNK = 2000


def m2o(v):
    return v[1] if isinstance(v, (list, tuple)) and len(v) == 2 else v


def m2o_id(v):
    return v[0] if isinstance(v, (list, tuple)) and len(v) == 2 else None


def main():
    o = OdooReader()
    total = o.search_count(MODEL)
    print(f"{MODEL}: {total} filas. Descargando en chunks de {CHUNK}...")
    rows = []
    off = 0
    while off < total:
        part = o.search_read(MODEL, domain=[], fields=FIELDS, limit=CHUNK, offset=off, order='id')
        if not part:
            break
        rows.extend(part)
        off += len(part)
        print(f"  {off}/{total}")
    df = pd.DataFrame(rows)
    # desempaquetar many2one a id + nombre
    for col in ['x_studio_product_id', 'x_studio_team_id', 'x_studio_categ_id']:
        if col in df.columns:
            df[col + '_id'] = df[col].apply(m2o_id)
            df[col] = df[col].apply(m2o)
    out_dir = Path(__file__).resolve().parent / "resultados"
    out_dir.mkdir(exist_ok=True)
    tag = pd.Timestamp.utcnow().strftime('%Y%m%d')
    pq = out_dir / f"estimacion_{tag}.parquet"
    df.to_parquet(pq, index=False)
    csv = out_dir / f"estimacion_{tag}.csv"
    df.to_csv(csv, sep=';', decimal=',', encoding='utf-8-sig', index=False)
    print(f"\nfilas={len(df)}  mu_sum={df['x_studio_mu_week'].sum():.0f}  "
          f"sigma_sum={df['x_studio_sigma_week'].sum():.0f}")
    print("por series_type:")
    g = df.groupby('x_studio_series_type').agg(
        n=('x_studio_mu_week', 'size'),
        mu_sum=('x_studio_mu_week', 'sum'),
        sigma_sum=('x_studio_sigma_week', 'sum'))
    print(g.to_string())
    print(f"\n-> {pq}\n-> {csv}")


if __name__ == "__main__":
    main()
