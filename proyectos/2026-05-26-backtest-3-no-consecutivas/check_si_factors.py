"""
Dos validaciones:
A) si_n_years para SKUs problema: confirma que tienen 3+ anos
   (umbral SI_MIN_YEARS_FOR_SKU para que aplique alpha_high=0.30 en el motor).
B) Calcular SI historica nosotros mismos a partir de pos.order.line
   para 10 categorias problema. Replica _calc_si_from_weekly del motor a nivel categ_global.

Output a archivo TXT.
"""
from __future__ import annotations
import sys
import io
import re
from pathlib import Path
from datetime import date
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

CSV_PATH = Path(r"c:\Users\sanhu\Odoo\OH Forecast Backtest (x_forecast_backtest) (1).csv")
OUT_PATH = Path(__file__).parent / "check_si_factors_output.txt"
NOISE_CATEG_KEYWORDS = ["cerveza", "cigarr", "tabaco", "snack", "impulso"]
NOISE_TEAM_KEYWORDS = ["san jos"]

pd.set_option("display.float_format", lambda x: f"{x:,.3f}")
pd.set_option("display.max_columns", 60)
pd.set_option("display.width", 220)


def _load_csv():
    df = pd.read_csv(CSV_PATH, low_memory=False, encoding="latin-1")
    for c in ["forecast_qty", "real_qty", "abs_error_qty", "error_qty"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)
    df["categ_lower"] = df["categ_id"].fillna("").astype(str).str.lower()
    df["team_lower"] = df["team_id"].fillna("").astype(str).str.lower()
    noise_c = df["categ_lower"].apply(lambda s: any(k in s for k in NOISE_CATEG_KEYWORDS))
    noise_t = df["team_lower"].apply(lambda s: any(k in s for k in NOISE_TEAM_KEYWORDS))
    return df[~(noise_c | noise_t)].copy()


def _top_problem_skus(clean, n=20):
    feb = clean[clean["target_week_start"] == "2026-02-16"][["product_id", "team_id",
                                                              "forecast_qty", "real_qty"]].rename(
        columns={"forecast_qty": "fc_feb", "real_qty": "real_feb"})
    mar = clean[clean["target_week_start"] == "2026-03-16"][["product_id", "team_id",
                                                              "forecast_qty", "real_qty"]].rename(
        columns={"forecast_qty": "fc_mar", "real_qty": "real_mar"})
    p = feb.merge(mar, on=["product_id", "team_id"], how="inner")
    p = p[(p["fc_feb"] > 0) & (p["fc_mar"] > 0) & (p["real_feb"] > 0) & (p["real_mar"] > 0)]
    sku = p.groupby("product_id").agg(
        fc_feb=("fc_feb", "sum"),
        real_feb=("real_feb", "sum"),
        fc_mar=("fc_mar", "sum"),
        real_mar=("real_mar", "sum"),
    ).reset_index()
    sku = sku[(sku["fc_feb"] >= 5) & (sku["real_feb"] >= 5)]
    sku["over_qty"] = sku["fc_mar"] - sku["real_mar"]
    return sku.sort_values("over_qty", ascending=False).head(n)


def _extract_code(name):
    """Devuelve el codigo entre [] del display_name. Ej '[9640] COCTEL...' -> '9640'."""
    if not isinstance(name, str):
        return None
    m = re.match(r"\s*\[([^\]]+)\]", name)
    return m.group(1) if m else None


def main():
    buf = io.StringIO()
    def p(s=""): buf.write(s + "\n")

    odoo = OdooReader()
    p(f"Conectado: {odoo}\n")

    clean = _load_csv()
    top = _top_problem_skus(clean, n=20)
    codes = [_extract_code(n) for n in top["product_id"].tolist()]
    codes = [c for c in codes if c]
    p(f"Top SKUs problema (over-units Mar): {len(top)}")
    p(f"Codigos extraidos: {codes}")

    # === A. Resolver codes -> product.product IDs ===
    prods = odoo.search_read(
        'product.product',
        domain=[('default_code', 'in', codes)],
        fields=['id', 'default_code', 'display_name'],
    )
    code_to_id = {pr['default_code']: pr['id'] for pr in prods}
    id_to_code = {pr['id']: pr['default_code'] for pr in prods}
    id_to_name = {pr['id']: pr['display_name'] for pr in prods}
    pids = list(code_to_id.values())
    p(f"\nProduct IDs resueltos: {len(pids)} de {len(codes)} codes")

    # === B. Query x_hm_si_forecast para esos product_ids ===
    p("\n" + "=" * 100)
    p("CHECK A: si_n_years + si_main vs si_sku para top SKUs problema (datos Apr-06)")
    p("=" * 100)
    if pids:
        rows = odoo.search_read(
            'x_hm_si_forecast',
            domain=[('x_studio_product_id', 'in', pids)],
            fields=['x_studio_product_id', 'x_studio_team_id',
                    'x_studio_week_start', 'x_studio_mu_week',
                    'x_studio_si_current', 'x_studio_si_next',
                    'x_studio_si_main_factor', 'x_studio_si_sku_factor',
                    'x_studio_si_n_years', 'x_studio_si_level',
                    'x_studio_regimen', 'x_studio_forecast_model_code'],
        )
        p(f"Filas obtenidas: {len(rows):,}")
        if rows:
            df_hm = pd.DataFrame(rows)
            df_hm["product_code"] = df_hm["x_studio_product_id"].apply(
                lambda x: id_to_code.get(x[0] if isinstance(x, list) else x, "?"))
            # Vista por SKU: agregar por product_id (promedio entre teams)
            g = df_hm.groupby("product_code").agg(
                n_teams=("x_studio_team_id", "count"),
                si_n_years_avg=("x_studio_si_n_years", "mean"),
                si_current_avg=("x_studio_si_current", "mean"),
                si_next_avg=("x_studio_si_next", "mean"),
                si_main_avg=("x_studio_si_main_factor", "mean"),
                si_sku_avg=("x_studio_si_sku_factor", "mean"),
            ).round(3)
            p("\nPromedio por SKU (cutoff actual = Apr-05, target = Apr-06 = iso_week 15):")
            p(g.to_string())

            # Quick stats
            p(f"\nDistribucion si_n_years sobre {len(df_hm)} filas:")
            p(df_hm["x_studio_si_n_years"].describe().to_string())
            p(f"\nFilas con si_n_years >= 3: {(df_hm['x_studio_si_n_years'] >= 3).sum():,} ({(df_hm['x_studio_si_n_years']>=3).mean()*100:.1f}%)")
            p(f"Filas con si_n_years < 1:  {(df_hm['x_studio_si_n_years'] < 1).sum():,}")

            p(f"\nsi_main_factor distribucion (debe ser SI categ-level, iso_week 15):")
            p(df_hm["x_studio_si_main_factor"].describe().to_string())
            p(f"\nsi_sku_factor distribucion (deviacion sku vs categ tras alpha cap):")
            p(df_hm["x_studio_si_sku_factor"].describe().to_string())

            p(f"\nDistribucion si_level (donde sale el SI):")
            p(df_hm["x_studio_si_level"].value_counts().to_string())

    # === C. Calcular SI historica directo desde POS, por categoria problema ===
    p("\n" + "=" * 100)
    p("CHECK B: SI historica desde POS por categoria (replica _calc_si_from_weekly)")
    p("=" * 100)
    p("Para cada categ: pull pos.order.line agregada por semana (read_group),")
    p("calcular promedio por iso_week sobre 36 meses, normalizar a global_avg.")
    p("Comparar SI(8) (mid-Feb) vs SI(12) (mid-Mar) y su ratio.\n")

    # Identificar categs problema desde el CSV (top 12 categs por contribucion al error)
    cat_pair = clean[clean["target_week_start"].isin(["2026-02-16", "2026-03-16"])]
    cat_g = cat_pair.groupby(["categ_id", "target_week_start"]).agg(
        fc=("forecast_qty", "sum"),
        real=("real_qty", "sum"),
    ).reset_index()
    # Tomar las categs con mayor real_feb (volumen)
    feb_vol = cat_g[cat_g["target_week_start"] == "2026-02-16"].sort_values("real", ascending=False)
    target_categs_names = feb_vol.head(12)["categ_id"].tolist()
    p(f"Top 12 categorias por volumen Feb-16:")
    for c in target_categs_names:
        p(f"  {c}")

    # Resolver nombres a IDs via product.category
    # display_name viene tipo "Bebidas Alcoholicas / Vinos / ..."
    p("\nResolviendo IDs de categoria...")
    all_cats = odoo.search_read('product.category', domain=[], fields=['id', 'display_name', 'complete_name'])
    name_to_id = {}
    for c in all_cats:
        for key in (c.get('display_name', ''), c.get('complete_name', '')):
            if key:
                name_to_id[key] = c['id']
    # Match con tolerancia a tildes (csv viene en latin-1 con cosas como AlcohÃ³licas)
    def norm(s):
        if not s: return ""
        # Reemplazos comunes de mojibake latin-1 -> utf-8
        repl = {"Ã³":"o","Ã©":"e","Ã­":"i","Ã¡":"a","Ãº":"u","Ã±":"n","Ã":"",}
        out = s
        for k,v in repl.items():
            out = out.replace(k,v)
        return out.lower().strip()
    norm_to_id = {norm(k): v for k, v in name_to_id.items()}
    categs_to_query = []
    for nm in target_categs_names:
        cid = norm_to_id.get(norm(nm))
        if cid:
            categs_to_query.append((nm, cid))
        else:
            p(f"  WARN no match para '{nm}'")
    p(f"\nMatched {len(categs_to_query)} categs\n")

    # SI history: 36 meses
    today = date.today()
    history_from = date(today.year - 3, today.month, 1).isoformat()
    p(f"Pulling pos history desde {history_from} ...")

    si_results = []
    for nm, cid in categs_to_query:
        # read_group sobre pos.order.line filtrado a esa categ
        domain = [
            ('product_id.product_tmpl_id.categ_id', '=', cid),
            ('order_id.state', 'in', ['paid', 'done', 'invoiced']),
            ('order_id.date_order', '>=', history_from),
        ]
        try:
            grp = odoo.execute(
                'pos.order.line', 'read_group',
                domain, ['qty:sum', 'order_id'], ['order_id:week'],
                lazy=False,
            )
        except Exception as e:
            p(f"  ERROR query categ {nm}: {e}")
            continue
        # Cada grupo tiene 'order_id:week' como '<week-num>, <year>'
        # Aggregate by iso_week (numerico)
        weekly = {}  # iso_week -> [list of week totals (one per matching week-year)]
        n_groups = 0
        for g in grp:
            wkey = g.get('order_id:week')
            qty = float(g.get('qty', 0.0) or 0.0)
            if not wkey or qty <= 0:
                continue
            # wkey formato: "W22, 2024" o "Wk22, 2024"
            m = re.search(r'(\d+)\D+(\d{4})', str(wkey))
            if not m:
                continue
            iso_w = int(m.group(1))
            if not (1 <= iso_w <= 52):
                continue
            weekly.setdefault(iso_w, []).append(qty)
            n_groups += 1
        if not weekly:
            p(f"  {nm[:60]}: sin data")
            continue

        # Promedio por iso_week
        avg_w = {w: sum(v)/len(v) for w, v in weekly.items()}
        global_avg = sum(avg_w.values()) / len(avg_w)
        if global_avg <= 0:
            continue
        si = {w: avg_w[w] / global_avg for w in avg_w}
        si_results.append({
            "categ": nm[:55],
            "n_weeks_hist": n_groups,
            "SI_iso_7": round(si.get(7, float('nan')), 3),
            "SI_iso_8": round(si.get(8, float('nan')), 3),
            "SI_iso_9": round(si.get(9, float('nan')), 3),
            "SI_iso_11": round(si.get(11, float('nan')), 3),
            "SI_iso_12": round(si.get(12, float('nan')), 3),
            "SI_iso_13": round(si.get(13, float('nan')), 3),
            "ratio_12_8": round(si.get(12, 1.0) / max(si.get(8, 1.0), 0.001), 3),
        })

    p("\nResultados SI historica (categ_global) por categoria:")
    if si_results:
        df_si = pd.DataFrame(si_results)
        p(df_si.to_string(index=False))
        p("\nResumen:")
        p(f"  ratio_12_8 promedio: {df_si['ratio_12_8'].mean():.3f}")
        p(f"  ratio_12_8 mediana:  {df_si['ratio_12_8'].median():.3f}")
        p(f"\n  Comparacion:")
        p(f"    Motor implicito (fc_mar/fc_feb agregado): 0.480")
        p(f"    Realidad (real_mar/real_feb agregado):     0.413")
        p(f"    Historica SI(12)/SI(8) categ-level:        {df_si['ratio_12_8'].mean():.3f}")

    OUT_PATH.write_text(buf.getvalue(), encoding="utf-8")
    print(f"Output saved to: {OUT_PATH}")


if __name__ == "__main__":
    main()
