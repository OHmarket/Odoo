"""
Simulacion: aplicar trend factor por team al forecast del backtest CSV
usando YoY units de x_sales_month_team_kpi. Comparar WAPE/BIAS antes y despues.

Variantes a probar:
  A) Last month YoY                 (mas reactivo, mas ruidoso)
  B) Avg last 3 months YoY          (estable)
  C) Avg last 6 months YoY          (mas estable, menos reactivo)
  D) Median last 6 months YoY       (robusto a outliers como Jan-26 +4.9%)

Pasos:
  1. Mapear nombres pos.config (CSV) -> crm.team.id (modelo Sales)
  2. Pull x_sales_month_team_kpi por mes y team
  3. Para cada cutoff del backtest, calcular trend_factor por team (clamp 0.7-1.3)
  4. Aplicar al forecast_qty, recalcular WAPE/BIAS
  5. Reporte side-by-side: baseline vs cada variante
"""
from __future__ import annotations
import sys
import io
from pathlib import Path
from datetime import date
import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

CSV_PATH = Path(r"c:\Users\sanhu\Odoo\OH Forecast Backtest (x_forecast_backtest) (1).csv")
OUT_PATH = Path(__file__).parent / "sim_trend_factor_output.txt"

NOISE_CATEG_KEYWORDS = ["cerveza", "cigarr", "tabaco", "snack", "impulso"]
NOISE_TEAM_KEYWORDS = ["san jos"]

# Mes cerrado mas reciente antes del cutoff de cada target_week
# Feb-16 (cutoff Feb-15)  -> Jan-26
# Mar-16 (cutoff Mar-15)  -> Feb-26
# Apr-06 (cutoff Apr-05)  -> Mar-26
CUTOFF_TO_LAST_MONTH = {
    "2026-02-16": date(2026, 1, 1),
    "2026-03-16": date(2026, 2, 1),
    "2026-04-06": date(2026, 3, 1),
}

CLAMP_LOW = 0.70
CLAMP_HIGH = 1.30

pd.set_option("display.float_format", lambda x: f"{x:,.2f}")
pd.set_option("display.max_columns", 60)
pd.set_option("display.width", 240)


def _load_csv():
    df = pd.read_csv(CSV_PATH, low_memory=False, encoding="latin-1")
    for c in ["forecast_qty", "real_qty", "abs_error_qty", "error_qty"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    df["categ_lower"] = df["categ_id"].fillna("").astype(str).str.lower()
    df["team_lower"] = df["team_id"].fillna("").astype(str).str.lower()
    noise_c = df["categ_lower"].apply(lambda s: any(k in s for k in NOISE_CATEG_KEYWORDS))
    noise_t = df["team_lower"].apply(lambda s: any(k in s for k in NOISE_TEAM_KEYWORDS))
    return df[~(noise_c | noise_t)].copy()


def _summary(df, label):
    real = df["real_qty"].sum()
    fc = df["forecast_corrected"].sum()
    ae = (df["forecast_corrected"] - df["real_qty"]).abs().sum()
    err = (df["real_qty"] - df["forecast_corrected"]).sum()
    wape = ae / real * 100 if real > 0 else float("nan")
    bias = err / real * 100 if real > 0 else float("nan")
    return f"  {label:30s}  real={real:>8,.0f}  fcst={fc:>8,.0f}  WAPE={wape:>5.1f}%  BIAS={bias:>+6.1f}%"


def main():
    buf = io.StringIO()
    def p(s=""): buf.write(s + "\n")

    odoo = OdooReader()
    p(f"Conectado: {odoo}\n")

    # === 1. CSV del backtest ===
    csv_df = _load_csv()
    csv_df["forecast_corrected"] = csv_df["forecast_qty"]  # baseline = sin corregir
    p(f"CSV filas (limpio): {len(csv_df):,}")
    p(f"Teams en CSV: {csv_df['team_id'].nunique()}")

    # === 2. Mapeo CSV team label -> crm_team_id ===
    # CSV label es "Ventas X". pos.config.name es "X Caja N". Hay que strippear.
    p("\n--- Mapping CSV team label -> crm_team_id (via prefix de pos.config) ---")
    pos_cfgs = odoo.search_read(
        'pos.config',
        domain=[],
        fields=['id', 'name', 'crm_team_id'],
    )
    # Group pos.config by crm_team_id, derivar prefix comun (parte antes de " Caja")
    team_to_names = {}
    for c in pos_cfgs:
        nm = c.get('name') or ''
        tm = c.get('crm_team_id')
        if not tm: continue
        tid = tm[0]
        team_to_names.setdefault(tid, []).append(nm)
    # Derivar el "local" name por team (antes de " Caja")
    name_to_team = {}
    for tid, names in team_to_names.items():
        prefixes = set()
        for nm in names:
            # "Coñaripe Caja 1" -> "Coñaripe"
            # "Nueva Imperial Caja 2" -> "Nueva Imperial"
            if ' Caja' in nm:
                prefixes.add(nm.split(' Caja')[0].strip())
            else:
                prefixes.add(nm.strip())
        # Si hay un solo prefix comun, ese es el local
        if len(prefixes) == 1:
            local = next(iter(prefixes))
            csv_label = f"Ventas {local}"
            name_to_team[csv_label] = tid

    csv_teams = sorted(csv_df["team_id"].unique())
    matched = 0
    for t in csv_teams:
        if t in name_to_team:
            matched += 1
            p(f"  OK  {t:30s} -> crm_team_id={name_to_team[t]}")
        else:
            p(f"  MISS {t:30s} (no match)")
    p(f"\n  Matched: {matched}/{len(csv_teams)}")

    # === 3. Pull x_sales_month_team_kpi ultimos 12 meses ===
    p("\n--- Pull x_sales_month_team_kpi ---")
    kpi = odoo.search_read(
        'x_sales_month_team_kpi',
        domain=[('x_studio_period_date', '>=', '2025-08-01'),
                ('x_studio_period_date', '<=', '2026-04-30')],
        fields=['x_studio_period_date', 'x_studio_team_id',
                'x_studio_units', 'x_studio_units_ly',
                'x_studio_yoy_units_pct'],
    )
    kpi_df = pd.DataFrame(kpi)
    kpi_df["team_crm_id"] = kpi_df["x_studio_team_id"].apply(lambda x: x[0] if isinstance(x, list) else x)
    kpi_df["period"] = pd.to_datetime(kpi_df["x_studio_period_date"]).dt.to_period("M").dt.to_timestamp()
    # yoy_units_pct viene como fraccion (-0.3 = -30%, no como pct). Confirmar.
    # En output anterior, agregado sale -6.7% via (units/ly - 1)*100, y por-team valores como -0.3.
    # Calcular YoY desde units/units_ly para ser robusto al formato.
    kpi_df["yoy_units"] = (kpi_df["x_studio_units"] / kpi_df["x_studio_units_ly"] - 1.0)
    kpi_df["yoy_units"] = kpi_df["yoy_units"].replace([np.inf, -np.inf], np.nan)
    p(f"  Filas: {len(kpi_df)}  meses: {sorted(kpi_df['period'].dt.strftime('%Y-%m').unique())}")

    # === 4. Calcular trend_factor por (team, cutoff, variante) ===
    p("\n--- Trend factors por team y cutoff ---")
    variants = ["A_last1", "B_avg3", "C_avg6", "D_med6"]

    factor_table = {}  # (week_start, team_crm_id, variant) -> factor

    for target_week, last_month in CUTOFF_TO_LAST_MONTH.items():
        for team_name, team_id in name_to_team.items():
            if team_name not in csv_teams:
                continue
            team_kpi = kpi_df[kpi_df["team_crm_id"] == team_id].sort_values("period")
            team_kpi = team_kpi[team_kpi["period"] <= pd.Timestamp(last_month)]

            if team_kpi.empty:
                for v in variants:
                    factor_table[(target_week, team_id, v)] = 1.0
                continue

            yoy_1 = team_kpi["yoy_units"].iloc[-1] if len(team_kpi) >= 1 else 0.0
            yoy_3 = team_kpi["yoy_units"].tail(3).mean() if len(team_kpi) >= 3 else yoy_1
            yoy_6 = team_kpi["yoy_units"].tail(6).mean() if len(team_kpi) >= 6 else yoy_3
            med_6 = team_kpi["yoy_units"].tail(6).median() if len(team_kpi) >= 6 else yoy_3

            for v, val in [("A_last1", yoy_1), ("B_avg3", yoy_3),
                           ("C_avg6", yoy_6), ("D_med6", med_6)]:
                f = max(CLAMP_LOW, min(CLAMP_HIGH, 1.0 + val))
                factor_table[(target_week, team_id, v)] = f

    # === 5. Aplicar factor por variante y medir ===
    p("\n--- Tabla factores por team (variante B_avg3) ---")
    rows = []
    for target_week in CUTOFF_TO_LAST_MONTH:
        for team_name, team_id in name_to_team.items():
            if team_name not in csv_teams:
                continue
            f = factor_table.get((target_week, team_id, "B_avg3"), 1.0)
            rows.append({"week": target_week, "team": team_name, "factor_B": round(f, 3)})
    fdf = pd.DataFrame(rows).pivot(index="team", columns="week", values="factor_B")
    p(fdf.to_string())

    # Tambien mostrar variante D
    p("\n--- Tabla factores por team (variante D_med6) ---")
    rows = []
    for target_week in CUTOFF_TO_LAST_MONTH:
        for team_name, team_id in name_to_team.items():
            if team_name not in csv_teams:
                continue
            f = factor_table.get((target_week, team_id, "D_med6"), 1.0)
            rows.append({"week": target_week, "team": team_name, "factor_D": round(f, 3)})
    fdf2 = pd.DataFrame(rows).pivot(index="team", columns="week", values="factor_D")
    p(fdf2.to_string())

    # === 6. Resultados por variante ===
    # Agregar el crm_team_id al CSV via mapeo
    csv_df["team_crm_id"] = csv_df["team_id"].map(name_to_team)

    p("\n" + "=" * 100)
    p("RESULTADOS WAPE/BIAS por variante y semana")
    p("=" * 100)

    # Baseline (sin corregir)
    p("\n[BASELINE - sin corregir]")
    for wk in CUTOFF_TO_LAST_MONTH:
        sub = csv_df[csv_df["target_week_start"] == wk].copy()
        sub["forecast_corrected"] = sub["forecast_qty"]
        p(_summary(sub, wk))
    sub_all = csv_df.copy()
    sub_all["forecast_corrected"] = sub_all["forecast_qty"]
    real = sub_all["real_qty"].sum()
    ae = (sub_all["forecast_corrected"] - sub_all["real_qty"]).abs().sum()
    err = (sub_all["real_qty"] - sub_all["forecast_corrected"]).sum()
    p(f"  TOTAL 3 sem                      real={real:>8,.0f}  WAPE={ae/real*100:>5.1f}%  BIAS={err/real*100:>+6.1f}%")

    for v in variants:
        p(f"\n[{v}]")
        for wk in CUTOFF_TO_LAST_MONTH:
            sub = csv_df[csv_df["target_week_start"] == wk].copy()
            sub["factor"] = sub["team_crm_id"].apply(
                lambda tid: factor_table.get((wk, tid, v), 1.0)
            )
            sub["forecast_corrected"] = sub["forecast_qty"] * sub["factor"]
            p(_summary(sub, wk))
        # Total
        sub_all = csv_df.copy()
        sub_all["factor"] = sub_all.apply(
            lambda r: factor_table.get((r["target_week_start"], r["team_crm_id"], v), 1.0), axis=1
        )
        sub_all["forecast_corrected"] = sub_all["forecast_qty"] * sub_all["factor"]
        real = sub_all["real_qty"].sum()
        ae = (sub_all["forecast_corrected"] - sub_all["real_qty"]).abs().sum()
        err = (sub_all["real_qty"] - sub_all["forecast_corrected"]).sum()
        p(f"  TOTAL 3 sem                      real={real:>8,.0f}  WAPE={ae/real*100:>5.1f}%  BIAS={err/real*100:>+6.1f}%")

    # === 7. Detalle por team (Mehuin Express, Coñaripe) usando variante B ===
    p("\n" + "=" * 100)
    p("DETALLE por team (variante B_avg3) - semana Mar-16")
    p("=" * 100)
    wk = "2026-03-16"
    rows_d = []
    for team_name in sorted(csv_teams):
        team_id = name_to_team.get(team_name)
        if not team_id: continue
        sub = csv_df[(csv_df["target_week_start"] == wk) & (csv_df["team_id"] == team_name)].copy()
        f = factor_table.get((wk, team_id, "B_avg3"), 1.0)
        fc_before = sub["forecast_qty"].sum()
        fc_after = fc_before * f
        real = sub["real_qty"].sum()
        ae_b = (sub["forecast_qty"] - sub["real_qty"]).abs().sum()
        ae_a = (sub["forecast_qty"]*f - sub["real_qty"]).abs().sum()
        rows_d.append({
            "team": team_name, "factor": round(f, 3),
            "real": real, "fc_before": fc_before, "fc_after": round(fc_after, 0),
            "WAPE_before": round(ae_b/real*100,1) if real>0 else float('nan'),
            "WAPE_after": round(ae_a/real*100,1) if real>0 else float('nan'),
            "BIAS_before": round((real-fc_before)/real*100,1) if real>0 else float('nan'),
            "BIAS_after": round((real-fc_after)/real*100,1) if real>0 else float('nan'),
        })
    p(pd.DataFrame(rows_d).to_string(index=False))

    OUT_PATH.write_text(buf.getvalue(), encoding="utf-8")
    print(f"Output saved to: {OUT_PATH}")


if __name__ == "__main__":
    main()
