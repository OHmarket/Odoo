"""
Analisis pase 1 - Backtest 3 semanas no-consecutivas
=====================================================
Objetivo: medir robustez del motor HM-SI v4.3 frente a:
  - Distinta posicion-en-mes (semana 3 / 5 / 2 = quincena / fin-mes / post-payday)
  - Transicion de temporada alta verano (Feb alta -> Mar transicion -> Abr off-season)

Semanas objetivo (target_week_start, lunes):
  - 2026-02-16 (sem 3 Feb, quincena, temporada alta)
  - 2026-03-30 (sem 5 Mar, fin-mes/payday, transicion)
  - 2026-04-06 (sem 2 Abr, post-payday, off-season)

Filtro de ruido (memoria forecast_noise_feedback):
  - Excluir cervezas, cigarros/tabacos, snacks, impulsivos.
  - Excluir team "Ventas San Jose" (clasica fuente de ruido).
"""
from __future__ import annotations
from pathlib import Path
import pandas as pd

CSV_PATH = Path(r"c:\Users\sanhu\Odoo\OH Forecast Backtest (x_forecast_backtest).csv")

# Keywords para excluir categorias ruidosas
NOISE_CATEG_KEYWORDS = ["cerveza", "cigarr", "tabaco", "snack", "impulsiv"]
NOISE_TEAM_KEYWORDS = ["san jos"]

pd.set_option("display.float_format", lambda x: f"{x:,.2f}")
pd.set_option("display.max_columns", 60)
pd.set_option("display.width", 200)


def _wmape(df):
    real = df["real_qty"].sum()
    if real <= 0:
        return float("nan")
    return df["abs_error_qty"].sum() / real


def _bias(df):
    """error_qty = real - forecast. bias > 0 = sub-forecast, bias < 0 = over-forecast."""
    real = df["real_qty"].sum()
    if real <= 0:
        return float("nan")
    return df["error_qty"].sum() / real


def _summary(df, by):
    g = df.groupby(by, dropna=False)
    out = pd.DataFrame({
        "n": g.size(),
        "real": g["real_qty"].sum(),
        "fcst": g["forecast_qty"].sum(),
        "abs_err": g["abs_error_qty"].sum(),
        "err": g["error_qty"].sum(),
    })
    out["wape_pct"] = (out["abs_err"] / out["real"]).where(out["real"] > 0) * 100
    out["bias_pct"] = (out["err"] / out["real"]).where(out["real"] > 0) * 100
    return out.sort_values(by if isinstance(by, str) else by[0])


def _bucket(row):
    fc = row["forecast_qty"]
    r = row["real_qty"]
    if fc > 0 and r > 0:
        return "vendio_y_forecast"
    if fc > 0 and r <= 0:
        return "forecast_sin_venta"
    if fc <= 0 and r > 0:
        return "venta_sin_forecast"
    return "sin_movimiento"


def main():
    print(f"Leyendo {CSV_PATH.name} ...")
    df = pd.read_csv(CSV_PATH, low_memory=False)
    print(f"  filas={len(df):,}  columnas={len(df.columns)}")
    print(f"  columnas: {list(df.columns)}")

    # Normalizar tipos
    for col in ["forecast_qty", "real_qty", "abs_error_qty", "error_qty",
                "mu_week_pre_bias", "ape", "bias_pct", "cv2"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)

    df["categ_lower"] = df["categ_id"].fillna("").astype(str).str.lower()
    df["team_lower"] = df["team_id"].fillna("").astype(str).str.lower()

    # Filtro ruido
    noise_categ = df["categ_lower"].apply(lambda s: any(k in s for k in NOISE_CATEG_KEYWORDS))
    noise_team = df["team_lower"].apply(lambda s: any(k in s for k in NOISE_TEAM_KEYWORDS))
    is_noise = noise_categ | noise_team

    print(f"\nFilas ruido (excluidas): {is_noise.sum():,} ({is_noise.mean()*100:.1f}%)")
    print(f"  por categoria: {noise_categ.sum():,}")
    print(f"  por team:      {noise_team.sum():,}")

    clean = df[~is_noise].copy()
    clean["bucket"] = clean.apply(_bucket, axis=1)
    df["bucket"] = df.apply(_bucket, axis=1)

    print("\n" + "=" * 80)
    print("0. SANITY CHECK")
    print("=" * 80)
    print("\nFilas por target_week_start (todas):")
    print(df.groupby("target_week_start").size().to_string())
    print("\nFilas por team (todas):")
    print(df.groupby("team_id").size().sort_values(ascending=False).to_string())
    print("\nMethods presentes:", df["method"].unique().tolist())
    print("Regimenes presentes:", sorted(df["regimen"].dropna().unique().tolist()))

    print("\n" + "=" * 80)
    print("1. HEADLINE: WAPE / BIAS por semana")
    print("=" * 80)

    for label, data in [("RAW (con ruido)", df), ("LIMPIO (sin ruido)", clean)]:
        print(f"\n[{label}]")
        s = _summary(data, "target_week_start")
        print(s[["n", "real", "fcst", "wape_pct", "bias_pct"]].to_string())
        print(f"  GLOBAL  wape={_wmape(data)*100:.1f}%  bias={_bias(data)*100:+.1f}%")

    print("\n" + "=" * 80)
    print("2. WAPE / BIAS por regimen x semana  (sobre LIMPIO)")
    print("=" * 80)
    pivot_w = clean.pivot_table(
        index="regimen",
        columns="target_week_start",
        values=["abs_error_qty", "real_qty", "error_qty"],
        aggfunc="sum",
        fill_value=0,
    )
    weeks = sorted(clean["target_week_start"].unique())
    rows = []
    for reg in sorted(clean["regimen"].dropna().unique()):
        for w in weeks:
            sub = clean[(clean["regimen"] == reg) & (clean["target_week_start"] == w)]
            real = sub["real_qty"].sum()
            wape = sub["abs_error_qty"].sum() / real * 100 if real > 0 else float("nan")
            bias = sub["error_qty"].sum() / real * 100 if real > 0 else float("nan")
            rows.append({
                "regimen": reg, "week": w, "n": len(sub),
                "real": real, "fcst": sub["forecast_qty"].sum(),
                "wape_pct": wape, "bias_pct": bias,
            })
    reg_wk = pd.DataFrame(rows)
    print(reg_wk.to_string(index=False))

    print("\n" + "=" * 80)
    print("3. WAPE / BIAS por team x semana  (sobre LIMPIO)")
    print("=" * 80)
    rows = []
    for team in sorted(clean["team_id"].dropna().unique()):
        for w in weeks:
            sub = clean[(clean["team_id"] == team) & (clean["target_week_start"] == w)]
            real = sub["real_qty"].sum()
            wape = sub["abs_error_qty"].sum() / real * 100 if real > 0 else float("nan")
            bias = sub["error_qty"].sum() / real * 100 if real > 0 else float("nan")
            rows.append({
                "team": team, "week": w, "n": len(sub),
                "real": real, "fcst": sub["forecast_qty"].sum(),
                "wape_pct": wape, "bias_pct": bias,
            })
    print(pd.DataFrame(rows).to_string(index=False))

    print("\n" + "=" * 80)
    print("4. Distribucion de buckets por semana  (sobre LIMPIO)")
    print("=" * 80)
    bk = clean.groupby(["target_week_start", "bucket"]).size().unstack(fill_value=0)
    bk_pct = bk.div(bk.sum(axis=1), axis=0) * 100
    print("Counts:")
    print(bk.to_string())
    print("\n% por semana:")
    print(bk_pct.to_string())

    print("\n" + "=" * 80)
    print("5. Efecto bias correction: mu_week_pre_bias vs forecast_qty (sobre LIMPIO)")
    print("=" * 80)
    for w in weeks:
        sub = clean[clean["target_week_start"] == w]
        real = sub["real_qty"].sum()
        if real <= 0:
            continue
        fc_pre = sub["mu_week_pre_bias"].sum()
        fc_post = sub["forecast_qty"].sum()
        ae_pre = (sub["mu_week_pre_bias"] - sub["real_qty"]).abs().sum()
        ae_post = sub["abs_error_qty"].sum()
        err_pre = (sub["real_qty"] - sub["mu_week_pre_bias"]).sum()
        err_post = sub["error_qty"].sum()
        print(f"  {w}:")
        print(f"    real={real:>10,.0f}  fcst_pre={fc_pre:>10,.0f}  fcst_post={fc_post:>10,.0f}")
        print(f"    WAPE_pre={ae_pre/real*100:>6.1f}%  WAPE_post={ae_post/real*100:>6.1f}%  delta={ (ae_post-ae_pre)/real*100:+.2f}pp")
        print(f"    BIAS_pre={err_pre/real*100:>+6.1f}%  BIAS_post={err_post/real*100:>+6.1f}%  delta={ (err_post-err_pre)/real*100:+.2f}pp")

    print("\n" + "=" * 80)
    print("6. Top 30 categorias por contribucion al WAPE absoluto  (sobre LIMPIO)")
    print("=" * 80)
    cat_g = clean.groupby("categ_id").agg(
        n=("abs_error_qty", "size"),
        real=("real_qty", "sum"),
        fcst=("forecast_qty", "sum"),
        abs_err=("abs_error_qty", "sum"),
        err=("error_qty", "sum"),
    )
    cat_g["wape_pct"] = (cat_g["abs_err"] / cat_g["real"]).where(cat_g["real"] > 0) * 100
    cat_g["bias_pct"] = (cat_g["err"] / cat_g["real"]).where(cat_g["real"] > 0) * 100
    cat_g["share_abs_err"] = cat_g["abs_err"] / cat_g["abs_err"].sum() * 100
    print(cat_g.sort_values("abs_err", ascending=False).head(30).to_string())


if __name__ == "__main__":
    main()
