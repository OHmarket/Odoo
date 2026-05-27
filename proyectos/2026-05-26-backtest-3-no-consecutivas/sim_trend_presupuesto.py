"""
Simulacion 4: trend factor replicando metodo del OH Presupuesto Ventas.

Formula canonica (de 05_finanzas/OH Presupuesto ventas.py:575):
  fac = ALPHA_BLEND * long_fac + (1 - ALPHA_BLEND) * short_fac
      = 0.25 * long + 0.75 * short

Donde:
  long_fac  = sum(units_actual_52w)  / sum(units_LY_52w)
  short_fac = sum(units_actual_7w)   / sum(units_LY_7w)

Clamp [0.60, 1.80] como en Presupuesto (mas amplio que mi 0.70-1.30).
"""
from __future__ import annotations
import sys
import io
import re
import unicodedata
from pathlib import Path
from datetime import date, timedelta
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

CSV_PATH = Path(r"c:\Users\sanhu\Odoo\OH Forecast Backtest (x_forecast_backtest) (1).csv")
OUT_PATH = Path(__file__).parent / "sim_trend_presupuesto_output.txt"

NOISE_CATEG_KEYWORDS = ["cerveza", "cigarr", "tabaco", "snack", "impulso"]
NOISE_TEAM_KEYWORDS = ["san jos"]

# Cutoff = lunes de la semana ANTES del target. La data del cutoff y antes
# es la que el motor "ve" al pronosticar.
CUTOFFS = {
    "2026-02-16": date(2026, 2, 9),
    "2026-03-16": date(2026, 3, 9),
    "2026-04-06": date(2026, 3, 30),
}

ALPHA_BLEND = 0.25
SHORT_WEEKS = 7         # ~45 dias / 7 dias = 6.4, redondeado a 7
LONG_WEEKS = 52
CLAMP_LOW = 0.60
CLAMP_HIGH = 1.80
MIN_BASE_SHORT = 100    # units min en ventana short LY para activar short_fac

pd.set_option("display.float_format", lambda x: f"{x:,.3f}")
pd.set_option("display.max_columns", 80)
pd.set_option("display.width", 280)


def _norm(s):
    return unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower().strip()


def _load_csv():
    df = pd.read_csv(CSV_PATH, low_memory=False, encoding="utf-8", encoding_errors="replace")
    for c in ["forecast_qty", "real_qty", "abs_error_qty", "error_qty"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    df["categ_lower"] = df["categ_id"].fillna("").astype(str).str.lower()
    df["team_lower"] = df["team_id"].fillna("").astype(str).str.lower()
    noise_c = df["categ_lower"].apply(lambda s: any(k in s for k in NOISE_CATEG_KEYWORDS))
    noise_t = df["team_lower"].apply(lambda s: any(k in s for k in NOISE_TEAM_KEYWORDS))
    return df[~(noise_c | noise_t)].copy()


def main():
    buf = io.StringIO()
    def p(s=""): buf.write(s + "\n")

    odoo = OdooReader()
    p(f"Conectado: {odoo}\n")
    p(f"Parametros (replica Presupuesto):")
    p(f"  ALPHA_BLEND={ALPHA_BLEND}  SHORT_WEEKS={SHORT_WEEKS}  LONG_WEEKS={LONG_WEEKS}")
    p(f"  CLAMP=[{CLAMP_LOW}, {CLAMP_HIGH}]  MIN_BASE_SHORT={MIN_BASE_SHORT}\n")

    csv_df = _load_csv()
    csv_teams = sorted(csv_df["team_id"].unique())

    # === 1. Mapping CSV team -> crm_team_id ===
    pos_cfgs = odoo.search_read('pos.config', domain=[], fields=['id', 'name', 'crm_team_id'])
    team_to_configs = {}
    team_to_local_norm = {}
    for c in pos_cfgs:
        nm = c.get('name') or ''
        tm = c.get('crm_team_id')
        if not tm: continue
        tid = tm[0]
        team_to_configs.setdefault(tid, []).append(c['id'])
        local = nm.split(' Caja')[0].strip() if ' Caja' in nm else nm.strip()
        team_to_local_norm[tid] = _norm(local)

    csv_to_team = {}
    for csv_label in csv_teams:
        csv_norm = _norm(csv_label.replace("Ventas ", ""))
        for tid, local_norm in team_to_local_norm.items():
            if csv_norm == local_norm:
                csv_to_team[csv_label] = tid
                break

    # === 2. Pull POS weekly por team, 2024-2026 (necesitamos 104+ semanas) ===
    history_from = date(2024, 1, 1).isoformat()
    p(f"--- Pull POS weekly por team desde {history_from} ---")
    weekly_data = {}
    for csv_team, tid in csv_to_team.items():
        if not tid: continue
        configs = team_to_configs.get(tid, [])
        if not configs: continue
        try:
            grp = odoo.execute(
                'pos.order.line', 'read_group',
                [('order_id.state', 'in', ['paid', 'done', 'invoiced']),
                 ('order_id.session_id.config_id', 'in', configs),
                 ('create_date', '>=', history_from)],
                ['qty:sum'], ['create_date:week'], lazy=False,
            )
        except Exception as e:
            p(f"  ERROR team {csv_team}: {str(e)[:120]}")
            continue
        for g in grp:
            wkey = g.get('create_date:week')
            qty = float(g.get('qty', 0.0) or 0.0)
            if not wkey or qty <= 0: continue
            m = re.search(r'W?\s*(\d+)\s+(\d{4})', str(wkey))
            if not m: continue
            iso_w = int(m.group(1)); iso_y = int(m.group(2))
            try:
                wk_monday = date.fromisocalendar(iso_y, iso_w, 1)
            except Exception:
                continue
            weekly_data[(tid, wk_monday)] = weekly_data.get((tid, wk_monday), 0.0) + qty
    p(f"Total puntos (team, week): {len(weekly_data):,}")

    # === 3. Calcular fac por (team, cutoff) con metodo Presupuesto ===
    def _sum_window(tid, end_week, n_weeks):
        """Suma units en n_weeks terminando en end_week (inclusivo)."""
        total = 0.0
        n_with_data = 0
        for i in range(n_weeks):
            wk = end_week - timedelta(weeks=i)
            v = weekly_data.get((tid, wk))
            if v is not None:
                total += v
                n_with_data += 1
        return total, n_with_data

    def _compute_fac(tid, cutoff_week):
        """Replica formula del Presupuesto adaptada a granularidad semanal."""
        # Long: ultimas 52 sem vs mismo periodo LY (52 sem antes)
        curr_long, _ = _sum_window(tid, cutoff_week, LONG_WEEKS)
        base_long, _ = _sum_window(tid, cutoff_week - timedelta(weeks=52), LONG_WEEKS)
        long_fac = (curr_long / base_long) if base_long > 0 else 1.0

        # Short: ultimas 7 sem vs LY
        curr_short, _ = _sum_window(tid, cutoff_week, SHORT_WEEKS)
        base_short, _ = _sum_window(tid, cutoff_week - timedelta(weeks=52), SHORT_WEEKS)
        if base_short >= MIN_BASE_SHORT:
            short_fac = (curr_short / base_short) if base_short > 0 else long_fac
            fac = ALPHA_BLEND * long_fac + (1.0 - ALPHA_BLEND) * short_fac
        else:
            fac = long_fac
            short_fac = float('nan')

        fac_clamped = max(CLAMP_LOW, min(CLAMP_HIGH, fac))
        return {
            "long_fac": long_fac,
            "short_fac": short_fac,
            "fac_raw": fac,
            "fac": fac_clamped,
            "curr_long": curr_long, "base_long": base_long,
            "curr_short": curr_short, "base_short": base_short,
        }

    p("\n" + "=" * 100)
    p("Factores por team y cutoff (metodo Presupuesto)")
    p("=" * 100)

    factor_table = {}
    for target_week, cutoff_week in CUTOFFS.items():
        p(f"\n--- Target {target_week} (cutoff_week={cutoff_week}) ---")
        rows = []
        for csv_team, tid in csv_to_team.items():
            if not tid: continue
            r = _compute_fac(tid, cutoff_week)
            factor_table[(target_week, tid)] = r["fac"]
            rows.append({
                "team": csv_team,
                "long_fac": round(r["long_fac"], 3),
                "short_fac": round(r["short_fac"], 3) if not pd.isna(r["short_fac"]) else None,
                "fac_raw": round(r["fac_raw"], 3),
                "fac_clamped": round(r["fac"], 3),
                "curr_short": round(r["curr_short"], 0),
                "base_short": round(r["base_short"], 0),
            })
        p(pd.DataFrame(rows).to_string(index=False))

    # === 4. Aplicar y medir ===
    csv_df["team_crm_id"] = csv_df["team_id"].map(csv_to_team)

    def _eval(use_factor=True):
        rows = {}
        ae_t = 0; err_t = 0; real_t = 0
        for wk in CUTOFFS:
            sub = csv_df[csv_df["target_week_start"] == wk].copy()
            if use_factor:
                sub["factor"] = sub["team_crm_id"].apply(
                    lambda tid: factor_table.get((wk, tid), 1.0))
            else:
                sub["factor"] = 1.0
            sub["fc_corr"] = sub["forecast_qty"] * sub["factor"]
            real = sub["real_qty"].sum()
            ae = (sub["fc_corr"] - sub["real_qty"]).abs().sum()
            err = (sub["real_qty"] - sub["fc_corr"]).sum()
            rows[wk] = {
                "real": real,
                "fc": sub["fc_corr"].sum(),
                "WAPE": ae/real*100 if real > 0 else float("nan"),
                "BIAS": err/real*100 if real > 0 else float("nan"),
            }
            ae_t += ae; err_t += err; real_t += real
        return rows, ae_t/real_t*100, err_t/real_t*100

    p("\n" + "=" * 100)
    p("RESULTADOS WAPE / BIAS")
    p("=" * 100)
    p(f"\n  {'variante':30s} | {'Feb-16 WAPE/BIAS':>20s} | {'Mar-16 WAPE/BIAS':>20s} | {'Apr-06 WAPE/BIAS':>20s} | {'Total 3w':>17s}")
    p(f"  {'-'*30} | {'-'*20} | {'-'*20} | {'-'*20} | {'-'*17}")
    for label, use_f in [("baseline (sin corregir)", False),
                          ("N_presupuesto_canon", True)]:
        per_wk, wape_t, bias_t = _eval(use_factor=use_f)
        def fmt(w):
            return f"{per_wk[w]['WAPE']:5.1f}% / {per_wk[w]['BIAS']:+5.1f}%"
        p(f"  {label:30s} | {fmt('2026-02-16'):>20s} | {fmt('2026-03-16'):>20s} | {fmt('2026-04-06'):>20s} | {wape_t:5.1f}% / {bias_t:+5.1f}%")

    # === 5. Detalle por team en cada semana ===
    for wk in CUTOFFS:
        p(f"\n--- Detalle por team {wk} (variante N_presupuesto_canon) ---")
        rows_d = []
        for csv_team, tid in csv_to_team.items():
            if not tid: continue
            sub = csv_df[(csv_df["target_week_start"] == wk) &
                         (csv_df["team_id"] == csv_team)].copy()
            f = factor_table.get((wk, tid), 1.0)
            real = sub["real_qty"].sum()
            fc_b = sub["forecast_qty"].sum()
            fc_a = fc_b * f
            ae_b = (sub["forecast_qty"] - sub["real_qty"]).abs().sum()
            ae_a = (sub["forecast_qty"]*f - sub["real_qty"]).abs().sum()
            rows_d.append({
                "team": csv_team, "factor": round(f, 3),
                "real": real, "fc_b": fc_b, "fc_a": round(fc_a, 0),
                "WAPE_b": round(ae_b/real*100,1) if real>0 else float('nan'),
                "WAPE_a": round(ae_a/real*100,1) if real>0 else float('nan'),
                "BIAS_b": round((real-fc_b)/real*100,1) if real>0 else float('nan'),
                "BIAS_a": round((real-fc_a)/real*100,1) if real>0 else float('nan'),
            })
        p(pd.DataFrame(rows_d).to_string(index=False))

    OUT_PATH.write_text(buf.getvalue(), encoding="utf-8")
    print(f"Output saved to: {OUT_PATH}")


if __name__ == "__main__":
    main()
