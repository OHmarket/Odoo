import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
import pandas as pd
from shared.odoo_xmlrpc import OdooReader

o = OdooReader()
df = pd.read_parquet(Path(__file__).parent / "rank_week_sku_cache.parquet")
for wk in ("2025-09-15", "2026-02-02"):
    g = o.execute("x_x_pos_week_sku_fact", "read_group",
                  [("x_studio_week_start", "=", wk)],
                  ["x_studio_units:sum"], [], lazy=False)
    tot_fact = (g[0].get("x_studio_units") or 0.0) if g else 0.0
    tot_cache = df[df["week"].astype(str) == wk]["qty"].sum()
    diff = (tot_cache - tot_fact) / tot_fact * 100 if tot_fact else float("nan")
    print(f"{wk}: fact_categ={tot_fact:,.0f}  cache_sku={tot_cache:,.0f}  delta={diff:+.2f}%")
