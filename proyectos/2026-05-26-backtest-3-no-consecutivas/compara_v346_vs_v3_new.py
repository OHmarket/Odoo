"""
Compara backtest CSV (2) vs CSV (3).
- (2): v3.46 corrido 12:58 hoy
- (3): nuevo backtest corrido 15:48 hoy (post-migracion 5 SKUs cervezas)

Comparaciones:
1. Headline: WAPE/BIAS por semana, total fcst vs real (sin filtro y con filtro ruido).
2. Cambio en TOP 20 por error absoluto: cuales entran/salen.
3. Estado especifico de los 5 SKUs migrados (9407, 9413, 9958, 1726, 9430).
4. Cambio agregado por categoria: cervezas Premium / Importadas / Tradicionales.
"""
from __future__ import annotations
from pathlib import Path
import pandas as pd

CSV_OLD = Path(r"c:\Users\sanhu\Odoo\OH Forecast Backtest (x_forecast_backtest) (2).csv")
CSV_NEW = Path(r"c:\Users\sanhu\Odoo\OH Forecast Backtest (x_forecast_backtest) (3).csv")

EXCLUIR_CATEG = ("Cervezas", "Cigarros", "Tabaco", "Snacks", "Impulsivos")
EXCLUIR_TEAM = ("Ventas San Jos",)

SKUS_MIGRADOS = ['9407', '9413', '9958', '1726', '9430']

pd.set_option("display.float_format", lambda x: f"{x:,.1f}")
pd.set_option("display.width", 260)
pd.set_option("display.max_columns", 30)
pd.set_option("display.max_colwidth", 60)


def _load(path):
    df = pd.read_csv(path, low_memory=False, encoding="latin-1")
    for c in ["forecast_qty", "real_qty", "abs_error_qty", "error_qty", "mu_week_pre_bias"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    return df


def _filtrar_ruido(df):
    out = df.copy()
    out = out[out["team_id"].fillna("").apply(lambda t: not any(x in t for x in EXCLUIR_TEAM))]
    out = out[out["categ_id"].fillna("").apply(lambda c: not any(x in c for x in EXCLUIR_CATEG))]
    return out


def _headline(df, label):
    real = df["real_qty"].sum()
    fcst = df["forecast_qty"].sum()
    abs_err = df["abs_error_qty"].sum()
    wape = abs_err / real * 100 if real else 0
    bias = (real - fcst) / real * 100 if real else 0
    print(f"  {label:>20s} | n={len(df):>6} real={real:>8,.0f} fcst={fcst:>8,.0f} abs_err={abs_err:>8,.0f} WAPE={wape:5.1f}% BIAS={bias:+5.1f}%")


def _por_semana(df, label):
    print(f"\n  {label} por semana:")
    for wk, sub in df.groupby("target_week_start"):
        real = sub["real_qty"].sum()
        fcst = sub["forecast_qty"].sum()
        abs_err = sub["abs_error_qty"].sum()
        wape = abs_err / real * 100 if real else 0
        bias = (real - fcst) / real * 100 if real else 0
        print(f"    {wk}  n={len(sub):>5}  real={real:>7,.0f}  fcst={fcst:>7,.0f}  WAPE={wape:5.1f}%  BIAS={bias:+5.1f}%")


def main():
    df_old = _load(CSV_OLD)
    df_new = _load(CSV_NEW)
    print(f"OLD (v3.46 12:58): {len(df_old):,} filas")
    print(f"NEW (15:48):       {len(df_new):,} filas")

    # ----------------------------------------------------------
    # 1. Headline general
    # ----------------------------------------------------------
    print("\n========== 1. HEADLINE (TODOS los SKUs) ==========")
    _headline(df_old, "OLD v3.46")
    _headline(df_new, "NEW post-migracion")

    print("\n========== 1b. HEADLINE (filtrado ruido) ==========")
    old_f = _filtrar_ruido(df_old)
    new_f = _filtrar_ruido(df_new)
    _headline(old_f, "OLD filtrado")
    _headline(new_f, "NEW filtrado")
    _por_semana(old_f, "OLD filtrado")
    _por_semana(new_f, "NEW filtrado")

    # ----------------------------------------------------------
    # 2. Cambio TOP 20 por error absoluto (filtrado)
    # ----------------------------------------------------------
    def _top20(df, n=20):
        agg = df.groupby("product_id").agg(
            sum_real=("real_qty", "sum"),
            sum_fcst=("forecast_qty", "sum"),
            sum_abs_err=("abs_error_qty", "sum"),
        )
        return agg.sort_values("sum_abs_err", ascending=False).head(n)

    top_old = _top20(old_f)
    top_new = _top20(new_f)

    set_old = set(top_old.index)
    set_new = set(top_new.index)
    salieron = set_old - set_new
    entraron = set_new - set_old

    print(f"\n========== 2. TOP 20 CAMBIOS (filtrado) ==========")
    print(f"  SKUs que SALIERON del top 20 ({len(salieron)}):")
    for sku in salieron:
        old_err = top_old.loc[sku, 'sum_abs_err']
        # Donde quedaron en NEW?
        new_rank_df = df_new.groupby("product_id").agg(sum_abs_err=("abs_error_qty", "sum")).sort_values("sum_abs_err", ascending=False).reset_index()
        new_rank_df['rank'] = range(1, len(new_rank_df) + 1)
        new_row = new_rank_df[new_rank_df["product_id"] == sku]
        new_rank = new_row['rank'].iloc[0] if not new_row.empty else 'N/A'
        new_err = new_row['sum_abs_err'].iloc[0] if not new_row.empty else 0
        print(f"    [old_err={old_err:>6,.0f}]  ahora rank={new_rank} new_err={new_err:>6,.0f}  {sku[:70]}")

    print(f"\n  SKUs que ENTRARON al top 20 ({len(entraron)}):")
    for sku in entraron:
        new_err = top_new.loc[sku, 'sum_abs_err']
        old_rank_df = df_old.groupby("product_id").agg(sum_abs_err=("abs_error_qty", "sum")).sort_values("sum_abs_err", ascending=False).reset_index()
        old_rank_df['rank'] = range(1, len(old_rank_df) + 1)
        old_row = old_rank_df[old_rank_df["product_id"] == sku]
        old_rank = old_row['rank'].iloc[0] if not old_row.empty else 'N/A'
        old_err = old_row['sum_abs_err'].iloc[0] if not old_row.empty else 0
        print(f"    [new_err={new_err:>6,.0f}]  antes rank={old_rank} old_err={old_err:>6,.0f}  {sku[:70]}")

    # ----------------------------------------------------------
    # 3. Estado de los 5 SKUs migrados
    # ----------------------------------------------------------
    print(f"\n========== 3. SKUs MIGRADOS (5 cervezas, sin filtro) ==========")
    for code in SKUS_MIGRADOS:
        mask_old = df_old["product_id"].fillna("").str.contains(f"\\[{code}\\]", regex=True)
        mask_new = df_new["product_id"].fillna("").str.contains(f"\\[{code}\\]", regex=True)
        sub_old = df_old[mask_old]
        sub_new = df_new[mask_new]
        if sub_old.empty and sub_new.empty:
            print(f"\n  [{code}] sin filas en ningun CSV")
            continue
        nombre = sub_new["product_id"].iloc[0] if not sub_new.empty else sub_old["product_id"].iloc[0]
        cat_old = sub_old["categ_id"].iloc[0] if not sub_old.empty else "(no OLD)"
        cat_new = sub_new["categ_id"].iloc[0] if not sub_new.empty else "(no NEW)"
        print(f"\n  [{code}] {nombre}")
        print(f"    categ_id  OLD: {cat_old}")
        print(f"              NEW: {cat_new}")

        for name, sub in [("OLD", sub_old), ("NEW", sub_new)]:
            real = sub["real_qty"].sum()
            fcst = sub["forecast_qty"].sum()
            abs_err = sub["abs_error_qty"].sum()
            wape = abs_err / real * 100 if real else 0
            bias = (real - fcst) / real * 100 if real else 0
            print(f"    {name}: n={len(sub):>3} real={real:>5,.0f} fcst={fcst:>5,.0f} abs_err={abs_err:>5,.0f} WAPE={wape:5.1f}% BIAS={bias:+5.1f}%")

    # ----------------------------------------------------------
    # 4. Agregado por sub-categoria afectada
    # ----------------------------------------------------------
    print(f"\n========== 4. AGREGADO por sub-categoria (cervezas afectadas) ==========")
    def _sub_cat(s):
        parts = str(s or "").split(" / ")
        return parts[2] if len(parts) >= 3 else parts[-1] if parts else ""
    df_old["sub_cat"] = df_old["categ_id"].apply(_sub_cat)
    df_new["sub_cat"] = df_new["categ_id"].apply(_sub_cat)
    cats_interes = ["Cervezas Premium", "Cervezas Importadas", "Cervezas Tradicionales", "Cervezas Promoción"]
    for c in cats_interes:
        sub_old = df_old[df_old["sub_cat"] == c]
        sub_new = df_new[df_new["sub_cat"] == c]
        if sub_old.empty and sub_new.empty:
            continue
        print(f"\n  {c}:")
        for name, sub in [("OLD", sub_old), ("NEW", sub_new)]:
            real = sub["real_qty"].sum()
            fcst = sub["forecast_qty"].sum()
            abs_err = sub["abs_error_qty"].sum()
            wape = abs_err / real * 100 if real else 0
            bias = (real - fcst) / real * 100 if real else 0
            print(f"    {name}: n={len(sub):>4} real={real:>6,.0f} fcst={fcst:>6,.0f} abs_err={abs_err:>6,.0f} WAPE={wape:5.1f}% BIAS={bias:+5.1f}%")


if __name__ == "__main__":
    main()
