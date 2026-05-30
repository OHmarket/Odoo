"""
Top 20 SKUs con mayor error absoluto en el backtest v3.46
(3 semanas W18-W20, 12 teams).

Aplica el filtro de ruido estandar (memoria Marco): excluir
cervezas, cigarros/tabacos, snacks, impulsivos y Ventas San Jose.

Metrica: suma de abs_error_qty agregada por SKU x todas las
sem y teams (excluyendo Ventas San Jose).
"""
from __future__ import annotations
from pathlib import Path
import pandas as pd

CSV = Path(r"c:\Users\sanhu\Odoo\OH Forecast Backtest (x_forecast_backtest) (2).csv")

EXCLUIR_CATEG = ("Cervezas", "Cigarros", "Tabaco", "Snacks", "Impulsivos")
EXCLUIR_TEAM = ("Ventas San Jos",)  # incluye encoding latin

pd.set_option("display.float_format", lambda x: f"{x:,.1f}")
pd.set_option("display.width", 260)
pd.set_option("display.max_columns", 30)
pd.set_option("display.max_colwidth", 60)


def main():
    df = pd.read_csv(CSV, low_memory=False, encoding="latin-1")
    print(f"Filas totales: {len(df):,}")

    # Excluir Ventas San Jose
    mask_team = df["team_id"].fillna("").apply(
        lambda t: not any(x in t for x in EXCLUIR_TEAM)
    )
    df = df[mask_team]
    print(f"Tras excluir San Jose: {len(df):,}")

    # Excluir categorias ruido
    mask_cat = df["categ_id"].fillna("").apply(
        lambda c: not any(x in c for x in EXCLUIR_CATEG)
    )
    excluidas = df[~mask_cat]
    df = df[mask_cat]
    print(f"Excluidos por categoria ruido: {len(excluidas):,}")
    print(f"  desglose:")
    for kw in EXCLUIR_CATEG:
        n = excluidas["categ_id"].fillna("").str.contains(kw).sum()
        if n:
            print(f"    {kw}: {n:,}")
    print(f"Filas finales para ranking: {len(df):,}")

    # Forzar numericos
    for c in ["forecast_qty", "real_qty", "abs_error_qty", "error_qty"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0.0)

    # Agregado por SKU
    agg = df.groupby("product_id").agg(
        n_filas=("forecast_qty", "size"),
        n_teams=("team_id", "nunique"),
        sum_real=("real_qty", "sum"),
        sum_fcst=("forecast_qty", "sum"),
        sum_abs_err=("abs_error_qty", "sum"),
        sum_err_signed=("error_qty", "sum"),
    ).reset_index()

    # error_qty firmado: convencion del CSV. Confirmo signo: bias = real - fcst,
    # asi que error positivo = over-forecast, error negativo = sub-forecast.
    # Validamos con: si sum_real > sum_fcst -> sub-forecast.
    agg["delta_real_minus_fcst"] = agg["sum_real"] - agg["sum_fcst"]
    safe_real = agg["sum_real"].where(agg["sum_real"] != 0, other=float("nan"))
    agg["wape_pct"] = (agg["sum_abs_err"] / safe_real * 100).round(1)
    agg["bias_pct"] = (agg["delta_real_minus_fcst"] / safe_real * 100).round(1)
    agg["direccion"] = agg["delta_real_minus_fcst"].apply(
        lambda d: "SUB" if d > 0 else ("OVER" if d < 0 else "OK")
    )

    # Categoria y abcxyz (toma primero)
    meta = df.groupby("product_id").agg(
        categ_id=("categ_id", "first"),
        abcxyz=("abcxyz", "first"),
        ciclo=("ciclo_de_vida", "first"),
        regimen=("regimen", "first"),
    ).reset_index()
    out = agg.merge(meta, on="product_id", how="left")

    # Sub-categoria L3 desde categ_id ("A / B / C / D" -> C)
    def _l3(c):
        parts = str(c or "").split(" / ")
        return parts[2] if len(parts) >= 3 else parts[-1]
    out["sub_cat"] = out["categ_id"].apply(_l3)

    # Top 20 por suma de error absoluto
    top = out.sort_values("sum_abs_err", ascending=False).head(20)

    cols = [
        "product_id", "sub_cat", "abcxyz", "regimen", "n_teams",
        "sum_real", "sum_fcst", "sum_abs_err", "delta_real_minus_fcst",
        "wape_pct", "bias_pct", "direccion",
    ]
    print("\n===== TOP 20 SKUs por suma_abs_error (3 sem x hasta 11 teams) =====")
    print(top[cols].to_string(index=False))

    # Totales del top 20 vs total dataset
    print(f"\nTotales:")
    print(f"  TOTAL dataset (post-filtro): real={out['sum_real'].sum():,.0f}  "
          f"fcst={out['sum_fcst'].sum():,.0f}  abs_err={out['sum_abs_err'].sum():,.0f}")
    print(f"  TOP 20:                     real={top['sum_real'].sum():,.0f}  "
          f"fcst={top['sum_fcst'].sum():,.0f}  abs_err={top['sum_abs_err'].sum():,.0f}  "
          f"(= {top['sum_abs_err'].sum() / out['sum_abs_err'].sum() * 100:.1f}% del error total)")

    # Cuantos SUB vs OVER en top 20
    n_sub = (top["direccion"] == "SUB").sum()
    n_over = (top["direccion"] == "OVER").sum()
    print(f"  TOP 20: SUB-forecast={n_sub}  OVER-forecast={n_over}")

    OUT = Path(__file__).parent / "top_skus_error.csv"
    top[cols].to_csv(OUT, index=False, encoding="utf-8")
    print(f"\nCSV: {OUT}")


if __name__ == "__main__":
    main()
