"""
Compara las 3 versiones recientes sobre las mismas 3 semanas de mayo:
  v3.44: fix declining (CSV sin sufijo)
  v3.45: remove mu<2.0 threshold (CSV (1))
  v3.46: remove rounding mu_week (CSV (2))
"""
from __future__ import annotations
from pathlib import Path
import io
import pandas as pd

CSVS = {
    "v3.44": Path(r"c:\Users\sanhu\Odoo\OH Forecast Backtest (x_forecast_backtest).csv"),
    "v3.45": Path(r"c:\Users\sanhu\Odoo\OH Forecast Backtest (x_forecast_backtest) (1).csv"),
    "v3.46": Path(r"c:\Users\sanhu\Odoo\OH Forecast Backtest (x_forecast_backtest) (2).csv"),
}
OUT = Path(__file__).parent / "v3_46_results.txt"

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

    dfs = {ver: _load(path) for ver, path in CSVS.items()}
    for ver, df in dfs.items():
        p(f"{ver}: {len(df):,} filas limpio | fcst total = {df['forecast_qty'].sum():,.1f}")

    # ===== 1. Headline 3 vias =====
    p("\n" + "=" * 110)
    p("1. HEADLINE WAPE / BIAS por semana (limpio)")
    p("=" * 110)
    p(f"\n  {'semana':12s} | {'v3.44':>17s} | {'v3.45':>17s} | {'v3.46':>17s} | {'Δ vs v44':>12s}")
    p(f"  {'-'*12} | {'-'*17} | {'-'*17} | {'-'*17} | {'-'*12}")
    for wk in sorted(dfs["v3.46"]["target_week_start"].unique()):
        line = f"  {wk}"
        for ver in ["v3.44", "v3.45", "v3.46"]:
            m = _metrics(dfs[ver][dfs[ver]["target_week_start"] == wk])
            line += f" | {m['WAPE']:>5.1f}% / {m['BIAS']:>+5.1f}%"
        # delta v3.46 vs v3.44
        m44 = _metrics(dfs["v3.44"][dfs["v3.44"]["target_week_start"] == wk])
        m46 = _metrics(dfs["v3.46"][dfs["v3.46"]["target_week_start"] == wk])
        dw = m46["WAPE"] - m44["WAPE"]
        db = m46["BIAS"] - m44["BIAS"]
        line += f" | {dw:>+5.1f}/{db:>+5.1f}"
        p(line)
    # Total
    line = f"  {'TOTAL':12s}"
    for ver in ["v3.44", "v3.45", "v3.46"]:
        m = _metrics(dfs[ver])
        line += f" | {m['WAPE']:>5.1f}% / {m['BIAS']:>+5.1f}%"
    m44 = _metrics(dfs["v3.44"])
    m46 = _metrics(dfs["v3.46"])
    line += f" | {m46['WAPE']-m44['WAPE']:>+5.1f}/{m46['BIAS']-m44['BIAS']:>+5.1f}"
    p(line)

    # Forecast totals
    p("")
    p(f"  Real total (sin cambio): {_metrics(dfs['v3.46'])['real']:,.0f}")
    p(f"  Fcst total v3.44: {dfs['v3.44']['forecast_qty'].sum():,.1f}")
    p(f"  Fcst total v3.45: {dfs['v3.45']['forecast_qty'].sum():,.1f}")
    p(f"  Fcst total v3.46: {dfs['v3.46']['forecast_qty'].sum():,.1f}")

    # ===== 2. min_stock_or_manual % =====
    p("\n" + "=" * 110)
    p("2. % min_stock_or_manual")
    p("=" * 110)
    p(f"\n  {'semana':12s} | {'v3.44':>8s} | {'v3.45':>8s} | {'v3.46':>8s}")
    for wk in sorted(dfs["v3.46"]["target_week_start"].unique()):
        row = f"  {wk}"
        for ver in ["v3.44", "v3.45", "v3.46"]:
            s = dfs[ver][dfs[ver]["target_week_start"] == wk]
            n_min = (s["forecast_model_code"] == "min_stock_or_manual").sum()
            pct = n_min/len(s)*100
            row += f" | {pct:>7.1f}%"
        p(row)

    # ===== 3. Distribucion mu_week en v3.46 =====
    p("\n" + "=" * 110)
    p("3. v3.46: distribucion forecast_qty (slow-movers ahora con decimal)")
    p("=" * 110)
    v46 = dfs["v3.46"]
    buckets = [
        ("== 0", v46["forecast_qty"] == 0),
        ("(0, 0.1]", (v46["forecast_qty"] > 0) & (v46["forecast_qty"] <= 0.1)),
        ("(0.1, 0.5]", (v46["forecast_qty"] > 0.1) & (v46["forecast_qty"] <= 0.5)),
        ("(0.5, 1.0]", (v46["forecast_qty"] > 0.5) & (v46["forecast_qty"] <= 1.0)),
        ("(1.0, 2.0]", (v46["forecast_qty"] > 1.0) & (v46["forecast_qty"] <= 2.0)),
        ("(2.0, 5.0]", (v46["forecast_qty"] > 2.0) & (v46["forecast_qty"] <= 5.0)),
        ("> 5.0", v46["forecast_qty"] > 5.0),
    ]
    p(f"\n  {'bucket':14s} | {'count':>7s} | {'% total':>7s} | {'sum_fcst':>10s} | {'sum_real':>10s}")
    for label, mask in buckets:
        n = mask.sum()
        sum_fc = v46.loc[mask, "forecast_qty"].sum()
        sum_real = v46.loc[mask, "real_qty"].sum()
        p(f"  {label:14s} | {n:>7,d} | {n/len(v46)*100:>6.1f}% | {sum_fc:>10,.1f} | {sum_real:>10,.0f}")

    # ===== 4. Detalle por team =====
    p("\n" + "=" * 110)
    p("4. Por team (May-18) v3.44 -> v3.46")
    p("=" * 110)
    wk = "2026-05-18"
    rows = []
    for team in sorted(dfs["v3.46"]["team_id"].unique()):
        m44 = _metrics(dfs["v3.44"][(dfs["v3.44"]["target_week_start"] == wk) & (dfs["v3.44"]["team_id"] == team)])
        m46 = _metrics(dfs["v3.46"][(dfs["v3.46"]["target_week_start"] == wk) & (dfs["v3.46"]["team_id"] == team)])
        rows.append({
            "team": team[:25],
            "real": m46["real"],
            "fc_v44": round(m44["fcst"], 1),
            "fc_v46": round(m46["fcst"], 1),
            "WAPE_v44": round(m44["WAPE"], 1),
            "WAPE_v46": round(m46["WAPE"], 1),
            "BIAS_v44": round(m44["BIAS"], 1),
            "BIAS_v46": round(m46["BIAS"], 1),
        })
    p(pd.DataFrame(rows).to_string(index=False))

    OUT.write_text(buf.getvalue(), encoding="utf-8")
    print(f"Output: {OUT}")


if __name__ == "__main__":
    main()
