"""
Confirma por que 9407 (STELLA 660) no aparece en top 20 limpio:
- Sin filtro categorias: aparece?
- Tiene quiebre en alguna sala/semana del backtest?
- En que ranking queda si solo excluimos SKUs con quiebre (sin filtrar cervezas)?
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
    df = pd.read_csv(CSV, low_memory=False, encoding="latin-1")
    for c in ["forecast_qty", "real_qty", "abs_error_qty"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    df = df[df["team_id"].fillna("").apply(lambda t: not any(x in t for x in EXCLUIR_TEAM))]
    df['code'] = df['product_id'].apply(_extract_code)

    # ----------------------------------------------------------
    # 1. 9407 en universo sin filtrar cervezas?
    # ----------------------------------------------------------
    print("=== 9407 en el CSV (sin filtrar cervezas) ===")
    sub = df[df['code'] == '9407']
    real = sub['real_qty'].sum()
    fcst = sub['forecast_qty'].sum()
    abs_err = sub['abs_error_qty'].sum()
    print(f"  filas: {len(sub)}  real={real:,.0f}  fcst={fcst:,.0f}  abs_err={abs_err:,.0f}")
    print(f"  categ: {sub['categ_id'].iloc[0] if not sub.empty else 'N/A'}")
    print(f"  bias: {(real-fcst)/real*100 if real else 0:+.1f}%  WAPE: {abs_err/real*100 if real else 0:.1f}%")

    # ----------------------------------------------------------
    # 2. 9407 tiene quiebre?
    # ----------------------------------------------------------
    odoo = OdooReader()
    prods = odoo.search_read('product.product', domain=[('default_code', '=', '9407')], fields=['id'])
    pid = prods[0]['id']
    print(f"\n=== Quiebre 9407 (pid={pid}) en sem backtest ===")
    fecha_min = min(BT_WEEKS)
    fecha_max = max(BT_WEEKS) + timedelta(days=6)
    rows = odoo.search_read(
        'x_stock_balance_daily',
        domain=[
            ('x_studio_product_id', '=', pid),
            ('x_studio_date', '>=', fecha_min.strftime('%Y-%m-%d')),
            ('x_studio_date', '<=', fecha_max.strftime('%Y-%m-%d')),
        ],
        fields=['x_studio_team_id', 'x_studio_date', 'x_studio_qty_balance',
                'x_studio_stockout', 'x_studio_stockout_partial'],
    )
    print(f"  filas registradas (eventos quiebre): {len(rows)}")
    if rows:
        for r in rows[:20]:
            team = r['x_studio_team_id'][1] if isinstance(r['x_studio_team_id'], (list, tuple)) else r['x_studio_team_id']
            print(f"    {r['x_studio_date']} team={team} balance={r['x_studio_qty_balance']:>5} stockout={r['x_studio_stockout']}")
    else:
        print("  *** SIN quiebres registrados — 9407 NO debería haber sido excluido por quiebre ***")

    # ----------------------------------------------------------
    # 3. Ranking 9407 sin filtro cervezas, sin excluir SKUs con quiebre
    # ----------------------------------------------------------
    print(f"\n=== Ranking 9407 (universo SIN filtrar cervezas, SIN excluir SKUs con quiebre) ===")
    agg = df.groupby("product_id").agg(
        sum_real=("real_qty", "sum"),
        sum_fcst=("forecast_qty", "sum"),
        sum_abs_err=("abs_error_qty", "sum"),
    ).reset_index().sort_values("sum_abs_err", ascending=False)
    agg['rank'] = range(1, len(agg) + 1)
    row_9407 = agg[agg['product_id'].str.contains('9407', na=False) & agg['product_id'].str.contains('STELLA')]
    print(row_9407.to_string(index=False))

    # ----------------------------------------------------------
    # 4. Top 20 sin filtrar cervezas, sin SKUs con quiebre
    # ----------------------------------------------------------
    print(f"\n=== Top 20 SIN filtrar cervezas pero SI excluyendo SKUs con quiebre ===")
    # Resolver pids del universo
    codes = df['code'].dropna().unique().tolist()
    pids_all = []
    for i in range(0, len(codes), 1000):
        prods = odoo.search_read(
            'product.product',
            domain=[('default_code', 'in', codes[i:i+1000])],
            fields=['id', 'default_code'],
        )
        pids_all.extend(prods)
    code_to_pid = {p['default_code']: p['id'] for p in pids_all}
    pid_to_code = {v: k for k, v in code_to_pid.items()}
    pids_universo = list(code_to_pid.values())

    # Quiebres
    quiebre_rows = []
    for i in range(0, len(pids_universo), 200):
        rs = odoo.search_read(
            'x_stock_balance_daily',
            domain=[
                ('x_studio_product_id', 'in', pids_universo[i:i+200]),
                ('x_studio_date', '>=', fecha_min.strftime('%Y-%m-%d')),
                ('x_studio_date', '<=', fecha_max.strftime('%Y-%m-%d')),
            ],
            fields=['x_studio_product_id', 'x_studio_stockout', 'x_studio_stockout_partial', 'x_studio_qty_balance'],
        )
        quiebre_rows.extend(rs)
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
    print(f"  SKUs con quiebre: {len(codes_con_quiebre):,} (de {len(codes):,})")
    print(f"  9407 en set quiebre? {'SI' if '9407' in codes_con_quiebre else 'NO'}")

    df_clean = df[~df['code'].isin(codes_con_quiebre)].copy()
    print(f"  Universo limpio: {len(df_clean):,} filas, {df_clean['code'].nunique():,} SKUs")

    agg2 = df_clean.groupby("product_id").agg(
        sum_real=("real_qty", "sum"),
        sum_fcst=("forecast_qty", "sum"),
        sum_abs_err=("abs_error_qty", "sum"),
    ).reset_index()
    meta = df_clean.groupby("product_id").agg(
        categ_id=("categ_id", "first"),
        abcxyz=("abcxyz", "first"),
        regimen=("regimen", "first"),
    ).reset_index()
    agg2 = agg2.merge(meta, on="product_id")
    agg2["sub_cat"] = agg2["categ_id"].apply(_sub_cat)
    safe_real = agg2["sum_real"].where(agg2["sum_real"] != 0, other=float("nan"))
    agg2["bias_pct"] = ((agg2["sum_real"] - agg2["sum_fcst"]) / safe_real * 100).round(0)
    agg2["direccion"] = agg2.apply(
        lambda r: 'SUB' if r['sum_real'] > r['sum_fcst']
                 else ('OVER' if r['sum_real'] < r['sum_fcst'] else 'OK'),
        axis=1,
    )
    top = agg2.sort_values("sum_abs_err", ascending=False).head(20)
    cols = ["product_id", "sub_cat", "abcxyz", "regimen",
            "sum_real", "sum_fcst", "sum_abs_err", "bias_pct", "direccion"]
    print(top[cols].to_string(index=False))


if __name__ == "__main__":
    main()
