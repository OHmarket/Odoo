"""
Compara v3.45 vs v3.44 sobre las mismas 3 semanas de mayo.
"""
from __future__ import annotations
from pathlib import Path
import io
import pandas as pd

CSV_V45 = Path(r"c:\Users\sanhu\Odoo\OH Forecast Backtest (x_forecast_backtest) (1).csv")
OUT = Path(__file__).parent / "v3_45_results.txt"

# v3.44 baseline (de v3_44_results.txt)
V44_BASELINE = {
    "2026-05-04": {"WAPE": 63.2, "BIAS": 14.9, "min_stock_pct": 70.2, "fcst": None},
    "2026-05-11": {"WAPE": 64.1, "BIAS": 9.2,  "min_stock_pct": 70.4, "fcst": None},
    "2026-05-18": {"WAPE": 62.9, "BIAS": 27.0, "min_stock_pct": 70.5, "fcst": None},
}
V44_TOTAL = {"WAPE": 63.3, "BIAS": 17.7, "real": 47947, "fcst": 39470}

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

    v45 = _load(CSV_V45)
    p(f"v3.45 limpio: {len(v45):,}")

    # ===== 1. Headline =====
    p("\n" + "=" * 100)
    p("1. HEADLINE comparativo v3.44 (baseline) -> v3.45")
    p("=" * 100)
    p(f"\n  {'semana':12s} | {'WAPE v44':>9s} | {'WAPE v45':>9s} | {'Δ':>8s} || {'BIAS v44':>9s} | {'BIAS v45':>9s} | {'Δ':>8s}")
    p(f"  {'-'*12} | {'-'*9} | {'-'*9} | {'-'*8} || {'-'*9} | {'-'*9} | {'-'*8}")
    for wk in sorted(v45["target_week_start"].unique()):
        m_v45 = _metrics(v45[v45["target_week_start"] == wk])
        base = V44_BASELINE[wk]
        d_wape = m_v45["WAPE"] - base["WAPE"]
        d_bias = m_v45["BIAS"] - base["BIAS"]
        p(f"  {wk} | {base['WAPE']:>8.1f}% | {m_v45['WAPE']:>8.1f}% | {d_wape:>+7.2f}pp || {base['BIAS']:>+8.1f}% | {m_v45['BIAS']:>+8.1f}% | {d_bias:>+7.2f}pp")

    # Total
    m_v45_t = _metrics(v45)
    d_wape_t = m_v45_t["WAPE"] - V44_TOTAL["WAPE"]
    d_bias_t = m_v45_t["BIAS"] - V44_TOTAL["BIAS"]
    p(f"  {'TOTAL':12s} | {V44_TOTAL['WAPE']:>8.1f}% | {m_v45_t['WAPE']:>8.1f}% | {d_wape_t:>+7.2f}pp || {V44_TOTAL['BIAS']:>+8.1f}% | {m_v45_t['BIAS']:>+8.1f}% | {d_bias_t:>+7.2f}pp")

    p(f"\n  Fcst total v44: {V44_TOTAL['fcst']:,.0f}  vs v45: {m_v45_t['fcst']:,.0f}")

    # ===== 2. min_stock_or_manual % =====
    p("\n" + "=" * 100)
    p("2. % min_stock_or_manual v3.44 vs v3.45")
    p("=" * 100)
    for wk in sorted(v45["target_week_start"].unique()):
        s_v45 = v45[v45["target_week_start"] == wk]
        n_min_v45 = (s_v45["forecast_model_code"] == "min_stock_or_manual").sum()
        pct_v45 = n_min_v45/len(s_v45)*100
        pct_v44 = V44_BASELINE[wk]["min_stock_pct"]
        p(f"  {wk}: v44 {pct_v44:>5.1f}%  ->  v45 {pct_v45:>5.1f}%  ({pct_v45-pct_v44:>+.2f}pp)  [{n_min_v45:,} de {len(s_v45):,}]")

    # ===== 3. forecast_zone & model =====
    p("\n" + "=" * 100)
    p("3. Distribucion forecast_model_code y zone (v3.45) por semana")
    p("=" * 100)
    p("\nforecast_model_code:")
    p(v45.groupby(["target_week_start", "forecast_model_code"]).size().unstack(fill_value=0).to_string())
    p("\nforecast_zone:")
    p(v45.groupby(["target_week_start", "forecast_zone"]).size().unstack(fill_value=0).to_string())
    p("\nregimen:")
    p(v45.groupby(["target_week_start", "regimen"]).size().unstack(fill_value=0).to_string())

    # ===== 4. Detalle por team May-18 =====
    p("\n" + "=" * 100)
    p("4. Detalle por team May-18 (v3.45)")
    p("=" * 100)
    wk = "2026-05-18"
    rows = []
    for team in sorted(v45["team_id"].unique()):
        s = v45[(v45["target_week_start"] == wk) & (v45["team_id"] == team)]
        m = _metrics(s)
        rows.append({
            "team": team[:25],
            "n": m["n"],
            "real": m["real"],
            "fcst": m["fcst"],
            "WAPE": round(m["WAPE"], 1),
            "BIAS": round(m["BIAS"], 1),
        })
    p(pd.DataFrame(rows).to_string(index=False))

    # ===== 5. Top categorias =====
    p("\n" + "=" * 100)
    p("5. Top 15 categorias por contribucion al WAPE (3 sem, v3.45)")
    p("=" * 100)
    cat_v45 = v45.groupby("categ_id").apply(lambda d: pd.Series({
        "n": len(d),
        "real": d["real_qty"].sum(),
        "fcst": d["forecast_qty"].sum(),
        "ae": (d["forecast_qty"] - d["real_qty"]).abs().sum(),
        "err": (d["real_qty"] - d["forecast_qty"]).sum(),
    }), include_groups=False)
    cat_v45["WAPE"] = (cat_v45["ae"] / cat_v45["real"]).where(cat_v45["real"] > 0) * 100
    cat_v45["BIAS"] = (cat_v45["err"] / cat_v45["real"]).where(cat_v45["real"] > 0) * 100
    top = cat_v45.sort_values("ae", ascending=False).head(15)
    p(top[["n", "real", "fcst", "WAPE", "BIAS"]].round(1).to_string())

    OUT.write_text(buf.getvalue(), encoding="utf-8")
    print(f"Output: {OUT}")


if __name__ == "__main__":
    main()
