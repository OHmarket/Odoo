"""
Pase 2 - Comparacion Feb (temp alta) vs Mar (transicion) en backtest 3 semanas.

Abril descartado por colapso a REG-0 (artefacto, no comportamiento del motor).
Foco: medir el delta del motor entre temporada alta y transicion.

Filtro ruido: cervezas, cigarros/tabacos, snacks, impulsivos, Ventas San Jose.
Encoding fix: el export viene en cp1252.
"""
from __future__ import annotations
from pathlib import Path
import pandas as pd

CSV_PATH = Path(r"c:\Users\sanhu\Odoo\OH Forecast Backtest (x_forecast_backtest).csv")

NOISE_CATEG_KEYWORDS = ["cerveza", "cigarr", "tabaco", "snack", "impulsiv"]
NOISE_TEAM_KEYWORDS = ["san jos"]

WEEKS_OK = ["2026-02-16", "2026-03-30"]

pd.set_option("display.float_format", lambda x: f"{x:,.2f}")
pd.set_option("display.max_columns", 60)
pd.set_option("display.width", 220)
pd.set_option("display.max_colwidth", 80)


def _load():
    df = pd.read_csv(CSV_PATH, low_memory=False, encoding="latin-1")
    for col in ["forecast_qty", "real_qty", "abs_error_qty", "error_qty",
                "mu_week_pre_bias", "ape", "bias_pct", "cv2"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    df["categ_lower"] = df["categ_id"].fillna("").astype(str).str.lower()
    df["team_lower"] = df["team_id"].fillna("").astype(str).str.lower()
    noise_categ = df["categ_lower"].apply(lambda s: any(k in s for k in NOISE_CATEG_KEYWORDS))
    noise_team = df["team_lower"].apply(lambda s: any(k in s for k in NOISE_TEAM_KEYWORDS))
    return df[~(noise_categ | noise_team)].copy()


def _agg(df, by):
    g = df.groupby(by, dropna=False).agg(
        n=("abs_error_qty", "size"),
        real=("real_qty", "sum"),
        fcst=("forecast_qty", "sum"),
        abs_err=("abs_error_qty", "sum"),
        err=("error_qty", "sum"),
    ).reset_index()
    g["wape_pct"] = (g["abs_err"] / g["real"]).where(g["real"] > 0) * 100
    g["bias_pct"] = (g["err"] / g["real"]).where(g["real"] > 0) * 100
    return g


def _delta_pivot(clean, dim, weeks=WEEKS_OK, min_real=20):
    """Pivot dim x semana, mostrando wape/bias/real, ordenado por delta bias."""
    rows = []
    for val in clean[dim].dropna().unique():
        sub = clean[clean[dim] == val]
        rec = {dim: val}
        valid = True
        for w in weeks:
            s = sub[sub["target_week_start"] == w]
            real = s["real_qty"].sum()
            if real < min_real:
                valid = False
            wape = s["abs_error_qty"].sum() / real * 100 if real > 0 else float("nan")
            bias = s["error_qty"].sum() / real * 100 if real > 0 else float("nan")
            rec[f"real_{w[5:]}"] = real
            rec[f"wape_{w[5:]}"] = wape
            rec[f"bias_{w[5:]}"] = bias
        if valid:
            rec["delta_wape"] = rec[f"wape_{weeks[1][5:]}"] - rec[f"wape_{weeks[0][5:]}"]
            rec["delta_bias"] = rec[f"bias_{weeks[1][5:]}"] - rec[f"bias_{weeks[0][5:]}"]
            rows.append(rec)
    return pd.DataFrame(rows)


def main():
    clean = _load()
    feb = clean[clean["target_week_start"] == "2026-02-16"]
    mar = clean[clean["target_week_start"] == "2026-03-30"]
    print(f"Filas limpio: Feb={len(feb):,}  Mar={len(mar):,}")

    print("\n" + "=" * 100)
    print("A. RESUMEN GLOBAL Feb vs Mar")
    print("=" * 100)
    for label, d in [("Feb (temp alta, quincena)", feb), ("Mar (transicion, fin-mes)", mar)]:
        real = d["real_qty"].sum()
        fcst = d["forecast_qty"].sum()
        abse = d["abs_error_qty"].sum()
        err = d["error_qty"].sum()
        print(f"  {label:35s}  real={real:>10,.0f}  fcst={fcst:>10,.0f}  "
              f"WAPE={abse/real*100:>5.1f}%  BIAS={err/real*100:>+6.1f}%")
    real_total = feb["real_qty"].sum() + mar["real_qty"].sum()
    print(f"\n  DELTA Mar - Feb:  real var={mar['real_qty'].sum()-feb['real_qty'].sum():+,.0f}  "
          f"(-{(1-mar['real_qty'].sum()/feb['real_qty'].sum())*100:.0f}% caida de venta de Feb a Mar)")

    print("\n" + "=" * 100)
    print("B. DELTA por REGIMEN (ordenado por delta_bias desc = los que mas sub-pronostican en Mar)")
    print("=" * 100)
    d = _delta_pivot(clean, "regimen", min_real=50)
    print(d.sort_values("delta_bias", ascending=False).to_string(index=False))

    print("\n" + "=" * 100)
    print("C. DELTA por TEAM (ordenado por delta_bias desc)")
    print("=" * 100)
    d = _delta_pivot(clean, "team_id", min_real=100)
    print(d.sort_values("delta_bias", ascending=False).to_string(index=False))

    print("\n" + "=" * 100)
    print("D. DELTA por ABCXYZ (sub-pronostico en clases A vs C)")
    print("=" * 100)
    d = _delta_pivot(clean, "abcxyz", min_real=50)
    print(d.sort_values("delta_bias", ascending=False).to_string(index=False))

    print("\n" + "=" * 100)
    print("E. DELTA por IMPORTANCIA")
    print("=" * 100)
    d = _delta_pivot(clean, "importancia", min_real=50)
    print(d.sort_values("delta_bias", ascending=False).to_string(index=False))

    print("\n" + "=" * 100)
    print("F. DELTA por SERIES_TYPE")
    print("=" * 100)
    d = _delta_pivot(clean, "series_type", min_real=50)
    print(d.sort_values("delta_bias", ascending=False).to_string(index=False))

    print("\n" + "=" * 100)
    print("G. DELTA por CICLO DE VIDA")
    print("=" * 100)
    d = _delta_pivot(clean, "ciclo_de_vida", min_real=50)
    print(d.sort_values("delta_bias", ascending=False).to_string(index=False))

    print("\n" + "=" * 100)
    print("H. DELTA por CATEGORIA - top 25 que mas empeoran BIAS en Mar")
    print("=" * 100)
    d = _delta_pivot(clean, "categ_id", min_real=100)
    print(d.sort_values("delta_bias", ascending=False).head(25).to_string(index=False))

    print("\n" + "=" * 100)
    print("I. DELTA por CATEGORIA - top 15 que MEJORAN BIAS en Mar (over-forecast Mar)")
    print("=" * 100)
    d = _delta_pivot(clean, "categ_id", min_real=100)
    print(d.sort_values("delta_bias", ascending=True).head(15).to_string(index=False))

    print("\n" + "=" * 100)
    print("J. FORECAST_MODEL_CODE distribucion Feb vs Mar (sanity)")
    print("=" * 100)
    fm = clean[clean["target_week_start"].isin(WEEKS_OK)].pivot_table(
        index="forecast_model_code",
        columns="target_week_start",
        values="product_id",
        aggfunc="count",
        fill_value=0,
    )
    fm["delta"] = fm["2026-03-30"] - fm["2026-02-16"]
    print(fm.sort_values("2026-02-16", ascending=False).to_string())

    print("\n" + "=" * 100)
    print("K. TOP 30 SKUs sub-pronosticados en Mar-30 (mayor error_qty positivo)")
    print("=" * 100)
    mar_g = mar.groupby(["product_id"]).agg(
        n=("abs_error_qty", "size"),
        real=("real_qty", "sum"),
        fcst=("forecast_qty", "sum"),
        err=("error_qty", "sum"),
        abs_err=("abs_error_qty", "sum"),
    )
    mar_g["wape_pct"] = (mar_g["abs_err"] / mar_g["real"]).where(mar_g["real"] > 0) * 100
    mar_g["bias_pct"] = (mar_g["err"] / mar_g["real"]).where(mar_g["real"] > 0) * 100
    top = mar_g.sort_values("err", ascending=False).head(30)
    print(top.to_string())

    print("\n" + "=" * 100)
    print("L. TOP 20 SKUs over-pronosticados en Mar-30 (mayor error_qty NEGATIVO)")
    print("=" * 100)
    bot = mar_g.sort_values("err", ascending=True).head(20)
    print(bot.to_string())


if __name__ == "__main__":
    main()
