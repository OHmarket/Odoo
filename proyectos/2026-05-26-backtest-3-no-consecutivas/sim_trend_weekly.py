"""
Simulacion 3: trend factor desde WEEKLY YoY por team.

Insight: weekly YoY (units_w / units_(w-52) - 1) es deseasonalizado por construccion
(misma calendar week, ano contra ano). No requiere calcular SI factors explicitos.
Es a granularidad semanal, no mensual -> capta el step-down reciente.

Variantes:
  J_w4_sym   - ventana 4 sem, simetrico clamp[0.70, 1.30]
  K_w4_asym  - ventana 4 sem, asimetrico clamp[0.70, 1.00]
  L_w8_sym   - ventana 8 sem, simetrico
  M_w8_asym  - ventana 8 sem, asimetrico
"""
from __future__ import annotations
import sys
import io
import unicodedata
from pathlib import Path
from datetime import date, timedelta
import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

CSV_PATH = Path(r"c:\Users\sanhu\Odoo\OH Forecast Backtest (x_forecast_backtest) (1).csv")
OUT_PATH = Path(__file__).parent / "sim_trend_weekly_output.txt"

NOISE_CATEG_KEYWORDS = ["cerveza", "cigarr", "tabaco", "snack", "impulso"]
NOISE_TEAM_KEYWORDS = ["san jos"]

# Para cada target_week, el cutoff (semana antes) y desde donde mirar atras
CUTOFFS = {
    "2026-02-16": date(2026, 2, 9),   # cutoff = lunes previo (week 7 = Feb 9)
    "2026-03-16": date(2026, 3, 9),   # week 11 = Mar 9
    "2026-04-06": date(2026, 3, 30),  # week 14 = Mar 30
}

CLAMP_LOW = 0.70
CLAMP_HIGH_SYM = 1.30
CLAMP_HIGH_ASYM = 1.00

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


def _week_monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def main():
    buf = io.StringIO()
    def p(s=""): buf.write(s + "\n")

    odoo = OdooReader()
    p(f"Conectado: {odoo}\n")

    csv_df = _load_csv()
    csv_teams = sorted(csv_df["team_id"].unique())

    # === 1. Mapping CSV team -> crm_team_id + pos.configs ===
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

    p(f"Teams CSV mapeados: {sum(1 for v in csv_to_team.values() if v)}/{len(csv_teams)}")

    # === 2. Pull POS weekly por team ===
    # Necesito ~104 semanas hacia atras desde Apr 5 2026 para cubrir
    # YoY de las ultimas 26 semanas. ~2 anos.
    history_from = date(2024, 1, 1).isoformat()
    p(f"\n--- Pull POS weekly por team desde {history_from} ---")

    # (team_id, week_monday) -> units
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
                ['qty:sum'],
                ['create_date:week'],
                lazy=False,
            )
        except Exception as e:
            p(f"  ERROR team {csv_team}: {str(e)[:120]}")
            continue
        n_rows = 0
        for g in grp:
            wkey = g.get('create_date:week')
            qty = float(g.get('qty', 0.0) or 0.0)
            if not wkey or qty <= 0: continue
            # 'W22 2024' -> parse iso week + year, derive monday
            import re
            m = re.search(r'W?\s*(\d+)\s+(\d{4})', str(wkey))
            if not m: continue
            iso_w = int(m.group(1))
            iso_y = int(m.group(2))
            try:
                # date.fromisocalendar(year, week, day) -> Monday=1
                wk_monday = date.fromisocalendar(iso_y, iso_w, 1)
            except Exception:
                continue
            weekly_data[(tid, wk_monday)] = weekly_data.get((tid, wk_monday), 0.0) + qty
            n_rows += 1
        p(f"  {csv_team:30s} (tid={tid}) -> {n_rows} weeks")

    p(f"\nTotal puntos (team, week): {len(weekly_data):,}")

    # === 3. Weekly YoY ===
    # Para cada (team, week_t): yoy = units_t / units_(t - 52 weeks) - 1
    yoy_data = {}
    for (tid, wk), units in weekly_data.items():
        prior = weekly_data.get((tid, wk - timedelta(weeks=52)))
        if prior and prior > 0:
            yoy_data[(tid, wk)] = units / prior - 1.0

    p(f"YoY puntos calculados: {len(yoy_data):,}")

    # === 4. Inspeccion: weekly YoY ultimas 12 semanas por team ===
    p("\n" + "=" * 100)
    p("Weekly YoY ultimas 12 semanas por team (Mar-Apr 2026)")
    p("=" * 100)
    weeks_to_show = [date(2026,1,12), date(2026,1,19), date(2026,1,26),
                      date(2026,2,2), date(2026,2,9), date(2026,2,16),
                      date(2026,2,23), date(2026,3,2), date(2026,3,9),
                      date(2026,3,16), date(2026,3,23), date(2026,3,30)]
    rows = []
    for csv_team, tid in csv_to_team.items():
        if not tid: continue
        row = {"team": csv_team}
        for w in weeks_to_show:
            v = yoy_data.get((tid, w))
            row[w.strftime("%m-%d")] = round(v*100, 1) if v is not None else None
        rows.append(row)
    p(pd.DataFrame(rows).to_string(index=False))

    # === 5. Trend factor por cutoff y variante ===
    factor_table = {}  # (target_week, team_id, variant) -> factor

    def _avg_yoy_last_n(tid, cutoff_week, n):
        """Promedio de yoy_w para w in last n weeks <= cutoff_week."""
        vals = []
        cur = cutoff_week
        while len(vals) < n + 10:  # ventana de busqueda
            if (tid, cur) in yoy_data:
                vals.append(yoy_data[(tid, cur)])
                if len(vals) >= n: break
            cur = cur - timedelta(weeks=1)
            if cur < date(2025, 1, 1): break
        return vals[:n]

    for target_week, cutoff_week in CUTOFFS.items():
        for csv_team, tid in csv_to_team.items():
            if not tid: continue
            for win, label_sym, label_asym in [(4, "J_w4_sym", "K_w4_asym"), (8, "L_w8_sym", "M_w8_asym")]:
                vals = _avg_yoy_last_n(tid, cutoff_week, win)
                if not vals:
                    avg = 0.0
                else:
                    avg = sum(vals) / len(vals)
                f_sym = max(CLAMP_LOW, min(CLAMP_HIGH_SYM, 1.0 + avg))
                f_asym = max(CLAMP_LOW, min(CLAMP_HIGH_ASYM, 1.0 + avg))
                factor_table[(target_week, tid, label_sym)] = f_sym
                factor_table[(target_week, tid, label_asym)] = f_asym

    # === 6. Mostrar factores ===
    p("\n" + "=" * 100)
    p("Factores por team y cutoff - variante L_w8_sym (ventana 8 sem, simetrico)")
    p("=" * 100)
    rows = []
    for csv_team, tid in csv_to_team.items():
        if not tid: continue
        row = {"team": csv_team}
        for tw in CUTOFFS:
            row[tw] = round(factor_table.get((tw, tid, "L_w8_sym"), 1.0), 3)
        rows.append(row)
    p(pd.DataFrame(rows).to_string(index=False))

    p("\n--- Variante M_w8_asym (mismo pero cap 1.0) ---")
    rows = []
    for csv_team, tid in csv_to_team.items():
        if not tid: continue
        row = {"team": csv_team}
        for tw in CUTOFFS:
            row[tw] = round(factor_table.get((tw, tid, "M_w8_asym"), 1.0), 3)
        rows.append(row)
    p(pd.DataFrame(rows).to_string(index=False))

    # === 7. Aplicar y medir ===
    csv_df["team_crm_id"] = csv_df["team_id"].map(csv_to_team)

    def _eval(variant):
        rows = {}
        ae_t = 0; err_t = 0; real_t = 0
        for wk in CUTOFFS:
            sub = csv_df[csv_df["target_week_start"] == wk].copy()
            if variant == "baseline":
                sub["factor"] = 1.0
            else:
                sub["factor"] = sub["team_crm_id"].apply(
                    lambda tid: factor_table.get((wk, tid, variant), 1.0))
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

    variants = ["baseline", "J_w4_sym", "K_w4_asym", "L_w8_sym", "M_w8_asym"]
    p("\n" + "=" * 100)
    p("RESULTADOS WAPE / BIAS por variante y semana")
    p("=" * 100)
    p(f"\n  {'variante':18s} | {'Feb-16 WAPE/BIAS':>20s} | {'Mar-16 WAPE/BIAS':>20s} | {'Apr-06 WAPE/BIAS':>20s} | {'Total 3w':>17s}")
    p(f"  {'-'*18} | {'-'*20} | {'-'*20} | {'-'*20} | {'-'*17}")

    for v in variants:
        per_wk, wape_t, bias_t = _eval(v)
        def fmt(wk):
            return f"{per_wk[wk]['WAPE']:5.1f}% / {per_wk[wk]['BIAS']:+5.1f}%"
        p(f"  {v:18s} | {fmt('2026-02-16'):>20s} | {fmt('2026-03-16'):>20s} | {fmt('2026-04-06'):>20s} | {wape_t:5.1f}% / {bias_t:+5.1f}%")

    # === 8. Detalle por team en Mar-16 con L_w8_sym ===
    p("\n" + "=" * 100)
    p("DETALLE por team en Mar-16 (variante L_w8_sym)")
    p("=" * 100)
    rows_d = []
    wk = "2026-03-16"
    for csv_team, tid in csv_to_team.items():
        if not tid: continue
        sub = csv_df[(csv_df["target_week_start"] == wk) &
                     (csv_df["team_id"] == csv_team)].copy()
        f = factor_table.get((wk, tid, "L_w8_sym"), 1.0)
        fc_b = sub["forecast_qty"].sum()
        fc_a = fc_b * f
        real = sub["real_qty"].sum()
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

    # === 9. Mismo detalle pero asimetrico ===
    p("\n" + "=" * 100)
    p("DETALLE por team en Mar-16 (variante M_w8_asym - cap 1.0)")
    p("=" * 100)
    rows_d = []
    for csv_team, tid in csv_to_team.items():
        if not tid: continue
        sub = csv_df[(csv_df["target_week_start"] == wk) &
                     (csv_df["team_id"] == csv_team)].copy()
        f = factor_table.get((wk, tid, "M_w8_asym"), 1.0)
        fc_b = sub["forecast_qty"].sum()
        fc_a = fc_b * f
        real = sub["real_qty"].sum()
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
