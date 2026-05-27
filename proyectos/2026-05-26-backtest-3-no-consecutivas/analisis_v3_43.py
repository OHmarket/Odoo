"""
Analisis de la corrida con v3.43 (trend correction activa).
Compara contra:
  - baseline v3.42 (sin trend correction)
  - simulacion M_w8_asym proyectada
Valida que mu_week_pre_bias != forecast_qty (signal de que el factor se aplico).
"""
from __future__ import annotations
from pathlib import Path
import io
import pandas as pd

CSV_NEW = Path(r"c:\Users\sanhu\Odoo\OH Forecast Backtest (x_forecast_backtest) (2).csv")
CSV_OLD = Path(r"c:\Users\sanhu\Odoo\OH Forecast Backtest (x_forecast_backtest) (1).csv")
OUT = Path(__file__).parent / "v3_43_results.txt"

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
    df["categ_lower"] = df["categ_id"].fillna("").astype(str).str.lower()
    df["team_lower"] = df["team_id"].fillna("").astype(str).str.lower()
    n_c = df["categ_lower"].apply(lambda s: any(k in s for k in NOISE_CATEG))
    n_t = df["team_lower"].apply(lambda s: any(k in s for k in NOISE_TEAM))
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

    new = _load(CSV_NEW)
    old = _load(CSV_OLD)
    p(f"NEW (v3.43): {len(new):,} filas limpio | semanas: {sorted(new['target_week_start'].unique())}")
    p(f"OLD (v3.42): {len(old):,} filas limpio")

    # === 1. Validar trend correction se aplico ===
    p("\n" + "=" * 100)
    p("1. VALIDACION: mu_week_pre_bias vs forecast_qty (debe ser distinto si trend!=1.0)")
    p("=" * 100)
    new["delta_pre_post"] = new["mu_week_pre_bias"] - new["forecast_qty"]
    n_diff = (new["delta_pre_post"].abs() > 0.5).sum()
    p(f"\n  Filas donde mu_week_pre_bias != forecast_qty: {n_diff:,} ({n_diff/len(new)*100:.1f}%)")
    if n_diff > 0:
        p(f"  delta_pre_post stats:")
        p(new["delta_pre_post"].describe().to_string())
    else:
        p("  [WARN] mu_week_pre_bias == forecast_qty para TODOS - trend factor no se aplico!")

    # Por team: muestra el ratio implícito (forecast_qty / mu_week_pre_bias)
    p("\n  Trend factor implicito por team (forecast_qty / mu_week_pre_bias):")
    for wk in sorted(new["target_week_start"].unique()):
        p(f"\n  --- {wk} ---")
        sub = new[(new["target_week_start"] == wk) &
                  (new["mu_week_pre_bias"] > 0) &
                  (new["forecast_qty"] > 0)].copy()
        by_team = sub.groupby("team_id").apply(
            lambda d: pd.Series({
                "n": len(d),
                "sum_pre": d["mu_week_pre_bias"].sum(),
                "sum_post": d["forecast_qty"].sum(),
                "factor_implicit": d["forecast_qty"].sum() / d["mu_week_pre_bias"].sum()
                                    if d["mu_week_pre_bias"].sum() > 0 else float("nan"),
            }), include_groups=False
        ).round(3)
        p(by_team.to_string())

    # === 2. HEADLINE comparativo ===
    p("\n" + "=" * 100)
    p("2. HEADLINE: WAPE / BIAS por semana NEW (v3.43 trend ON) vs OLD (v3.42 baseline)")
    p("=" * 100)
    p(f"\n  {'semana':12s} | {'WAPE old':>10s} | {'WAPE new':>10s} | {'delta':>8s} || {'BIAS old':>10s} | {'BIAS new':>10s} | {'delta':>8s}")
    p(f"  {'-'*12} | {'-'*10} | {'-'*10} | {'-'*8} || {'-'*10} | {'-'*10} | {'-'*8}")
    for wk in sorted(new["target_week_start"].unique()):
        m_new = _metrics(new[new["target_week_start"] == wk])
        m_old = _metrics(old[old["target_week_start"] == wk])
        d_wape = m_new["WAPE"] - m_old["WAPE"]
        d_bias = m_new["BIAS"] - m_old["BIAS"]
        p(f"  {wk:12s} | {m_old['WAPE']:>9.1f}% | {m_new['WAPE']:>9.1f}% | {d_wape:>+7.2f}pp || {m_old['BIAS']:>+9.1f}% | {m_new['BIAS']:>+9.1f}% | {d_bias:>+7.2f}pp")

    # Total
    real_t_o = old["real_qty"].sum()
    real_t_n = new["real_qty"].sum()
    ae_t_o = (old["forecast_qty"] - old["real_qty"]).abs().sum()
    ae_t_n = (new["forecast_qty"] - new["real_qty"]).abs().sum()
    err_t_o = (old["real_qty"] - old["forecast_qty"]).sum()
    err_t_n = (new["real_qty"] - new["forecast_qty"]).sum()
    p(f"  {'TOTAL':12s} | {ae_t_o/real_t_o*100:>9.1f}% | {ae_t_n/real_t_n*100:>9.1f}% | {(ae_t_n/real_t_n - ae_t_o/real_t_o)*100:>+7.2f}pp || {err_t_o/real_t_o*100:>+9.1f}% | {err_t_n/real_t_n*100:>+9.1f}% | {(err_t_n/real_t_n - err_t_o/real_t_o)*100:>+7.2f}pp")

    # === 3. Detalle por team Mar-16 ===
    p("\n" + "=" * 100)
    p("3. DETALLE POR TEAM Mar-16 (NEW vs OLD)")
    p("=" * 100)
    rows = []
    wk = "2026-03-16"
    for team in sorted(new["team_id"].unique()):
        sub_n = new[(new["target_week_start"] == wk) & (new["team_id"] == team)]
        sub_o = old[(old["target_week_start"] == wk) & (old["team_id"] == team)]
        m_n = _metrics(sub_n)
        m_o = _metrics(sub_o)
        # factor implicito
        pre_sum = sub_n["mu_week_pre_bias"].sum()
        post_sum = sub_n["forecast_qty"].sum()
        fac = post_sum / pre_sum if pre_sum > 0 else float("nan")
        rows.append({
            "team": team,
            "factor": round(fac, 3),
            "real": m_n["real"],
            "fc_old": m_o["fcst"],
            "fc_new": m_n["fcst"],
            "WAPE_old": round(m_o["WAPE"], 1),
            "WAPE_new": round(m_n["WAPE"], 1),
            "BIAS_old": round(m_o["BIAS"], 1),
            "BIAS_new": round(m_n["BIAS"], 1),
        })
    p(pd.DataFrame(rows).to_string(index=False))

    # === 4. Detalle por regimen Mar-16 ===
    p("\n" + "=" * 100)
    p("4. DELTA por REGIMEN en Mar-16")
    p("=" * 100)
    rows = []
    for reg in sorted(new[new["target_week_start"] == wk]["regimen"].dropna().unique()):
        sub_n = new[(new["target_week_start"] == wk) & (new["regimen"] == reg)]
        sub_o = old[(old["target_week_start"] == wk) & (old["regimen"] == reg)]
        m_n = _metrics(sub_n)
        m_o = _metrics(sub_o)
        rows.append({
            "regimen": reg,
            "n": m_n["n"],
            "real": m_n["real"],
            "WAPE_old": round(m_o["WAPE"], 1),
            "WAPE_new": round(m_n["WAPE"], 1),
            "BIAS_old": round(m_o["BIAS"], 1),
            "BIAS_new": round(m_n["BIAS"], 1),
            "delta_WAPE": round(m_n["WAPE"] - m_o["WAPE"], 2),
            "delta_BIAS": round(m_n["BIAS"] - m_o["BIAS"], 2),
        })
    p(pd.DataFrame(rows).to_string(index=False))

    # === 5. Top categs Mar-16 ===
    p("\n" + "=" * 100)
    p("5. TOP 15 categorias por contribucion al WAPE Mar-16 - NEW vs OLD")
    p("=" * 100)
    sub_w_new = new[new["target_week_start"] == wk]
    sub_w_old = old[old["target_week_start"] == wk]
    cat_n = sub_w_new.groupby("categ_id").apply(lambda d: pd.Series({
        "n": len(d),
        "real": d["real_qty"].sum(),
        "fc_new": d["forecast_qty"].sum(),
        "ae_new": (d["forecast_qty"] - d["real_qty"]).abs().sum(),
        "err_new": (d["real_qty"] - d["forecast_qty"]).sum(),
    }), include_groups=False)
    cat_o = sub_w_old.groupby("categ_id").apply(lambda d: pd.Series({
        "fc_old": d["forecast_qty"].sum(),
        "ae_old": (d["forecast_qty"] - d["real_qty"]).abs().sum(),
        "err_old": (d["real_qty"] - d["forecast_qty"]).sum(),
    }), include_groups=False)
    cat_j = cat_n.join(cat_o)
    cat_j["WAPE_old"] = (cat_j["ae_old"] / cat_j["real"]) * 100
    cat_j["WAPE_new"] = (cat_j["ae_new"] / cat_j["real"]) * 100
    cat_j["BIAS_old"] = (cat_j["err_old"] / cat_j["real"]) * 100
    cat_j["BIAS_new"] = (cat_j["err_new"] / cat_j["real"]) * 100
    cat_j["delta_BIAS"] = cat_j["BIAS_new"] - cat_j["BIAS_old"]
    top = cat_j.sort_values("ae_new", ascending=False).head(15)
    p(top[["n", "real", "fc_old", "fc_new", "WAPE_old", "WAPE_new", "BIAS_old", "BIAS_new", "delta_BIAS"]].round(1).to_string())

    OUT.write_text(buf.getvalue(), encoding="utf-8")
    print(f"Output saved to: {OUT}")


if __name__ == "__main__":
    main()
