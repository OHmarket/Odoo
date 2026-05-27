"""
Analisis del backtest limpio (sin OLD) sobre 2026-05-04/11/18.
Valida que:
  - No hay regresion vs v3.43 sobre Feb/Mar/Apr (mismas metricas si todo OK)
  - Trend correction se sigue aplicando
  - Apr-06 bug NO aparece (cutoffs todos lejos de 'hoy', son mas viejos)
"""
from __future__ import annotations
from pathlib import Path
import io
import pandas as pd

CSV = Path(r"c:\Users\sanhu\Odoo\OH Forecast Backtest (x_forecast_backtest) (3).csv")
OUT = Path(__file__).parent / "mayo_clean_results.txt"

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

    df = _load(CSV)
    p(f"Filas limpio: {len(df):,}")
    p(f"Semanas: {sorted(df['target_week_start'].unique())}")

    # === 1. Headline por semana ===
    p("\n" + "=" * 100)
    p("1. HEADLINE WAPE/BIAS por semana (LIMPIO)")
    p("=" * 100)
    p(f"\n  {'semana':12s} | {'n':>6s} | {'real':>9s} | {'fcst':>9s} | {'WAPE':>6s} | {'BIAS':>7s}")
    p(f"  {'-'*12} | {'-'*6} | {'-'*9} | {'-'*9} | {'-'*6} | {'-'*7}")
    for wk in sorted(df["target_week_start"].unique()):
        m = _metrics(df[df["target_week_start"] == wk])
        p(f"  {wk} | {m['n']:>6,d} | {m['real']:>9,.0f} | {m['fcst']:>9,.0f} | {m['WAPE']:>5.1f}% | {m['BIAS']:>+6.1f}%")
    # Total
    m_t = _metrics(df)
    p(f"  {'TOTAL':12s} | {m_t['n']:>6,d} | {m_t['real']:>9,.0f} | {m_t['fcst']:>9,.0f} | {m_t['WAPE']:>5.1f}% | {m_t['BIAS']:>+6.1f}%")

    # === 2. Validar trend correction ===
    p("\n" + "=" * 100)
    p("2. VALIDAR trend correction (mu_week_pre_bias vs forecast_qty)")
    p("=" * 100)
    df["delta"] = df["mu_week_pre_bias"] - df["forecast_qty"]
    n_diff = (df["delta"].abs() > 0.5).sum()
    p(f"  Filas con mu_week_pre_bias != forecast_qty: {n_diff:,} ({n_diff/len(df)*100:.1f}%)")
    if n_diff > 0:
        p(f"  delta_pre_post stats:")
        p(df["delta"].describe().to_string())

    # Factor implicito por team
    p("\n  Factor implicito por team y semana:")
    for wk in sorted(df["target_week_start"].unique()):
        sub = df[(df["target_week_start"] == wk) & (df["mu_week_pre_bias"] > 0) & (df["forecast_qty"] > 0)].copy()
        by_team = sub.groupby("team_id").apply(
            lambda d: pd.Series({
                "n": len(d),
                "pre_sum": d["mu_week_pre_bias"].sum(),
                "post_sum": d["forecast_qty"].sum(),
                "factor": d["forecast_qty"].sum() / d["mu_week_pre_bias"].sum() if d["mu_week_pre_bias"].sum() > 0 else float("nan"),
            }), include_groups=False
        ).round(3)
        p(f"\n  --- {wk} ---")
        p(by_team.to_string())

    # === 3. Distribucion de forecast_model_code y regimen ===
    p("\n" + "=" * 100)
    p("3. Distribucion forecast_model_code y regimen por semana")
    p("=" * 100)
    p("\nforecast_model_code:")
    p(df.groupby(["target_week_start", "forecast_model_code"]).size().unstack(fill_value=0).to_string())
    p("\nregimen:")
    p(df.groupby(["target_week_start", "regimen"]).size().unstack(fill_value=0).to_string())
    p("\nforecast_zone:")
    p(df.groupby(["target_week_start", "forecast_zone"]).size().unstack(fill_value=0).to_string())

    # === 4. Sanity: chequeo del bug Apr-06 ===
    p("\n" + "=" * 100)
    p("4. SANITY: chequeo % min_stock_or_manual (bug Apr-06 era 99%)")
    p("=" * 100)
    for wk in sorted(df["target_week_start"].unique()):
        sub = df[df["target_week_start"] == wk]
        n = len(sub)
        n_min = (sub["forecast_model_code"] == "min_stock_or_manual").sum()
        p(f"  {wk}: {n_min:>6,d} / {n:>6,d} ({n_min/n*100:.1f}%)")
    p("\n  (referencia: Feb-16 13%, Mar-16 14%, Apr-06 99% [BUG])")

    # === 5. Por categoria, top 15 contribucion al WAPE ===
    p("\n" + "=" * 100)
    p("5. Top 15 categorias por contribucion al WAPE (3 semanas total)")
    p("=" * 100)
    cat = df.groupby("categ_id").apply(lambda d: pd.Series({
        "n": len(d),
        "real": d["real_qty"].sum(),
        "fcst": d["forecast_qty"].sum(),
        "ae": (d["forecast_qty"] - d["real_qty"]).abs().sum(),
        "err": (d["real_qty"] - d["forecast_qty"]).sum(),
    }), include_groups=False)
    cat["WAPE_pct"] = (cat["ae"] / cat["real"]).where(cat["real"] > 0) * 100
    cat["BIAS_pct"] = (cat["err"] / cat["real"]).where(cat["real"] > 0) * 100
    cat["share_ae"] = (cat["ae"] / cat["ae"].sum() * 100)
    top = cat.sort_values("ae", ascending=False).head(15)
    p(top[["n", "real", "fcst", "WAPE_pct", "BIAS_pct", "share_ae"]].round(1).to_string())

    # === 6. Por team ===
    p("\n" + "=" * 100)
    p("6. WAPE/BIAS por team x semana")
    p("=" * 100)
    for wk in sorted(df["target_week_start"].unique()):
        p(f"\n  --- {wk} ---")
        rows = []
        for team in sorted(df["team_id"].unique()):
            sub = df[(df["target_week_start"] == wk) & (df["team_id"] == team)]
            m = _metrics(sub)
            # factor implicito
            pre = sub["mu_week_pre_bias"].sum()
            post = sub["forecast_qty"].sum()
            fac = post / pre if pre > 0 else float("nan")
            rows.append({
                "team": team,
                "factor": round(fac, 3),
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
