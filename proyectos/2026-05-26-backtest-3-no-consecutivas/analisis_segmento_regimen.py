"""
Analisis por regimen (REG-0..REG-8) del backtest v3.46 vs v3.44.

Objetivo: ver migracion de SKUs entre regimenes (v3.44 -> v3.46) y como
pega cada regimen (WAPE/BIAS, real/fcst, modelo dominante).

Output: regimen_results.txt
"""
from __future__ import annotations
from pathlib import Path
import io
import pandas as pd

CSVS = {
    "v3.44": Path(r"c:\Users\sanhu\Odoo\OH Forecast Backtest (x_forecast_backtest).csv"),
    "v3.46": Path(r"c:\Users\sanhu\Odoo\OH Forecast Backtest (x_forecast_backtest) (2).csv"),
}
OUT = Path(__file__).parent / "regimen_results.txt"

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
    df["regimen"] = df["regimen"].fillna("(vacio)").astype(str)
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

    # ===== 1. Migracion de SKUs entre regimenes =====
    p("=" * 110)
    p("1. Migracion de SKUs por regimen: v3.44 -> v3.46 (las 3 semanas agregadas)")
    p("=" * 110)
    counts = {}
    for ver, df in dfs.items():
        counts[ver] = df.groupby("regimen").size()
    cmp = pd.DataFrame({"v3.44": counts["v3.44"], "v3.46": counts["v3.46"]}).fillna(0).astype(int)
    cmp["delta"] = cmp["v3.46"] - cmp["v3.44"]
    cmp["delta_pct"] = (cmp["delta"] / cmp["v3.44"].replace(0, 1) * 100).round(1)
    p("")
    p(cmp.to_string())

    # ===== 2. WAPE / BIAS por regimen =====
    p("\n" + "=" * 110)
    p("2. WAPE / BIAS por regimen (3 semanas agregadas)")
    p("=" * 110)
    rows = []
    for reg in sorted(dfs["v3.46"]["regimen"].unique()):
        m44 = _metrics(dfs["v3.44"][dfs["v3.44"]["regimen"] == reg])
        m46 = _metrics(dfs["v3.46"][dfs["v3.46"]["regimen"] == reg])
        rows.append({
            "regimen": reg,
            "n_v44": m44["n"],
            "n_v46": m46["n"],
            "real_v46": round(m46["real"], 0),
            "fcst_v44": round(m44["fcst"], 1),
            "fcst_v46": round(m46["fcst"], 1),
            "WAPE_v44": round(m44["WAPE"], 1),
            "WAPE_v46": round(m46["WAPE"], 1),
            "BIAS_v44": round(m44["BIAS"], 1),
            "BIAS_v46": round(m46["BIAS"], 1),
        })
    p("")
    p(pd.DataFrame(rows).to_string(index=False))

    # ===== 3. Modelo dominante por regimen (v3.46) =====
    p("\n" + "=" * 110)
    p("3. forecast_model_code por regimen (v3.46) - que engine sirve a cada regimen")
    p("=" * 110)
    pivot = dfs["v3.46"].groupby(["regimen", "forecast_model_code"]).size().unstack(fill_value=0)
    p("")
    p(pivot.to_string())

    # ===== 4. Distribucion forecast_qty por regimen (v3.46) =====
    p("\n" + "=" * 110)
    p("4. Distribucion forecast_qty por regimen (v3.46) - cuantos quedan en 0 vs continuo")
    p("=" * 110)
    v46 = dfs["v3.46"]
    rows2 = []
    for reg in sorted(v46["regimen"].unique()):
        s = v46[v46["regimen"] == reg]
        n = len(s)
        n_zero = (s["forecast_qty"] == 0).sum()
        n_lt05 = ((s["forecast_qty"] > 0) & (s["forecast_qty"] < 0.5)).sum()
        n_05_1 = ((s["forecast_qty"] >= 0.5) & (s["forecast_qty"] < 1.0)).sum()
        n_ge1 = (s["forecast_qty"] >= 1.0).sum()
        rows2.append({
            "regimen": reg,
            "n": n,
            "==0": n_zero,
            "==0%": f"{n_zero/n*100:.1f}%" if n else "-",
            "(0,0.5)": n_lt05,
            "[0.5,1)": n_05_1,
            ">=1": n_ge1,
            "real_tot": int(s["real_qty"].sum()),
        })
    p("")
    p(pd.DataFrame(rows2).to_string(index=False))

    # ===== 5. Donde estan los SKUs migrados (REG-7 v3.44 -> que regimen v3.46) =====
    p("\n" + "=" * 110)
    p("5. Migracion concreta REG-7 v3.44 (catch-all min_stock) -> v3.46")
    p("=" * 110)
    p("    Cruce por (product_id, team_id, target_week_start)")
    key_cols = ["product_id", "team_id", "target_week_start"]
    v44_r7 = dfs["v3.44"][dfs["v3.44"]["regimen"] == "REG-7"][key_cols + ["forecast_qty", "real_qty"]].copy()
    v44_r7.columns = key_cols + ["fcst_v44", "real_v44"]
    v46_keys = dfs["v3.46"][key_cols + ["regimen", "forecast_model_code", "forecast_qty", "real_qty"]].copy()
    v46_keys.columns = key_cols + ["regimen_v46", "model_v46", "fcst_v46", "real_v46"]
    merged = v44_r7.merge(v46_keys, on=key_cols, how="left")
    p(f"\n  SKUs en REG-7 (v3.44): {len(merged):,}")
    p(f"  Cruzados con v3.46:    {merged['regimen_v46'].notna().sum():,}")
    p("\n  Hacia donde migraron (regimen v3.46):")
    p(merged.groupby("regimen_v46").size().to_string())
    p("\n  Modelo asignado en v3.46:")
    p(merged.groupby("model_v46").size().to_string())
    p("\n  Performance del bloque migrado:")
    mig = merged[merged["regimen_v46"].notna()]
    real_tot = mig["real_v46"].sum()
    fc_v44_tot = mig["fcst_v44"].sum()
    fc_v46_tot = mig["fcst_v46"].sum()
    ae_v44 = (mig["fcst_v44"] - mig["real_v46"]).abs().sum()
    ae_v46 = (mig["fcst_v46"] - mig["real_v46"]).abs().sum()
    err_v44 = (mig["real_v46"] - mig["fcst_v44"]).sum()
    err_v46 = (mig["real_v46"] - mig["fcst_v46"]).sum()
    p(f"    real:       {real_tot:,.0f}")
    p(f"    fcst v3.44: {fc_v44_tot:,.1f}  WAPE {ae_v44/real_tot*100:.1f}%  BIAS {err_v44/real_tot*100:+.1f}%")
    p(f"    fcst v3.46: {fc_v46_tot:,.1f}  WAPE {ae_v46/real_tot*100:.1f}%  BIAS {err_v46/real_tot*100:+.1f}%")

    OUT.write_text(buf.getvalue(), encoding="utf-8")
    print(f"Output: {OUT}")


if __name__ == "__main__":
    main()
