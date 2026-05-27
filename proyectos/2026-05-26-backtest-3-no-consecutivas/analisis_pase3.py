"""
Pase 3 - Backtest 3 semanas SIN feriados, filtro de ruido corregido.

Semanas:
  - 2026-02-16  Feb sem 3, quincena, TEMPORADA ALTA verano
  - 2026-03-16  Mar sem 3, post-quincena, TRANSICION LIMPIA (sin Sem Santa)
  - 2026-04-06  Abr sem 2, post-Pascua, OFF-SEASON

Filtro corregido: 'impulso' (no 'impulsiv').
Output a archivo TXT para evitar crash de encoding del PowerShell.
"""
from __future__ import annotations
from pathlib import Path
import io
import pandas as pd

CSV_PATH = Path(r"c:\Users\sanhu\Odoo\OH Forecast Backtest (x_forecast_backtest) (1).csv")
OUT_PATH = Path(__file__).parent / "pase3_output.txt"

NOISE_CATEG_KEYWORDS = ["cerveza", "cigarr", "tabaco", "snack", "impulso"]
NOISE_TEAM_KEYWORDS = ["san jos"]

WEEKS = ["2026-02-16", "2026-03-16", "2026-04-06"]
WEEKS_AB = ["2026-02-16", "2026-03-16"]  # Feb vs Mar comparison limpio
WEEKS_BC = ["2026-03-16", "2026-04-06"]  # Mar vs Abr comparison

pd.set_option("display.float_format", lambda x: f"{x:,.2f}")
pd.set_option("display.max_columns", 60)
pd.set_option("display.width", 240)
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
    clean = df[~(noise_categ | noise_team)].copy()
    return df, clean, int(noise_categ.sum()), int(noise_team.sum())


def _delta_pivot(clean, dim, weeks, min_real=20):
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
    buf = io.StringIO()

    def p(s=""):
        buf.write(s + "\n")

    raw, clean, n_cat, n_team = _load()
    p(f"CSV: {CSV_PATH.name}")
    p(f"Filas raw: {len(raw):,}  | limpio: {len(clean):,}")
    p(f"Excluidos: categoria_ruido={n_cat:,}  team_ruido={n_team:,}")
    p(f"Semanas presentes en limpio:")
    p(clean.groupby("target_week_start").size().to_string())
    p(f"\nRegimenes presentes (limpio):")
    p(clean.groupby(["target_week_start", "regimen"]).size().unstack(fill_value=0).to_string())

    # === A. ABRIL: sigue roto o se arreglo? ===
    p("\n" + "=" * 100)
    p("A. SANITY ABRIL-06: el motor escribio forecast o sigue colapsado a REG-0?")
    p("=" * 100)
    abr = clean[clean["target_week_start"] == "2026-04-06"]
    fcst = abr["forecast_qty"].sum()
    real = abr["real_qty"].sum()
    n_with_fcst = (abr["forecast_qty"] > 0).sum()
    p(f"  filas Abr-06 limpio: {len(abr):,}")
    p(f"  con forecast>0: {n_with_fcst:,} ({n_with_fcst/len(abr)*100:.1f}%)")
    p(f"  forecast total: {fcst:,.0f}   real total: {real:,.0f}   WAPE={abr['abs_error_qty'].sum()/real*100:.1f}%")
    p(f"  forecast_model_code distribucion Abr-06:")
    p(abr.groupby("forecast_model_code").size().sort_values(ascending=False).to_string())

    # === B. HEADLINE ===
    p("\n" + "=" * 100)
    p("B. HEADLINE: WAPE / BIAS por semana (LIMPIO)")
    p("=" * 100)
    for w in WEEKS:
        d = clean[clean["target_week_start"] == w]
        real = d["real_qty"].sum()
        fcst = d["forecast_qty"].sum()
        abse = d["abs_error_qty"].sum()
        err = d["error_qty"].sum()
        wape = abse/real*100 if real > 0 else float("nan")
        bias = err/real*100 if real > 0 else float("nan")
        p(f"  {w}  n={len(d):>6,d}  real={real:>10,.0f}  fcst={fcst:>10,.0f}  WAPE={wape:>5.1f}%  BIAS={bias:>+6.1f}%")

    # Buckets
    p("\n  Buckets % por semana:")
    clean2 = clean.copy()
    clean2["bucket"] = clean2.apply(_bucket, axis=1)
    bk = clean2.groupby(["target_week_start", "bucket"]).size().unstack(fill_value=0)
    bk_pct = bk.div(bk.sum(axis=1), axis=0) * 100
    p(bk_pct.to_string())

    # === C. Delta Feb -> Mar (transicion limpia) ===
    p("\n" + "=" * 100)
    p("C. DELTA Feb-16 (temp alta) -> Mar-16 (transicion LIMPIA) por REGIMEN")
    p("=" * 100)
    d = _delta_pivot(clean, "regimen", WEEKS_AB, min_real=50)
    p(d.sort_values("delta_bias", ascending=False).to_string(index=False))

    p("\n" + "=" * 100)
    p("D. DELTA Feb-16 -> Mar-16 por TEAM")
    p("=" * 100)
    d = _delta_pivot(clean, "team_id", WEEKS_AB, min_real=100)
    p(d.sort_values("delta_bias", ascending=False).to_string(index=False))

    p("\n" + "=" * 100)
    p("E. DELTA Feb-16 -> Mar-16 por ABCXYZ")
    p("=" * 100)
    d = _delta_pivot(clean, "abcxyz", WEEKS_AB, min_real=50)
    p(d.sort_values("delta_bias", ascending=False).to_string(index=False))

    p("\n" + "=" * 100)
    p("F. DELTA Feb-16 -> Mar-16 por SERIES_TYPE")
    p("=" * 100)
    d = _delta_pivot(clean, "series_type", WEEKS_AB, min_real=50)
    p(d.sort_values("delta_bias", ascending=False).to_string(index=False))

    p("\n" + "=" * 100)
    p("G. DELTA Feb-16 -> Mar-16 por CICLO_DE_VIDA")
    p("=" * 100)
    d = _delta_pivot(clean, "ciclo_de_vida", WEEKS_AB, min_real=50)
    p(d.sort_values("delta_bias", ascending=False).to_string(index=False))

    p("\n" + "=" * 100)
    p("H. DELTA Feb-16 -> Mar-16 por IMPORTANCIA")
    p("=" * 100)
    d = _delta_pivot(clean, "importancia", WEEKS_AB, min_real=50)
    p(d.sort_values("delta_bias", ascending=False).to_string(index=False))

    p("\n" + "=" * 100)
    p("I. DELTA Feb-16 -> Mar-16 top 25 CATEGORIAS por delta_bias desc")
    p("=" * 100)
    d = _delta_pivot(clean, "categ_id", WEEKS_AB, min_real=100)
    p(d.sort_values("delta_bias", ascending=False).head(25).to_string(index=False))

    p("\n" + "=" * 100)
    p("J. DELTA Feb-16 -> Mar-16 top 15 CATEGORIAS que MEJORAN BIAS (over-forecast Mar)")
    p("=" * 100)
    p(d.sort_values("delta_bias", ascending=True).head(15).to_string(index=False))

    # === Mar -> Abr (si Abr funciono) ===
    if (clean["target_week_start"] == "2026-04-06").any() and clean[clean["target_week_start"] == "2026-04-06"]["forecast_qty"].sum() > 1000:
        p("\n" + "=" * 100)
        p("K. DELTA Mar-16 -> Abr-06 por REGIMEN (off-season pura)")
        p("=" * 100)
        d = _delta_pivot(clean, "regimen", WEEKS_BC, min_real=50)
        p(d.sort_values("delta_bias", ascending=False).to_string(index=False))

        p("\n" + "=" * 100)
        p("L. DELTA Mar-16 -> Abr-06 por ABCXYZ")
        p("=" * 100)
        d = _delta_pivot(clean, "abcxyz", WEEKS_BC, min_real=50)
        p(d.sort_values("delta_bias", ascending=False).to_string(index=False))

        p("\n" + "=" * 100)
        p("M. 3 SEMANAS por REGIMEN (vista completa)")
        p("=" * 100)
        rows = []
        for reg in sorted(clean["regimen"].dropna().unique()):
            for w in WEEKS:
                s = clean[(clean["regimen"] == reg) & (clean["target_week_start"] == w)]
                real = s["real_qty"].sum()
                wape = s["abs_error_qty"].sum() / real * 100 if real > 0 else float("nan")
                bias = s["error_qty"].sum() / real * 100 if real > 0 else float("nan")
                rows.append({"regimen": reg, "week": w, "n": len(s), "real": real,
                             "fcst": s["forecast_qty"].sum(), "wape_pct": wape, "bias_pct": bias})
        p(pd.DataFrame(rows).to_string(index=False))
    else:
        p("\n" + "=" * 100)
        p("K. ABRIL SIGUE ROTO  -- skipping Mar->Abr comparison")
        p("=" * 100)

    # === Sanity bias correction ===
    p("\n" + "=" * 100)
    p("N. mu_week_pre_bias vs forecast_qty por semana")
    p("=" * 100)
    for w in WEEKS:
        d = clean[clean["target_week_start"] == w]
        pre = d["mu_week_pre_bias"].sum()
        post = d["forecast_qty"].sum()
        same = (d["mu_week_pre_bias"] == d["forecast_qty"]).all()
        p(f"  {w}: pre={pre:,.1f}  post={post:,.1f}  identical={same}")

    # Top categorias por contribucion total al WAPE absoluto (3 semanas)
    p("\n" + "=" * 100)
    p("O. Top 20 categorias por contribucion al WAPE absoluto (3 semanas, limpio)")
    p("=" * 100)
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
    p(cat_g.sort_values("abs_err", ascending=False).head(20).to_string())

    OUT_PATH.write_text(buf.getvalue(), encoding="utf-8")
    print(f"Output saved to: {OUT_PATH}")
    print(f"Filas analizadas (limpio): {len(clean):,}")


if __name__ == "__main__":
    main()
