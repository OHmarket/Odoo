"""
Re-evaluacion del backtest CSV (3) excluyendo SKU-semana-team con quiebre
de stock confirmado en x_stock_balance_daily.

Logica:
- Si (pid, team_id, week_start) tiene >=1 fila con stockout=True (o balance<=0)
  en x_stock_balance_daily durante la semana, la fila del backtest queda
  excluida. La "venta real" de esa celda estuvo censurada por falta de stock,
  asi que cualquier error vs forecast es ruido.
- Se reporta el universo limpio (sin quiebres) y se compara WAPE/BIAS y
  top 20 vs el universo original.
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

pd.set_option("display.float_format", lambda x: f"{x:,.1f}")
pd.set_option("display.width", 280)
pd.set_option("display.max_columns", 30)
pd.set_option("display.max_colwidth", 55)


def _extract_code(prod_str):
    m = re.match(r'\[([^\]]+)\]', str(prod_str or ''))
    return m.group(1) if m else None


def _sub_cat(s):
    parts = str(s or "").split(" / ")
    return parts[2] if len(parts) >= 3 else parts[-1] if parts else ""


def _iso_monday(d):
    return d - timedelta(days=d.weekday())


def main():
    # ------------------------------------------------------------
    # 1. Cargar backtest filtrado (ruido)
    # ------------------------------------------------------------
    df = pd.read_csv(CSV, low_memory=False, encoding="latin-1")
    for c in ["forecast_qty", "real_qty", "abs_error_qty"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    df = df[df["team_id"].fillna("").apply(lambda t: not any(x in t for x in EXCLUIR_TEAM))]
    df = df[df["categ_id"].fillna("").apply(lambda c: not any(x in c for x in EXCLUIR_CATEG))]
    df['code'] = df['product_id'].apply(_extract_code)
    df['target_week_start_dt'] = pd.to_datetime(df['target_week_start']).dt.date
    print(f"Filas backtest filtrado: {len(df):,}")
    print(f"  SKUs distintos: {df['code'].nunique():,}")
    print(f"  Team labels distintos: {df['team_id'].nunique()}")

    # ------------------------------------------------------------
    # 2. Mapeos team_label -> team_id (int) y code -> pid
    # ------------------------------------------------------------
    odoo = OdooReader()
    print(f"\nConectado: {odoo}")

    # Mapeo team
    pos_configs = odoo.search_read(
        'pos.config',
        domain=[],
        fields=['id', 'name', 'crm_team_id'],
    )
    name_to_team = {}
    for pc in pos_configs:
        cm = pc.get('crm_team_id')
        tid = cm[0] if isinstance(cm, (list, tuple)) else cm
        if tid:
            name_to_team[pc['name']] = tid
    # CSV usa "Ventas <local>"; pos.config.name es "<local>" (variable). Hacer
    # match por prefix-strip del label CSV.
    def _label_to_tid(label):
        # Prueba con label completo y label sin prefijo "Ventas "
        if label in name_to_team:
            return name_to_team[label]
        stripped = re.sub(r'^Ventas\s+', '', label or '')
        for n, t in name_to_team.items():
            if n.strip() == stripped or stripped in n:
                return t
        return None

    df['team_id_int'] = df['team_id'].apply(_label_to_tid)
    missing_teams = df[df['team_id_int'].isna()]['team_id'].unique()
    if len(missing_teams):
        print(f"  *** Team labels sin match: {missing_teams} ***")
    df = df[df['team_id_int'].notna()].copy()
    df['team_id_int'] = df['team_id_int'].astype(int)

    # Mapeo pid
    codes = df['code'].dropna().unique().tolist()
    print(f"  Codigos a resolver: {len(codes):,}")
    prods_all = []
    BATCH = 1000
    for i in range(0, len(codes), BATCH):
        batch = codes[i:i+BATCH]
        prods = odoo.search_read(
            'product.product',
            domain=[('default_code', 'in', batch)],
            fields=['id', 'default_code'],
        )
        prods_all.extend(prods)
    code_to_pid = {p['default_code']: p['id'] for p in prods_all}
    df['pid'] = df['code'].map(code_to_pid)
    n_no_pid = df['pid'].isna().sum()
    print(f"  SKUs sin pid resoluto: {n_no_pid:,}")
    df = df[df['pid'].notna()].copy()
    df['pid'] = df['pid'].astype(int)
    print(f"  Filas con (team, pid) resueltos: {len(df):,}")

    # ------------------------------------------------------------
    # 3. Pull x_stock_balance_daily para las 3 sem backtest x universo
    # ------------------------------------------------------------
    pids_universo = df['pid'].unique().tolist()
    teams_universo = df['team_id_int'].unique().tolist()
    fecha_min = min(BT_WEEKS)
    fecha_max = max(BT_WEEKS) + timedelta(days=6)
    print(f"\nPull x_stock_balance_daily {fecha_min} -> {fecha_max}")
    print(f"  pids: {len(pids_universo):,}  teams: {len(teams_universo)}")

    # Pull en batches por pid (evita query gigante)
    quiebre_rows = []
    BATCH_PID = 200
    for i in range(0, len(pids_universo), BATCH_PID):
        batch = pids_universo[i:i+BATCH_PID]
        rows = odoo.search_read(
            'x_stock_balance_daily',
            domain=[
                ('x_studio_product_id', 'in', batch),
                ('x_studio_team_id', 'in', teams_universo),
                ('x_studio_date', '>=', fecha_min.strftime('%Y-%m-%d')),
                ('x_studio_date', '<=', fecha_max.strftime('%Y-%m-%d')),
            ],
            fields=['x_studio_product_id', 'x_studio_team_id', 'x_studio_date',
                    'x_studio_qty_balance', 'x_studio_stockout', 'x_studio_stockout_partial'],
        )
        quiebre_rows.extend(rows)
        print(f"  pids {i}-{i+len(batch)}: +{len(rows):,} filas (acc {len(quiebre_rows):,})")

    print(f"\nTotal filas x_stock_balance_daily registradas: {len(quiebre_rows):,}")
    if not quiebre_rows:
        print("  *** Sin data de stock en el rango ***")
        return

    df_q = pd.DataFrame(quiebre_rows)
    df_q['pid'] = df_q['x_studio_product_id'].apply(lambda v: v[0] if isinstance(v, (list, tuple)) else v)
    df_q['team_id_int'] = df_q['x_studio_team_id'].apply(lambda v: v[0] if isinstance(v, (list, tuple)) else v)
    df_q['date'] = pd.to_datetime(df_q['x_studio_date']).dt.date
    df_q['week_start'] = df_q['date'].apply(_iso_monday)
    df_q['stockout_any'] = (
        df_q['x_studio_stockout'].fillna(False)
        | df_q['x_studio_stockout_partial'].fillna(False)
        | (pd.to_numeric(df_q['x_studio_qty_balance'], errors='coerce').fillna(0) <= 0)
    )

    # ------------------------------------------------------------
    # 4. Marcar filas backtest con quiebre en esa (pid, team, week)
    # ------------------------------------------------------------
    # Identificar el set de tuplas (pid, team_id_int, week_start) con >=1
    # dia stockout cualquiera (incluye partial y balance<=0)
    quiebre_set = set(
        df_q[df_q['stockout_any']]
        .groupby(['pid', 'team_id_int', 'week_start']).size().index.tolist()
    )
    # quiebre_set es set de tuplas (pid, team, week)
    print(f"  Tuplas (pid, team, week) con quiebre: {len(quiebre_set):,}")

    # Marcar el backtest
    df['quiebre'] = df.apply(
        lambda r: (r['pid'], r['team_id_int'], r['target_week_start_dt']) in quiebre_set,
        axis=1,
    )

    n_quiebre = df['quiebre'].sum()
    print(f"\n  Filas backtest con quiebre: {n_quiebre:,} ({n_quiebre/len(df)*100:.1f}%)")

    # ------------------------------------------------------------
    # 5. Headlines: con vs sin quiebre
    # ------------------------------------------------------------
    def _headline(d, label):
        real = d['real_qty'].sum()
        fcst = d['forecast_qty'].sum()
        abs_err = d['abs_error_qty'].sum()
        wape = abs_err / real * 100 if real else 0
        bias = (real - fcst) / real * 100 if real else 0
        print(f"  {label:>30s} | n={len(d):>6} real={real:>8,.0f} fcst={fcst:>8,.0f} abs_err={abs_err:>8,.0f} WAPE={wape:5.1f}% BIAS={bias:+5.1f}%")

    print(f"\n========== HEADLINES ==========")
    _headline(df, "TOTAL (con quiebres)")
    df_clean = df[~df['quiebre']].copy()
    _headline(df_clean, "TOTAL (SIN quiebres)")
    df_quebrado = df[df['quiebre']].copy()
    _headline(df_quebrado, "Solo quiebres (excluidos)")

    print(f"\n  Por semana (SIN quiebres):")
    for wk in BT_WEEKS:
        sub = df_clean[df_clean['target_week_start_dt'] == wk]
        _headline(sub, f"  {wk}")

    print(f"\n  Por semana (con quiebres - excluidas):")
    for wk in BT_WEEKS:
        sub = df_quebrado[df_quebrado['target_week_start_dt'] == wk]
        _headline(sub, f"  {wk}")

    # ------------------------------------------------------------
    # 6. Top 20 sin quiebres
    # ------------------------------------------------------------
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

    top20_clean = agg.sort_values("sum_abs_err", ascending=False).head(20)
    print(f"\n========== TOP 20 SIN QUIEBRES ==========")
    cols = ["product_id", "sub_cat", "abcxyz", "regimen", "n_filas",
            "sum_real", "sum_fcst", "sum_abs_err", "wape_pct", "bias_pct"]
    print(top20_clean[cols].to_string(index=False))

    # ------------------------------------------------------------
    # 7. Comparacion ranking: cambios vs top 20 original
    # ------------------------------------------------------------
    agg_orig = df.groupby("product_id").agg(
        sum_abs_err=("abs_error_qty", "sum"),
    ).reset_index().sort_values("sum_abs_err", ascending=False)
    top20_orig = set(agg_orig.head(20)["product_id"].tolist())
    top20_clean_set = set(top20_clean["product_id"].tolist())

    salieron = top20_orig - top20_clean_set
    entraron = top20_clean_set - top20_orig
    print(f"\n========== CAMBIOS top 20 original vs sin quiebres ==========")
    print(f"  SALIERON ({len(salieron)}):")
    for p in salieron:
        old_err = agg_orig[agg_orig['product_id'] == p]['sum_abs_err'].iloc[0]
        print(f"    [old_err={old_err:>6,.0f}]  {p[:80]}")
    print(f"  ENTRARON ({len(entraron)}):")
    for p in entraron:
        new_err = top20_clean[top20_clean['product_id'] == p]['sum_abs_err'].iloc[0]
        print(f"    [new_err={new_err:>6,.0f}]  {p[:80]}")

    OUT = Path(__file__).parent / "backtest_sin_quiebres.csv"
    top20_clean[cols].to_csv(OUT, index=False, encoding="utf-8")
    print(f"\nCSV: {OUT}")


if __name__ == "__main__":
    main()
