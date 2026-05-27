"""
Analisis del backtest con v3.44 (fix declining via nz_recent_8w).
Compara directamente vs v3.43 (corrida anterior sobre las mismas 3 semanas).
"""
from __future__ import annotations
from pathlib import Path
import io
import pandas as pd

CSV_NEW = Path(r"c:\Users\sanhu\Odoo\OH Forecast Backtest (x_forecast_backtest).csv")
# v3.43 numbers from mayo_clean_results.txt (saved offline)
V3_43_BASELINE = {
    "2026-05-04": {"n_clean": 12612, "real": 15852, "fcst": 13274, "WAPE": 62.2, "BIAS": 16.3},
    "2026-05-11": {"n_clean": 12637, "real": 14313, "fcst": 12919, "WAPE": 63.6, "BIAS": 9.7},
    "2026-05-18": {"n_clean": 12661, "real": 17782, "fcst": 12933, "WAPE": 62.7, "BIAS": 27.3},
}
V3_43_TOTAL = {"WAPE": 62.8, "BIAS": 18.4, "real": 47947, "fcst": 39126, "n_clean": 37910}
V3_43_MIN_STOCK_PCT = {"2026-05-04": 71.6, "2026-05-11": 71.3, "2026-05-18": 71.0}

OUT = Path(__file__).parent / "v3_44_results.txt"

NOISE_CATEG = ["cerveza", "cigarr", "tabaco", "snack", "impulso"]
NOISE_TEAM = ["san jos"]

pd.set_option("display.float_format", lambda x: f"{x:,.2f}")
pd.set_option("display.max_columns", 60)
pd.set_option("display.width", 240)


def _load(path):
    df = pd.read_csv(path, low_memory=False, encoding="latin-1")
    for c in ["forecast_qty", "real_qty", "abs_error_qty", "error_qty", "mu_week_pre_bias"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    df["cat_l"] = df["categ_id"].fillna("").astype(str).str.lower()
    df["team_l"] = df["team_id"].fillna("").astype(str).str.lower()
    n_c = df["cat_l"].apply(lambda s: any(k in s for k in NOISE_CATEG))
    n_t = df["team_l"].apply(lambda s: any(k in s for k in NOISE_TEAM))
    return df[~(n_c | n_t)].copy()


def _metrics(d):
    real = d["real_qty"].sum()
    fc = d["forecast_qty"].sum()
    ae = (d["forecast_qty"] - d["real_qty"]).abs().sum()
    err = (d["real_qty"] - d["forecast_qty"]).sum()
    return {
        "n": len(d),
        "real": real,
        "fcst": fc,
        "WAPE": ae/real*100 if real > 0 else float("nan"),
        "BIAS": err/real*100 if real > 0 else float("nan"),
    }


def main():
    buf = io.StringIO()
    def p(s=""): buf.write(s + "\n")

    df = _load(CSV_NEW)
    p(f"Filas v3.44 (limpio): {len(df):,}")

    # === HEADLINE v3.43 vs v3.44 ===
    p("\n" + "=" * 100)
    p("HEADLINE comparativo v3.43 -> v3.44")
    p("=" * 100)
    p(f"\n  {'semana':12s} | {'WAPE old':>9s} | {'WAPE new':>9s} | {'Δ':>8s} || {'BIAS old':>9s} | {'BIAS new':>9s} | {'Δ':>8s}")
    p(f"  {'-'*12} | {'-'*9} | {'-'*9} | {'-'*8} || {'-'*9} | {'-'*9} | {'-'*8}")
    for wk in sorted(df["target_week_start"].unique()):
        m_new = _metrics(df[df["target_week_start"] == wk])
        old = V3_43_BASELINE[wk]
        d_wape = m_new["WAPE"] - old["WAPE"]
        d_bias = m_new["BIAS"] - old["BIAS"]
        p(f"  {wk} | {old['WAPE']:>8.1f}% | {m_new['WAPE']:>8.1f}% | {d_wape:>+7.2f}pp || {old['BIAS']:>+8.1f}% | {m_new['BIAS']:>+8.1f}% | {d_bias:>+7.2f}pp")

    # Total
    real_t = df["real_qty"].sum()
    fc_t = df["forecast_qty"].sum()
    ae_t = (df["forecast_qty"] - df["real_qty"]).abs().sum()
    err_t = (df["real_qty"] - df["forecast_qty"]).sum()
    wape_t = ae_t/real_t*100
    bias_t = err_t/real_t*100
    p(f"  {'TOTAL':12s} | {V3_43_TOTAL['WAPE']:>8.1f}% | {wape_t:>8.1f}% | {wape_t-V3_43_TOTAL['WAPE']:>+7.2f}pp || {V3_43_TOTAL['BIAS']:>+8.1f}% | {bias_t:>+8.1f}% | {bias_t-V3_43_TOTAL['BIAS']:>+7.2f}pp")

    p(f"\n  Real total v3.43: {V3_43_TOTAL['real']:,.0f}  vs v3.44: {real_t:,.0f}")
    p(f"  Fcst total v3.43: {V3_43_TOTAL['fcst']:,.0f}  vs v3.44: {fc_t:,.0f}")

    # === % min_stock_or_manual ===
    p("\n" + "=" * 100)
    p("% min_stock_or_manual v3.43 vs v3.44 (objetivo: bajar de 71% a 30-40%)")
    p("=" * 100)
    p(f"\n  {'semana':12s} | {'old %':>6s} | {'new %':>6s} | {'Δ':>8s}")
    for wk in sorted(df["target_week_start"].unique()):
        sub = df[df["target_week_start"] == wk]
        n_min = (sub["forecast_model_code"] == "min_stock_or_manual").sum()
        pct_new = n_min / len(sub) * 100
        pct_old = V3_43_MIN_STOCK_PCT[wk]
        p(f"  {wk} | {pct_old:>5.1f}% | {pct_new:>5.1f}% | {pct_new - pct_old:>+7.2f}pp")

    # === Distribuciones ===
    p("\n" + "=" * 100)
    p("Distribucion forecast_model_code por semana")
    p("=" * 100)
    p(df.groupby(["target_week_start", "forecast_model_code"]).size().unstack(fill_value=0).to_string())
    p("\nregimen:")
    p(df.groupby(["target_week_start", "regimen"]).size().unstack(fill_value=0).to_string())

    # === Por team ===
    p("\n" + "=" * 100)
    p("Detalle por team (May-18)")
    p("=" * 100)
    wk = "2026-05-18"
    rows = []
    for team in sorted(df["team_id"].unique()):
        sub_n = df[(df["target_week_start"] == wk) & (df["team_id"] == team)]
        m = _metrics(sub_n)
        rows.append({
            "team": team[:25],
            "n": m["n"],
            "real": m["real"],
            "fcst": m["fcst"],
            "WAPE": round(m["WAPE"], 1),
            "BIAS": round(m["BIAS"], 1),
        })
    p(pd.DataFrame(rows).to_string(index=False))

    OUT.write_text(buf.getvalue(), encoding="utf-8")
    print(f"Output: {OUT}")


if __name__ == "__main__":
    main()
