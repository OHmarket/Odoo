"""
Para los TOP 20 SKUs con mayor error en backtest CSV (3), pull POS 16 sem
y arma tabla SKU x semana para ver el patron temporal de cada uno.

Filtro ruido: excluye Ventas San Jose + categorias ruido (Cervezas, Cigarros,
Tabaco, Snacks, Impulsivos) — consistente con analisis previos.

Tabla:
- Columnas izq: codigo SKU, sub-cat, abc, regimen
- Centro: 16 columnas semanales con qty real
- Derecha: avg pre-backtest (13 sem), avg backtest (3 sem), forecast suma,
  delta, lectura
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
WEEKS_BACK = 16
TODAY = date(2026, 5, 27)

EXCLUIR_CATEG = ("Cervezas", "Cigarros", "Tabaco", "Snacks", "Impulsivos")
EXCLUIR_TEAM = ("Ventas San Jos",)
BT_WEEKS = [date(2026, 5, 4), date(2026, 5, 11), date(2026, 5, 18)]

pd.set_option("display.float_format", lambda x: f"{x:,.0f}")
pd.set_option("display.width", 400)
pd.set_option("display.max_columns", 50)
pd.set_option("display.max_colwidth", 45)


def _iso_monday(d): return d - timedelta(days=d.weekday())


def _extract_code(prod_str):
    """De '[9407] CERVEZA STELLA ARTOIS BOTELLA UNIDAD 660 CC' -> '9407'."""
    m = re.match(r'\[([^\]]+)\]', str(prod_str or ''))
    return m.group(1) if m else None


def _sub_cat(s):
    parts = str(s or "").split(" / ")
    return parts[2] if len(parts) >= 3 else parts[-1] if parts else ""


def main():
    # ------------------------------------------------------------
    # 1. CSV: top 20 por error absoluto (filtrado ruido)
    # ------------------------------------------------------------
    df = pd.read_csv(CSV, low_memory=False, encoding="latin-1")
    for c in ["forecast_qty", "real_qty", "abs_error_qty"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    df = df[df["team_id"].fillna("").apply(lambda t: not any(x in t for x in EXCLUIR_TEAM))]
    df = df[df["categ_id"].fillna("").apply(lambda c: not any(x in c for x in EXCLUIR_CATEG))]

    agg = df.groupby("product_id").agg(
        sum_real=("real_qty", "sum"),
        sum_fcst=("forecast_qty", "sum"),
        sum_abs_err=("abs_error_qty", "sum"),
    ).reset_index()
    meta = df.groupby("product_id").agg(
        categ_id=("categ_id", "first"),
        abcxyz=("abcxyz", "first"),
        regimen=("regimen", "first"),
    ).reset_index()
    agg = agg.merge(meta, on="product_id")
    agg["sub_cat"] = agg["categ_id"].apply(_sub_cat)
    agg["bias_pct"] = ((agg["sum_real"] - agg["sum_fcst"]) / agg["sum_real"].where(agg["sum_real"] != 0, other=float("nan")) * 100).round(0)

    top20 = agg.sort_values("sum_abs_err", ascending=False).head(20).copy()
    top20["code"] = top20["product_id"].apply(_extract_code)
    print(f"Top 20 cargados desde CSV (3) filtrado ({len(agg)} SKUs en universo)")
    print(top20[["code", "sub_cat", "abcxyz", "regimen", "sum_real", "sum_fcst", "sum_abs_err", "bias_pct"]].to_string(index=False))

    codes = [c for c in top20["code"].tolist() if c]
    print(f"\nCodigos a pull: {len(codes)}")

    # ------------------------------------------------------------
    # 2. Pull POS 16 semanas para esos 20 SKUs (un solo query)
    # ------------------------------------------------------------
    odoo = OdooReader()
    print(f"Conectado: {odoo}")

    prods = odoo.search_read(
        'product.product',
        domain=[('default_code', 'in', codes)],
        fields=['id', 'default_code', 'name'],
    )
    code_to_pid = {p['default_code']: p['id'] for p in prods}
    pid_to_code = {p['id']: p['default_code'] for p in prods}
    pids = list(code_to_pid.values())
    missing_codes = set(codes) - set(code_to_pid.keys())
    print(f"  Resueltos: {len(pids)}/{len(codes)}")
    if missing_codes:
        print(f"  NO encontrados: {missing_codes}")

    week_now = _iso_monday(TODAY)
    start = week_now - timedelta(weeks=WEEKS_BACK)
    print(f"  Ventana: {start} -> {week_now}")

    lines = odoo.search_read(
        'pos.order.line',
        domain=[
            ('product_id', 'in', pids),
            ('order_id.date_order', '>=', start.strftime('%Y-%m-%d')),
            ('order_id.date_order', '<', week_now.strftime('%Y-%m-%d')),
            ('order_id.state', 'in', ['paid', 'done', 'invoiced']),
        ],
        fields=['qty', 'product_id', 'order_id'],
    )
    print(f"  pos.order.line: {len(lines):,}")

    df_lines = pd.DataFrame(lines)
    df_lines['pid'] = df_lines['product_id'].apply(lambda v: v[0] if isinstance(v, (list, tuple)) else v)
    df_lines['order_id_id'] = df_lines['order_id'].apply(lambda v: v[0] if isinstance(v, (list, tuple)) else v)

    order_ids = sorted(df_lines['order_id_id'].unique().tolist())
    print(f"  pos.order distintos: {len(order_ids):,} (pull en batches de 5000)")

    # Pull pos.order en batches para no exceder limites de XML-RPC
    orders_all = []
    BATCH = 5000
    for i in range(0, len(order_ids), BATCH):
        batch_ids = order_ids[i:i+BATCH]
        rows = odoo.search_read(
            'pos.order',
            domain=[('id', 'in', batch_ids)],
            fields=['date_order', 'crm_team_id'],
        )
        orders_all.extend(rows)

    df_orders = pd.DataFrame(orders_all)
    df_orders['team'] = df_orders['crm_team_id'].apply(
        lambda v: v[1] if isinstance(v, (list, tuple)) and v else 'SIN_TEAM'
    )
    df_orders['date_order_dt'] = pd.to_datetime(df_orders['date_order'])
    df_orders['week_start'] = df_orders['date_order_dt'].apply(lambda d: _iso_monday(d.date()))

    merged = df_lines.merge(
        df_orders[['id', 'week_start', 'team']],
        left_on='order_id_id', right_on='id', how='left',
    )
    # Excluir San Jose
    merged = merged[~merged['team'].fillna('').str.contains('San Jos')]
    merged['code'] = merged['pid'].map(pid_to_code)

    # ------------------------------------------------------------
    # 3. Pivot SKU x week
    # ------------------------------------------------------------
    pivot = merged.groupby(['code', 'week_start'])['qty'].sum().unstack(fill_value=0)
    pivot = pivot.reindex(columns=sorted(pivot.columns))

    # Asegurar todas las 16 semanas como columnas
    all_weeks = [week_now - timedelta(weeks=WEEKS_BACK - i) for i in range(WEEKS_BACK)]
    for w in all_weeks:
        if w not in pivot.columns:
            pivot[w] = 0
    pivot = pivot[sorted(pivot.columns)]

    # Anadir avg pre-backtest, avg backtest, forecast suma, gap
    code_to_meta = top20.set_index("code")
    bt_set = set(BT_WEEKS)
    pre_weeks = [w for w in pivot.columns if w not in bt_set]
    pivot['avg_pre'] = pivot[pre_weeks].mean(axis=1).round(0)
    pivot['avg_bt'] = pivot[BT_WEEKS].mean(axis=1).round(0)

    # Agregar forecast del backtest
    fcst_by_code = {}
    for _, r in top20.iterrows():
        fcst_by_code[r['code']] = round(r['sum_fcst'] / 3, 0)  # promedio por semana
    pivot['avg_fcst'] = pivot.index.map(fcst_by_code)
    pivot['delta_bt_vs_pre'] = (pivot['avg_bt'] - pivot['avg_pre']).round(0)
    pivot['delta_real_vs_fcst'] = (pivot['avg_bt'] - pivot['avg_fcst']).round(0)

    # Lectura automatica
    def _lectura(r):
        d_pre = r['delta_bt_vs_pre']
        d_fc = r['delta_real_vs_fcst']
        if abs(d_pre) > r['avg_pre'] * 0.30:  # subio/bajo >30% vs baseline
            if d_pre > 0:
                return 'subio en BT'
            return 'bajo en BT'
        if abs(d_fc) > r['avg_fcst'] * 0.30:
            if d_fc > 0:
                return 'fcst sub-pron'
            return 'fcst over-pron'
        return 'consistente'
    pivot['lectura'] = pivot.apply(_lectura, axis=1)

    # Adjuntar meta (sub_cat, abc, regimen)
    pivot = pivot.merge(code_to_meta[['sub_cat', 'abcxyz', 'regimen']], left_index=True, right_index=True)

    # Reordenar por error original (mismo orden top20)
    pivot = pivot.reindex(top20['code'].tolist())

    # ------------------------------------------------------------
    # 4. Print tabla
    # ------------------------------------------------------------
    print("\n========== TOP 20 — SERIE 16 SEM POS ==========")
    print("BT = 2026-05-04 (W18), 2026-05-11 (W19), 2026-05-18 (W20)")

    # Formato de columnas: solo MM-DD para fechas
    cols_left = ['sub_cat', 'abcxyz', 'regimen']
    cols_weeks = sorted([c for c in pivot.columns if isinstance(c, date)])
    cols_right = ['avg_pre', 'avg_bt', 'avg_fcst', 'delta_bt_vs_pre', 'delta_real_vs_fcst', 'lectura']

    display = pivot[cols_left + cols_weeks + cols_right].copy()
    display.columns = (
        cols_left
        + [f"{c.month:02d}-{c.day:02d}{'*' if c in bt_set else ''}" for c in cols_weeks]
        + cols_right
    )
    print(display.to_string())

    # ------------------------------------------------------------
    # 5. Resumen por lectura
    # ------------------------------------------------------------
    print("\n========== RESUMEN POR LECTURA ==========")
    print(pivot.groupby('lectura').size().to_string())

    OUT = Path(__file__).parent / "top20_serie_16sem.csv"
    display.to_csv(OUT, encoding="utf-8")
    print(f"\nCSV: {OUT}")


if __name__ == "__main__":
    main()
