"""
Mide la SI ratio IMPLICITA del motor: forecast_Mar/forecast_Feb por SKU,
y compara contra ratio real_Mar/real_Feb.

Asume mu_base_Feb ~= mu_base_Mar (deseasonalizacion correcta).
Si el ratio efectivo es mayor que el ratio real, el motor sub-corrige la
estacionalidad de Feb->Mar (SI demasiado suave).

Output a archivo TXT.
"""
from __future__ import annotations
from pathlib import Path
import io
import pandas as pd

CSV_PATH = Path(r"c:\Users\sanhu\Odoo\OH Forecast Backtest (x_forecast_backtest) (1).csv")
OUT_PATH = Path(__file__).parent / "si_implicita_output.txt"

NOISE_CATEG_KEYWORDS = ["cerveza", "cigarr", "tabaco", "snack", "impulso"]
NOISE_TEAM_KEYWORDS = ["san jos"]

pd.set_option("display.float_format", lambda x: f"{x:,.3f}")
pd.set_option("display.max_columns", 60)
pd.set_option("display.width", 220)
pd.set_option("display.max_colwidth", 80)


def _load():
    df = pd.read_csv(CSV_PATH, low_memory=False, encoding="latin-1")
    for col in ["forecast_qty", "real_qty", "abs_error_qty", "error_qty",
                "mu_week_pre_bias"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    df["categ_lower"] = df["categ_id"].fillna("").astype(str).str.lower()
    df["team_lower"] = df["team_id"].fillna("").astype(str).str.lower()
    noise_categ = df["categ_lower"].apply(lambda s: any(k in s for k in NOISE_CATEG_KEYWORDS))
    noise_team = df["team_lower"].apply(lambda s: any(k in s for k in NOISE_TEAM_KEYWORDS))
    return df[~(noise_categ | noise_team)].copy()


def main():
    buf = io.StringIO()
    def p(s=""): buf.write(s + "\n")

    df = _load()
    feb = df[df["target_week_start"] == "2026-02-16"][["product_id", "team_id", "categ_id", "regimen", "abcxyz",
                                                         "forecast_qty", "real_qty"]].copy()
    mar = df[df["target_week_start"] == "2026-03-16"][["product_id", "team_id", "forecast_qty", "real_qty"]].copy()
    feb.rename(columns={"forecast_qty": "fc_feb", "real_qty": "real_feb"}, inplace=True)
    mar.rename(columns={"forecast_qty": "fc_mar", "real_qty": "real_mar"}, inplace=True)
    pair = feb.merge(mar, on=["product_id", "team_id"], how="inner")
    p(f"Pairs (team,SKU) Feb&Mar disponibles: {len(pair):,}")

    # Solo pares con forecast Y real > 0 en ambas semanas (sino la ratio explota)
    pair_clean = pair[(pair["fc_feb"] > 0) & (pair["fc_mar"] > 0) &
                      (pair["real_feb"] > 0) & (pair["real_mar"] > 0)].copy()
    pair_clean["si_ratio_motor"] = pair_clean["fc_mar"] / pair_clean["fc_feb"]
    pair_clean["si_ratio_real"]  = pair_clean["real_mar"] / pair_clean["real_feb"]
    pair_clean["si_gap"]         = pair_clean["si_ratio_motor"] - pair_clean["si_ratio_real"]
    p(f"Pairs limpios (forecast Y real >0 en ambas): {len(pair_clean):,}")
    p("")

    p("=" * 100)
    p("A. SI RATIO IMPLICITA AGREGADA por CATEGORIA (top 20 por contribucion al error)")
    p("=" * 100)
    p("Interpretacion:")
    p("  si_ratio_motor = forecast_Mar / forecast_Feb (lo que el motor aplico)")
    p("  si_ratio_real  = real_Mar    / real_Feb    (lo que paso de verdad)")
    p("  si_gap         = motor - real. Positivo grande => motor sub-corrigio (SI muy suave).")
    p("")

    cat = pair_clean.groupby("categ_id").agg(
        n=("product_id", "size"),
        fc_feb=("fc_feb", "sum"),
        fc_mar=("fc_mar", "sum"),
        real_feb=("real_feb", "sum"),
        real_mar=("real_mar", "sum"),
    )
    cat["si_motor"] = cat["fc_mar"] / cat["fc_feb"]
    cat["si_real"]  = cat["real_mar"] / cat["real_feb"]
    cat["gap"]      = cat["si_motor"] - cat["si_real"]
    cat["abs_err_total"] = (cat["fc_mar"] - cat["real_mar"]).abs() + (cat["fc_feb"] - cat["real_feb"]).abs()

    top = cat.sort_values("abs_err_total", ascending=False).head(25)
    p(top[["n", "fc_feb", "real_feb", "fc_mar", "real_mar", "si_motor", "si_real", "gap"]].to_string())

    p("")
    p("=" * 100)
    p("B. AGREGADO TOTAL: ratio Feb->Mar motor vs realidad")
    p("=" * 100)
    p(f"  Motor: fc_mar/fc_feb = {pair_clean['fc_mar'].sum()/pair_clean['fc_feb'].sum():.4f}")
    p(f"  Real:  real_mar/real_feb = {pair_clean['real_mar'].sum()/pair_clean['real_feb'].sum():.4f}")
    motor_r = pair_clean['fc_mar'].sum()/pair_clean['fc_feb'].sum()
    real_r = pair_clean['real_mar'].sum()/pair_clean['real_feb'].sum()
    p(f"  Gap absoluto = {motor_r-real_r:.4f}  ({(motor_r/real_r - 1)*100:+.1f}% relativo)")

    p("")
    p("=" * 100)
    p("C. TOP 30 SKUs con peor gap (motor expects mucho, reality drops fuerte)")
    p("=" * 100)
    # SKU-level: agregar por product solo (sumar teams)
    sku = pair_clean.groupby(["product_id", "categ_id"]).agg(
        n_teams=("team_id", "size"),
        fc_feb=("fc_feb", "sum"),
        fc_mar=("fc_mar", "sum"),
        real_feb=("real_feb", "sum"),
        real_mar=("real_mar", "sum"),
    ).reset_index()
    sku["si_motor"] = sku["fc_mar"] / sku["fc_feb"]
    sku["si_real"]  = sku["real_mar"] / sku["real_feb"]
    sku["gap"]      = sku["si_motor"] - sku["si_real"]
    sku["over_qty"] = sku["fc_mar"] - sku["real_mar"]  # cuanto over-forecast en Mar

    # filtro: SKUs con suficiente volumen para no ser ruido
    sku_min = sku[(sku["fc_feb"] >= 5) & (sku["real_feb"] >= 5)].copy()
    p(f"SKUs con vol minimo Feb >=5 unidades: {len(sku_min):,}")
    top_gap = sku_min.sort_values("over_qty", ascending=False).head(30)
    p("\nTop por over_qty (units over-pronosticadas Mar):")
    p(top_gap[["product_id", "categ_id", "n_teams", "fc_feb", "real_feb", "fc_mar", "real_mar",
                "si_motor", "si_real", "gap", "over_qty"]].to_string(index=False))

    p("")
    p("=" * 100)
    p("D. Distribucion de SI gap (sub-correccion del motor)")
    p("=" * 100)
    p(sku_min["gap"].describe(percentiles=[0.1, 0.25, 0.5, 0.75, 0.9, 0.95]).to_string())
    p(f"\nSKUs con gap > 0 (motor sub-corrige): {(sku_min['gap'] > 0).sum():,}  ({(sku_min['gap']>0).mean()*100:.1f}%)")
    p(f"SKUs con gap > 0.2 (motor sub-corrige FUERTE): {(sku_min['gap'] > 0.2).sum():,}  ({(sku_min['gap']>0.2).mean()*100:.1f}%)")
    p(f"SKUs con gap < 0 (motor over-corrige): {(sku_min['gap'] < 0).sum():,}  ({(sku_min['gap']<0).mean()*100:.1f}%)")

    p("")
    p("=" * 100)
    p("E. SI ratio por REGIMEN")
    p("=" * 100)
    reg = pair_clean.groupby("regimen").agg(
        n=("product_id", "size"),
        fc_feb=("fc_feb", "sum"),
        fc_mar=("fc_mar", "sum"),
        real_feb=("real_feb", "sum"),
        real_mar=("real_mar", "sum"),
    )
    reg["si_motor"] = reg["fc_mar"] / reg["fc_feb"]
    reg["si_real"]  = reg["real_mar"] / reg["real_feb"]
    reg["gap"]      = reg["si_motor"] - reg["si_real"]
    p(reg.to_string())

    p("")
    p("=" * 100)
    p("F. SI ratio por ABCXYZ")
    p("=" * 100)
    abx = pair_clean.groupby("abcxyz").agg(
        n=("product_id", "size"),
        fc_feb=("fc_feb", "sum"),
        fc_mar=("fc_mar", "sum"),
        real_feb=("real_feb", "sum"),
        real_mar=("real_mar", "sum"),
    )
    abx["si_motor"] = abx["fc_mar"] / abx["fc_feb"]
    abx["si_real"]  = abx["real_mar"] / abx["real_feb"]
    abx["gap"]      = abx["si_motor"] - abx["si_real"]
    p(abx.to_string())

    OUT_PATH.write_text(buf.getvalue(), encoding="utf-8")
    print(f"Output saved to: {OUT_PATH}")


if __name__ == "__main__":
    main()
