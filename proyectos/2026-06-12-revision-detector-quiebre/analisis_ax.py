"""
Analisis de quiebres — SOLO AX (sonda).

Read-only contra x_stock_balance_daily. TODO via read_group: Postgres agrega
server-side y devuelve decenas de filas, nunca el ~1M crudo (eso es lo que mato
el server al hacer el "api completo del modelo"). Cada bloque imprime su tiempo
para confirmar que la query no tensa al server.

Salida: consola + CSVs en resultados/ (formato Excel-CL ; , utf-8-sig).
"""
from __future__ import annotations
import sys
import time
from pathlib import Path
from datetime import date

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

MODEL = 'x_stock_balance_daily'
ABC = 'AX'
OUT_DIR = Path(__file__).resolve().parent / 'resultados'
OUT_DIR.mkdir(exist_ok=True)


def rg(odoo, domain, groupby, *, measures=('__count',), orderby=None, limit=None):
    """read_group con timing. measures: lista de 'campo:sum' o '__count'."""
    fields = [m for m in measures if m != '__count']
    kw = {'lazy': False}
    if orderby:
        kw['orderby'] = orderby
    if limit:
        kw['limit'] = limit
    t0 = time.time()
    rows = odoo.execute(MODEL, 'read_group', domain, fields, groupby, **kw)
    dt = time.time() - t0
    print(f"  [{dt:5.2f}s] groupby={groupby} domain={domain} -> {len(rows)} filas")
    return rows


def dump_csv(rows, cols, name):
    import csv
    path = OUT_DIR / name
    with path.open('w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f, delimiter=';')
        w.writerow(cols)
        for r in rows:
            w.writerow([_cell(r.get(c)) for c in cols])
    print(f"    -> {path.name}")


def _cell(v):
    if isinstance(v, (list, tuple)):  # m2o [id, name]
        return v[1] if len(v) > 1 else v[0]
    if isinstance(v, float):
        return str(v).replace('.', ',')
    return v


def main():
    odoo = OdooReader()
    today = date.today().strftime('%Y-%m-%d')
    print(f"Conectado: {odoo}\n")

    # 0) Confirmar labels ABCXYZ y volumen total (1 query, ~9 buckets)
    print("== 0. Distribucion por ABCXYZ (confirma label exacto de AX) ==")
    by_abc = rg(odoo, [], ['x_studio_abcxyz'], measures=['__count'])
    for r in sorted(by_abc, key=lambda x: -x['__count']):
        print(f"    {r.get('x_studio_abcxyz')!r:18} {r['__count']:>9,} dias-quiebre")

    dom = [('x_studio_abcxyz', '=', ABC)]
    n_ax = odoo.search_count(MODEL, dom)
    print(f"\n== AX: {n_ax:,} dias-quiebre totales ==\n")
    if n_ax == 0:
        print("AX vacio o label distinto. Revisa el bloque 0 y ajusta ABC.")
        return

    # 1) AX por sala x mes
    print("== 1. AX por sala x mes ==")
    r1 = rg(odoo, dom, ['x_studio_team_id', 'x_studio_date:month'],
            measures=['__count', 'x_studio_qty_out:sum'])
    dump_csv(r1, ['x_studio_team_id', 'x_studio_date:month', '__count',
                  'x_studio_qty_out'], 'ax_sala_mes.csv')

    # 2) AX por categoria
    print("== 2. AX por categoria ==")
    r2 = rg(odoo, dom, ['x_studio_categ_id'], measures=['__count'],
            orderby='__count desc')
    dump_csv(r2, ['x_studio_categ_id', '__count'], 'ax_categoria.csv')

    # 3) AX por proveedor
    print("== 3. AX por proveedor ==")
    r3 = rg(odoo, dom, ['x_studio_supplier_id'], measures=['__count'],
            orderby='__count desc')
    dump_csv(r3, ['x_studio_supplier_id', '__count'], 'ax_proveedor.csv')

    # 4) Total vs parcial
    print("== 4. AX total vs parcial (intradia) ==")
    r4 = rg(odoo, dom, ['x_studio_stockout_partial'], measures=['__count'])
    for r in r4:
        tipo = 'parcial' if r.get('x_studio_stockout_partial') else 'total'
        print(f"    {tipo:8} {r['__count']:>9,}")

    # 5) Top SKUs AX
    print("== 5. Top 50 SKUs AX por dias-quiebre ==")
    r5 = rg(odoo, dom, ['x_studio_product_id'], measures=['__count'],
            orderby='__count desc', limit=50)
    dump_csv(r5, ['x_studio_product_id', '__count'], 'ax_top_skus.csv')

    # 6) Quiebres AX vigentes HOY
    n_hoy = odoo.search_count(MODEL, dom + [('x_studio_date', '=', today)])
    print(f"\n== 6. AX en quiebre HOY ({today}): {n_hoy:,} pares sala-SKU ==")

    print("\nListo. CSVs en resultados/. Ninguna query bajo filas crudas.")


if __name__ == '__main__':
    main()
