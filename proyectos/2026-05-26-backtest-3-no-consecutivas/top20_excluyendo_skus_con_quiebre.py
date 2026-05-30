"""
Top 20 por error excluyendo los SKUs que tuvieron CUALQUIER quiebre
en alguna sala/semana de las 3 sem backtest. Mas conservador que
excluir solo SKU-semana-team con quiebre.

Si un SKU tuvo quiebre en al menos 1 (team, week) del backtest, se
excluye COMPLETO del top 20.
"""
from __future__ import annotations
import sys
import re
from pathlib import Path
from datetime import date, timedelta
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

CSV = Path(r"c:\Users\sanhu\Odoo\OH Forecast Backtest (x_forecast_backtest) (3).csv")
EXCLUIR_CATEG = ("Cervezas", "Cigarros", "Tabaco", "Snacks", "Impulsivos")
EXCLUIR_TEAM = ("Ventas San Jos",)
BT_WEEKS = [date(2026, 5, 4), date(2026, 5, 11), date(2026, 5, 18)]

pd.set_option("display.float_format", lambda x: f"{x:,.0f}")
pd.set_option("display.width", 260)
pd.set_option("display.max_columns", 20)
pd.set_option("display.max_colwidth", 65)


def _extract_code(s):
    m = re.match(r'\[([^\]]+)\]', str(s or ''))
    return m.group(1) if m else None


def _sub_cat(s):
    parts = str(s or "").split(" / ")
    return parts[2] if len(parts) >= 3 else parts[-1] if parts else ""


def main():
    # ----------------------------------------------------------
    # 1. Cargar backtest filtrado
    # ----------------------------------------------------------
    df = pd.read_csv(CSV, low_memory=False, encoding="latin-1")
    for c in ["forecast_qty", "real_qty", "abs_error_qty"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    df = df[df["team_id"].fillna("").apply(lambda t: not any(x in t for x in EXCLUIR_TEAM))]
    df = df[df["categ_id"].fillna("").apply(lambda c: not any(x in c for x in EXCLUIR_CATEG))]
    df['code'] = df['product_id'].apply(_extract_code)
    print(f"Universo: {len(df):,} filas, {df['code'].nunique():,} SKUs")

    # ----------------------------------------------------------
    # 2. Pids con quiebre en las 3 sem backtest
    # ----------------------------------------------------------
    odoo = OdooReader()
    print(f"Conectado: {odoo}")

    codes = df['code'].dropna().unique().tolist()
    pids_all = []
    BATCH = 1000
    for i in range(0, len(codes), BATCH):
        prods = odoo.search_read(
            'product.product',
            domain=[('default_code', 'in', codes[i:i+BATCH])],
            fields=['id', 'default_code'],
        )
        pids_all.extend(prods)
    code_to_pid = {p['default_code']: p['id'] for p in pids_all}
    pid_to_code = {v: k for k, v in code_to_pid.items()}
    pids_universo = list(code_to_pid.values())
    print(f"  SKUs resueltos a pid: {len(pids_universo):,}/{len(codes):,}")

    fecha_min = min(BT_WEEKS)
    fecha_max = max(BT_WEEKS) + timedelta(days=6)

    quiebre_rows = []
    for i in range(0, len(pids_universo), 200):
        batch = pids_universo[i:i+200]
        rows = odoo.search_read(
            'x_stock_balance_daily',
            domain=[
                ('x_studio_product_id', 'in', batch),
                ('x_studio_date', '>=', fecha_min.strftime('%Y-%m-%d')),
                ('x_studio_date', '<=', fecha_max.strftime('%Y-%m-%d')),
            ],
            fields=['x_studio_product_id', 'x_studio_stockout', 'x_studio_stockout_partial',
                    'x_studio_qty_balance'],
        )
        quiebre_rows.extend(rows)
    print(f"  Filas stock balance: {len(quiebre_rows):,}")

    if quiebre_rows:
        df_q = pd.DataFrame(quiebre_rows)
        df_q['pid'] = df_q['x_studio_product_id'].apply(lambda v: v[0] if isinstance(v, (list, tuple)) else v)
        df_q['stockout_any'] = (
            df_q['x_studio_stockout'].fillna(False)
            | df_q['x_studio_stockout_partial'].fillna(False)
            | (pd.to_numeric(df_q['x_studio_qty_balance'], errors='coerce').fillna(0) <= 0)
        )
        pids_con_quiebre = set(df_q[df_q['stockout_any']]['pid'].unique())
    else:
        pids_con_quiebre = set()
    codes_con_quiebre = {pid_to_code.get(p) for p in pids_con_quiebre if p in pid_to_code}
    print(f"  SKUs con AL MENOS 1 quiebre: {len(codes_con_quiebre):,}")

    # ----------------------------------------------------------
    # 3. Filtrar y top 20
    # ----------------------------------------------------------
    df_clean = df[~df['code'].isin(codes_con_quiebre)].copy()
    print(f"  Universo limpio: {len(df_clean):,} filas, {df_clean['code'].nunique():,} SKUs")

    agg = df_clean.groupby("product_id").agg(
        sum_real=("real_qty", "sum"),
        sum_fcst=("forecast_qty", "sum"),
        sum_abs_err=("abs_error_qty", "sum"),
        n_teams=("team_id", "nunique"),
        n_filas=("real_qty", "size"),
    ).reset_index()
    meta = df_clean.groupby("product_id").agg(
        categ_id=("categ_id", "first"),
        abcxyz=("abcxyz", "first"),
        regimen=("regimen", "first"),
    ).reset_index()
    agg = agg.merge(meta, on="product_id")
    agg["sub_cat"] = agg["categ_id"].apply(_sub_cat)
    safe_real = agg["sum_real"].where(agg["sum_real"] != 0, other=float("nan"))
    agg["wape_pct"] = (agg["sum_abs_err"] / safe_real * 100).round(0)
    agg["bias_pct"] = ((agg["sum_real"] - agg["sum_fcst"]) / safe_real * 100).round(0)
    agg["direccion"] = agg.apply(
        lambda r: 'SUB' if r['sum_real'] > r['sum_fcst']
                 else ('OVER' if r['sum_real'] < r['sum_fcst'] else 'OK'),
        axis=1,
    )

    top = agg.sort_values("sum_abs_err", ascending=False).head(20)

    cols = ["product_id", "sub_cat", "abcxyz", "regimen", "n_teams",
            "sum_real", "sum_fcst", "sum_abs_err", "wape_pct", "bias_pct", "direccion"]
    print(f"\n========== TOP 20 SIN SKUs con CUALQUIER quiebre ==========")
    print(top[cols].to_string(index=False))

    print(f"\n  TOTAL universo limpio: real={agg['sum_real'].sum():,.0f}  fcst={agg['sum_fcst'].sum():,.0f}  abs_err={agg['sum_abs_err'].sum():,.0f}")
    print(f"  TOP 20:                real={top['sum_real'].sum():,.0f}  fcst={top['sum_fcst'].sum():,.0f}  abs_err={top['sum_abs_err'].sum():,.0f}  (= {top['sum_abs_err'].sum()/agg['sum_abs_err'].sum()*100:.1f}% del error)")
    print(f"  TOP 20 direccion: SUB={(top['direccion']=='SUB').sum()}  OVER={(top['direccion']=='OVER').sum()}")

    OUT = Path(__file__).parent / "top20_excluyendo_skus_con_quiebre.csv"
    top[cols].to_csv(OUT, index=False, encoding="utf-8")
    print(f"\nCSV: {OUT}")


if __name__ == "__main__":
    main()
