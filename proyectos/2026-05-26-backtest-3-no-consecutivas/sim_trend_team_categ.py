"""
Simulacion 2: trend factor por (team x categ_L1) en lugar de solo team.

Compara variantes:
  B_avg3_team          - solo team, simetrico (baseline anterior)
  G_avg3_team_categL1  - team x categ_L1, simetrico clamp[0.70, 1.30]
  H_avg3_team_categL1_asym - team x categ_L1, asimetrico clamp[0.70, 1.00]
                            (solo recorta, no amplifica)
  I_avg3_team_asym     - solo team, asimetrico (control)

Calcula trend_factor desde POS aggregado por (team, L1, mes), comparando
mismo mes ano-a-ano (YoY), promedio de los ultimos 3 meses cerrados al cutoff.
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
OUT_PATH = Path(__file__).parent / "sim_trend_team_categ_output.txt"

NOISE_CATEG_KEYWORDS = ["cerveza", "cigarr", "tabaco", "snack", "impulso"]
NOISE_TEAM_KEYWORDS = ["san jos"]

CUTOFF_TO_LAST_MONTH = {
    "2026-02-16": date(2026, 1, 1),
    "2026-03-16": date(2026, 2, 1),
    "2026-04-06": date(2026, 3, 1),
}

CLAMP_LOW = 0.70
CLAMP_HIGH = 1.30
CLAMP_HIGH_ASYM = 1.00  # asimetrico: solo recorta

pd.set_option("display.float_format", lambda x: f"{x:,.3f}")
pd.set_option("display.max_columns", 60)
pd.set_option("display.width", 240)


def _load_csv():
    df = pd.read_csv(CSV_PATH, low_memory=False, encoding="utf-8", encoding_errors="replace")
    for c in ["forecast_qty", "real_qty", "abs_error_qty", "error_qty"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    df["categ_lower"] = df["categ_id"].fillna("").astype(str).str.lower()
    df["team_lower"] = df["team_id"].fillna("").astype(str).str.lower()
    noise_c = df["categ_lower"].apply(lambda s: any(k in s for k in NOISE_CATEG_KEYWORDS))
    noise_t = df["team_lower"].apply(lambda s: any(k in s for k in NOISE_TEAM_KEYWORDS))
    out = df[~(noise_c | noise_t)].copy()
    # Parse L1 del categ_id (primer segmento antes de "/")
    out["categ_L1"] = out["categ_id"].fillna("").astype(str).apply(
        lambda s: s.split("/")[0].strip() if s else ""
    )
    return out


def _norm(s):
    """Normaliza string a ASCII sin acentos para matching robusto."""
    import unicodedata
    return unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower().strip()


def main():
    buf = io.StringIO()
    def p(s=""): buf.write(s + "\n")

    odoo = OdooReader()
    p(f"Conectado: {odoo}\n")

    csv_df = _load_csv()
    p(f"CSV filas (limpio): {len(csv_df):,}")
    csv_teams = sorted(csv_df["team_id"].unique())
    csv_L1s = sorted(csv_df["categ_L1"].unique())
    p(f"Teams en CSV: {len(csv_teams)} | L1s en CSV: {len(csv_L1s)}")
    p(f"L1s: {csv_L1s}")

    # === 1. Mapeo CSV team label -> crm_team_id (matching normalizado) ===
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

    p("\n--- Team mapping ---")
    for t in csv_teams:
        tid = csv_to_team.get(t)
        configs = team_to_configs.get(tid, [])
        p(f"  {t:30s} -> crm_team={tid}  configs={configs}")

    # === 2. L1 categs: resolver IDs por complete_name ===
    # L1 = categoria cuyo complete_name (sin separador "/") = csv_L1
    all_cats = odoo.search_read('product.category', domain=[],
                                 fields=['id', 'name', 'parent_id', 'complete_name'])
    # Map por nombre normalizado (sin tildes) y por complete_name
    cn_to_id = {}
    name_l1_to_id = {}
    for c in all_cats:
        cn = c.get('complete_name', '') or ''
        cn_to_id[_norm(cn)] = c['id']
        # Si complete_name no tiene "/", es un L1 raiz
        if '/' not in cn:
            name_l1_to_id[_norm(cn)] = c['id']

    csv_L1_to_id = {}
    for l1_name in csv_L1s:
        nl = _norm(l1_name)
        # Probar exact match en L1 sin slash
        if nl in name_l1_to_id:
            csv_L1_to_id[l1_name] = name_l1_to_id[nl]
        elif nl in cn_to_id:
            csv_L1_to_id[l1_name] = cn_to_id[nl]
        else:
            # buscar como prefijo de complete_name
            for cn_norm, cid in cn_to_id.items():
                if cn_norm == nl or cn_norm.startswith(nl + ' /') or cn_norm.startswith(nl + '/'):
                    csv_L1_to_id[l1_name] = cid
                    break

    p(f"\n--- L1 categs CSV resueltos: {len(csv_L1_to_id)}/{len(csv_L1s)} ---")
    for l1, lid in csv_L1_to_id.items():
        p(f"  '{l1}' -> id={lid}")

    # === 3. Pull POS aggregado por (team_config, L1, mes) ===
    # Para cada (L1_id, team_id): read_group filtrado, groupby month
    p("\n--- Pull POS aggregado por (team, L1, mes) ---")
    today = date.today()
    history_from = date(today.year - 2, today.month, 1).isoformat()
    p(f"History from: {history_from}")

    # (team_id, L1_name, month_str) -> units
    pos_data = {}

    for l1_name, l1_id in csv_L1_to_id.items():
        for csv_team, team_id in csv_to_team.items():
            if not team_id: continue
            configs = team_to_configs.get(team_id, [])
            if not configs: continue
            try:
                grp = odoo.execute(
                    'pos.order.line', 'read_group',
                    [('product_id.product_tmpl_id.categ_id', 'child_of', l1_id),
                     ('order_id.state', 'in', ['paid', 'done', 'invoiced']),
                     ('order_id.session_id.config_id', 'in', configs),
                     ('create_date', '>=', history_from)],
                    ['qty:sum'],
                    ['create_date:month'],
                    lazy=False,
                )
            except Exception as e:
                p(f"  ERROR ({l1_name[:20]}, team={team_id}): {str(e)[:120]}")
                continue
            for g in grp:
                m = g.get('create_date:month')
                qty = float(g.get('qty', 0.0) or 0.0)
                if not m or qty <= 0: continue
                # parsear "enero 2024" -> date(2024,1,1)
                months_es = {'enero':1,'febrero':2,'marzo':3,'abril':4,'mayo':5,'junio':6,
                              'julio':7,'agosto':8,'septiembre':9,'octubre':10,'noviembre':11,'diciembre':12}
                parts = str(m).lower().split()
                if len(parts) != 2: continue
                mo = months_es.get(parts[0])
                try:
                    yr = int(parts[1])
                except: continue
                if mo:
                    mkey = date(yr, mo, 1)
                    pos_data[(team_id, l1_name, mkey)] = qty
        # progreso
        p(f"  done L1={l1_name[:30]:30s}")

    # === 4. Calcular YoY por (team, L1, month) ===
    yoy_data = {}  # (team_id, L1, month) -> yoy ratio (e.g. -0.10 = -10%)
    for (tid, l1, mkey), units in pos_data.items():
        prev = pos_data.get((tid, l1, date(mkey.year - 1, mkey.month, 1)))
        if prev and prev > 0:
            yoy_data[(tid, l1, mkey)] = (units / prev) - 1.0

    p(f"\nYoY puntos calculados: {len(yoy_data):,}")

    # === 5. Trend factor por (team, L1, cutoff) ===
    factor_table = {}  # (target_week, team_id, l1, variant) -> factor

    def _prev_month(d):
        return date(d.year - 1, 12, 1) if d.month == 1 else date(d.year, d.month - 1, 1)

    def _last_n_yoy(tid, l1, last_month, n):
        """Ultimos n meses cerrados (<=last_month) con yoy disponible."""
        vals = []
        cur = last_month
        for _ in range(n + 6):
            if (tid, l1, cur) in yoy_data:
                vals.append(yoy_data[(tid, l1, cur)])
            cur = _prev_month(cur)
            if len(vals) >= n: break
        return vals

    for target_week, last_month in CUTOFF_TO_LAST_MONTH.items():
        for csv_team, tid in csv_to_team.items():
            if not tid: continue
            for l1 in csv_L1_to_id.keys():
                vals = _last_n_yoy(tid, l1, last_month, 3)
                if not vals:
                    avg = 0.0
                else:
                    avg = sum(vals) / len(vals)
                # variantes
                # G simetrico
                f_sym = max(CLAMP_LOW, min(CLAMP_HIGH, 1.0 + avg))
                # H asimetrico (cap a 1.0)
                f_asym = max(CLAMP_LOW, min(CLAMP_HIGH_ASYM, 1.0 + avg))
                factor_table[(target_week, tid, l1, "G_sym")] = f_sym
                factor_table[(target_week, tid, l1, "H_asym")] = f_asym

        # Tambien team-only para comparar (re-calcular sin L1)
        for csv_team, tid in csv_to_team.items():
            if not tid: continue
            # Suma units across L1s para este team
            t_yoy = {}
            for (t2, l1, m), units in pos_data.items():
                if t2 == tid:
                    t_yoy.setdefault(m, [0, 0])
                    t_yoy[m][0] += units
            # Prior year
            for (t2, l1, m), units in pos_data.items():
                if t2 == tid:
                    prev_m = date(m.year - 1, m.month, 1)
                    if prev_m in t_yoy:
                        # this row is prior year, add to slot [1]
                        pass
            # Mejor: re-calcular limpio
            team_units = {}
            for (t2, l1, m), units in pos_data.items():
                if t2 == tid:
                    team_units[m] = team_units.get(m, 0) + units
            team_yoy = {}
            for m, u in team_units.items():
                prev = team_units.get(date(m.year - 1, m.month, 1))
                if prev and prev > 0:
                    team_yoy[m] = u/prev - 1.0
            # Ultimos 3 meses
            vals = []
            cur = last_month
            for _ in range(9):
                if cur in team_yoy:
                    vals.append(team_yoy[cur])
                cur = _prev_month(cur)
                if len(vals) >= 3: break
            avg = sum(vals)/len(vals) if vals else 0.0
            f_team_sym = max(CLAMP_LOW, min(CLAMP_HIGH, 1.0 + avg))
            f_team_asym = max(CLAMP_LOW, min(CLAMP_HIGH_ASYM, 1.0 + avg))
            factor_table[(target_week, tid, "_ALL_", "B_team_sym")] = f_team_sym
            factor_table[(target_week, tid, "_ALL_", "I_team_asym")] = f_team_asym

    # === 6. Mostrar factores por (team, L1) para Mar-16 (variante G_sym) ===
    p("\n" + "=" * 100)
    p("Tabla factores (team x L1) - variante G_sym - cutoff Mar-16")
    p("=" * 100)
    rows = []
    wk = "2026-03-16"
    for csv_team, tid in csv_to_team.items():
        if not tid: continue
        row = {"team": csv_team}
        for l1 in csv_L1_to_id.keys():
            row[l1[:25]] = factor_table.get((wk, tid, l1, "G_sym"), 1.0)
        rows.append(row)
    p(pd.DataFrame(rows).round(2).to_string(index=False))

    # === 7. Aplicar y medir ===
    csv_df["team_crm_id"] = csv_df["team_id"].map(csv_to_team)

    def _eval(variant, asym=False):
        """Aplica variant y devuelve dict con WAPE/BIAS por semana."""
        out = {}
        for wk in CUTOFF_TO_LAST_MONTH:
            sub = csv_df[csv_df["target_week_start"] == wk].copy()
            if variant == "baseline":
                sub["factor"] = 1.0
            elif variant in ("B_team_sym", "I_team_asym"):
                sub["factor"] = sub["team_crm_id"].apply(
                    lambda tid: factor_table.get((wk, tid, "_ALL_", variant), 1.0))
            else:
                sub["factor"] = sub.apply(
                    lambda r: factor_table.get((wk, r["team_crm_id"], r["categ_L1"], variant), 1.0),
                    axis=1,
                )
            sub["fc_corr"] = sub["forecast_qty"] * sub["factor"]
            real = sub["real_qty"].sum()
            fc = sub["fc_corr"].sum()
            ae = (sub["fc_corr"] - sub["real_qty"]).abs().sum()
            err = (sub["real_qty"] - sub["fc_corr"]).sum()
            out[wk] = {
                "real": real, "fc": fc,
                "WAPE": ae/real*100 if real > 0 else float("nan"),
                "BIAS": err/real*100 if real > 0 else float("nan"),
            }
        return out

    variants = ["baseline", "B_team_sym", "I_team_asym", "G_sym", "H_asym"]
    p("\n" + "=" * 100)
    p("RESULTADOS WAPE / BIAS por variante y semana")
    p("=" * 100)
    p(f"\n  {'variante':22s} | {'Feb-16 WAPE/BIAS':>20s} | {'Mar-16 WAPE/BIAS':>20s} | {'Apr-06 WAPE/BIAS':>20s} | {'Total 3w':>16s}")
    p(f"  {'-'*22} | {'-'*20} | {'-'*20} | {'-'*20} | {'-'*16}")

    for v in variants:
        r = _eval(v)
        # Total
        real_t = sum(r[w]["real"] for w in r)
        fc_t = sum(r[w]["fc"] for w in r)
        ae_t = 0; err_t = 0
        for wk in CUTOFF_TO_LAST_MONTH:
            sub = csv_df[csv_df["target_week_start"] == wk].copy()
            if v == "baseline":
                sub["factor"] = 1.0
            elif v in ("B_team_sym", "I_team_asym"):
                sub["factor"] = sub["team_crm_id"].apply(
                    lambda tid: factor_table.get((wk, tid, "_ALL_", v), 1.0))
            else:
                sub["factor"] = sub.apply(
                    lambda x: factor_table.get((wk, x["team_crm_id"], x["categ_L1"], v), 1.0),
                    axis=1,
                )
            sub["fc_corr"] = sub["forecast_qty"] * sub["factor"]
            ae_t += (sub["fc_corr"] - sub["real_qty"]).abs().sum()
            err_t += (sub["real_qty"] - sub["fc_corr"]).sum()
        wape_t = ae_t/real_t*100 if real_t > 0 else 0
        bias_t = err_t/real_t*100 if real_t > 0 else 0

        def fmt(wk):
            return f"{r[wk]['WAPE']:5.1f}% / {r[wk]['BIAS']:+5.1f}%"
        p(f"  {v:22s} | {fmt('2026-02-16'):>20s} | {fmt('2026-03-16'):>20s} | {fmt('2026-04-06'):>20s} | {wape_t:5.1f}% / {bias_t:+5.1f}%")

    # === 8. Detalle por L1 en Mar-16 (variante H_asym, la mas conservadora) ===
    p("\n" + "=" * 100)
    p("DETALLE por categoria_L1 en Mar-16 (variante H_asym = team x L1 asimetrico)")
    p("=" * 100)
    wk = "2026-03-16"
    sub_all = csv_df[csv_df["target_week_start"] == wk].copy()
    sub_all["factor"] = sub_all.apply(
        lambda r: factor_table.get((wk, r["team_crm_id"], r["categ_L1"], "H_asym"), 1.0), axis=1,
    )
    sub_all["fc_corr"] = sub_all["forecast_qty"] * sub_all["factor"]
    by_l1 = sub_all.groupby("categ_L1").agg(
        n=("forecast_qty", "size"),
        real=("real_qty", "sum"),
        fc_before=("forecast_qty", "sum"),
        fc_after=("fc_corr", "sum"),
        avg_factor=("factor", "mean"),
    ).reset_index()
    by_l1["WAPE_b"] = (
        sub_all.groupby("categ_L1").apply(lambda d: (d["forecast_qty"]-d["real_qty"]).abs().sum())
        / by_l1.set_index("categ_L1")["real"]
    ).values * 100
    by_l1["WAPE_a"] = (
        sub_all.groupby("categ_L1").apply(lambda d: (d["fc_corr"]-d["real_qty"]).abs().sum())
        / by_l1.set_index("categ_L1")["real"]
    ).values * 100
    by_l1["BIAS_b"] = (
        (by_l1["real"] - by_l1["fc_before"]) / by_l1["real"]
    ) * 100
    by_l1["BIAS_a"] = (
        (by_l1["real"] - by_l1["fc_after"]) / by_l1["real"]
    ) * 100
    p(by_l1.sort_values("real", ascending=False).to_string(index=False))

    OUT_PATH.write_text(buf.getvalue(), encoding="utf-8")
    print(f"Output saved to: {OUT_PATH}")


if __name__ == "__main__":
    main()
