"""
Detalle SKU 9407 CERVEZA STELLA ARTOIS BOTELLA UNIDAD 660 CC
en v3.44 vs v3.46 - todas las filas (3 sem x 11 teams).
"""
from __future__ import annotations
from pathlib import Path
import pandas as pd

CSVS = {
    "v3.44": Path(r"c:\Users\sanhu\Odoo\OH Forecast Backtest (x_forecast_backtest).csv"),
    "v3.46": Path(r"c:\Users\sanhu\Odoo\OH Forecast Backtest (x_forecast_backtest) (2).csv"),
}

pd.set_option("display.float_format", lambda x: f"{x:,.2f}")
pd.set_option("display.max_columns", 80)
pd.set_option("display.width", 260)


def _load(path):
    df = pd.read_csv(path, low_memory=False, encoding="latin-1")
    for c in ["forecast_qty", "real_qty", "mu_week_pre_bias", "mu_base", "si_factor",
              "trend_factor", "correccion_factor"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    return df


def main():
    # Match por nombre (CSV puede tener distintos encodings de "STELLA ARTOIS")
    KEY = "STELLA ARTOIS"
    rows_all = []
    for ver, path in CSVS.items():
        df = _load(path)
        mask = df["product_id"].fillna("").astype(str).str.upper().str.contains(KEY)
        sub = df[mask].copy()
        sub["ver"] = ver
        rows_all.append(sub)
    full = pd.concat(rows_all, ignore_index=True)

    print(f"\nFilas STELLA ARTOIS encontradas: {len(full)}")
    print(f"Productos distintos: {sorted(full['product_id'].unique())}")
    print(f"Teams: {sorted(full['team_id'].unique())}")
    print(f"Semanas: {sorted(full['target_week_start'].unique())}")

    cols = [
        "ver", "target_week_start", "team_id", "abcxyz", "series_type",
        "lifecycle", "regimen", "forecast_zone", "forecast_model_code",
        "mu_week_pre_bias", "forecast_qty", "real_qty",
    ]
    cols = [c for c in cols if c in full.columns]

    # Quedarnos solo con el 9407 (botella 660 cc) si hay multiples
    full["pname"] = full["product_id"].fillna("").astype(str).str.upper()
    is_9407 = full["pname"].str.contains("660")
    f9407 = full[is_9407].copy() if is_9407.any() else full.copy()

    print(f"\n--- Variante 660 CC ---")
    print(f"Producto exacto: {sorted(f9407['product_id'].unique())}")

    # Pivot por semana x team para v3.46
    for ver in ["v3.44", "v3.46"]:
        sub = f9407[f9407["ver"] == ver].copy()
        if sub.empty:
            continue
        print(f"\n========= {ver} =========")
        print(sub[cols].sort_values(["target_week_start", "team_id"]).to_string(index=False))

        # Totales por semana
        print(f"\n  Totales {ver} por semana:")
        agg = sub.groupby("target_week_start").agg(
            n=("forecast_qty", "size"),
            fcst=("forecast_qty", "sum"),
            real=("real_qty", "sum"),
        )
        agg["ae"] = sub.groupby("target_week_start").apply(
            lambda d: (d["forecast_qty"] - d["real_qty"]).abs().sum(), include_groups=False
        )
        agg["WAPE"] = (agg["ae"] / agg["real"] * 100).round(1)
        agg["BIAS"] = ((agg["real"] - agg["fcst"]) / agg["real"] * 100).round(1)
        print(agg.to_string())

    # Diff side-by-side de mu_week y forecast_qty
    print(f"\n========= Diff v3.44 vs v3.46 (mismo SKU x team x semana) =========")
    v44 = f9407[f9407["ver"] == "v3.44"][["product_id", "team_id", "target_week_start",
                                            "regimen", "forecast_model_code",
                                            "mu_week_pre_bias", "forecast_qty", "real_qty"]].copy()
    v46 = f9407[f9407["ver"] == "v3.46"][["product_id", "team_id", "target_week_start",
                                            "regimen", "forecast_model_code",
                                            "mu_week_pre_bias", "forecast_qty"]].copy()
    v44.columns = ["product_id", "team_id", "target_week_start", "reg_v44", "model_v44",
                    "mu_v44", "fc_v44", "real"]
    v46.columns = ["product_id", "team_id", "target_week_start", "reg_v46", "model_v46",
                    "mu_v46", "fc_v46"]
    merged = v44.merge(v46, on=["product_id", "team_id", "target_week_start"], how="inner")
    merged["delta_fc"] = (merged["fc_v46"] - merged["fc_v44"]).round(2)
    print(merged.sort_values(["target_week_start", "team_id"]).to_string(index=False))


if __name__ == "__main__":
    main()
