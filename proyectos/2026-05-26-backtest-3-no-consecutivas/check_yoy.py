"""
Validar deterioro YoY: ventas totales POS por mes en los ultimos 36 meses.
Comparar mismo mes ano-a-ano para detectar trend bajista.

Tambien: mes a mes para las categorias problema (Helados, Aguas, etc.)
para ver si el deterioro es generalizado o por categoria.
"""
from __future__ import annotations
import sys
import io
from pathlib import Path
from datetime import date
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

OUT_PATH = Path(__file__).parent / "check_yoy_output.txt"

pd.set_option("display.float_format", lambda x: f"{x:,.0f}")
pd.set_option("display.max_columns", 60)
pd.set_option("display.width", 200)


def main():
    buf = io.StringIO()
    def p(s=""): buf.write(s + "\n")

    odoo = OdooReader()
    p(f"Conectado: {odoo}\n")

    today = date.today()
    history_from = date(today.year - 3, today.month, 1).isoformat()
    p(f"Pulling POS history desde {history_from} ...\n")

    # === 1. GLOBAL: ventas totales por mes ===
    p("=" * 100)
    p("1. VENTAS GLOBALES TOTALES POS por mes (filtrando states paid/done/invoiced)")
    p("=" * 100)
    grp = odoo.execute(
        'pos.order.line', 'read_group',
        [('order_id.state', 'in', ['paid', 'done', 'invoiced']),
         ('create_date', '>=', history_from)],
        ['qty:sum', 'price_subtotal:sum'],
        ['create_date:month'],
        lazy=False,
    )
    rows = []
    for g in grp:
        wkey = g.get('create_date:month')
        qty = float(g.get('qty', 0.0) or 0.0)
        rev = float(g.get('price_subtotal', 0.0) or 0.0)
        rows.append({'month': wkey, 'qty': qty, 'rev_clp': rev})
    df = pd.DataFrame(rows)
    p(df.to_string(index=False))

    # Parse month and pivot YoY
    p("\n--- Vista YoY (units) ---")
    # 'create_date:month' viene tipo 'mayo 2024'
    months_es = {'enero':1,'febrero':2,'marzo':3,'abril':4,'mayo':5,'junio':6,
                  'julio':7,'agosto':8,'septiembre':9,'octubre':10,'noviembre':11,'diciembre':12}
    parsed = []
    for _, r in df.iterrows():
        m = r['month']
        if not m: continue
        parts = str(m).lower().split()
        if len(parts) != 2: continue
        mo = months_es.get(parts[0])
        try:
            yr = int(parts[1])
        except: continue
        if mo:
            parsed.append({'year': yr, 'month': mo, 'qty': r['qty'], 'rev': r['rev_clp']})
    pdf = pd.DataFrame(parsed)
    if not pdf.empty:
        pivot = pdf.pivot(index='month', columns='year', values='qty')
        p(pivot.to_string())
        p("\n--- Ratio YoY (year/prev_year) units ---")
        years = sorted(pivot.columns.tolist())
        for i in range(1, len(years)):
            y_now = years[i]
            y_prev = years[i-1]
            ratio = (pivot[y_now] / pivot[y_prev]).round(3)
            p(f"\nRatio {y_now}/{y_prev}:")
            p(ratio.to_string())
            avg = ratio.dropna().mean()
            p(f"  promedio: {avg:.3f}  ({(avg-1)*100:+.1f}%)")

        p("\n--- Vista YoY (revenue CLP) ---")
        pivot_rev = pdf.pivot(index='month', columns='year', values='rev')
        p(pivot_rev.to_string())
        p("\n--- Ratio YoY revenue ---")
        for i in range(1, len(years)):
            y_now = years[i]
            y_prev = years[i-1]
            ratio = (pivot_rev[y_now] / pivot_rev[y_prev]).round(3)
            p(f"\nRatio {y_now}/{y_prev}:")
            p(ratio.to_string())
            avg = ratio.dropna().mean()
            p(f"  promedio: {avg:.3f}  ({(avg-1)*100:+.1f}%)")

    # === 2. POR CATEGORIA PROBLEMA ===
    p("\n" + "=" * 100)
    p("2. POR CATEGORIA - YoY units por mes")
    p("=" * 100)
    target_cats = [
        ('Helados', 1665),
        ('Cocteles Ice', 1631),
        ('Aguas Saborizadas', 1612),
        ('Agua Mineral', 1608),
        ('Bebidas Individuales', 1615),
        ('Bebidas Regulares', 1618),
        ('Jugos Colacion', 1643),
    ]
    for name, cid in target_cats:
        try:
            grp = odoo.execute(
                'pos.order.line', 'read_group',
                [('product_id.product_tmpl_id.categ_id', '=', cid),
                 ('order_id.state', 'in', ['paid', 'done', 'invoiced']),
                 ('create_date', '>=', history_from)],
                ['qty:sum'],
                ['create_date:month'],
                lazy=False,
            )
        except Exception as e:
            p(f"  ERROR {name}: {str(e)[:100]}")
            continue
        parsed = []
        for g in grp:
            m = g.get('create_date:month')
            qty = float(g.get('qty', 0.0) or 0.0)
            if not m: continue
            parts = str(m).lower().split()
            if len(parts) != 2: continue
            mo = months_es.get(parts[0])
            try:
                yr = int(parts[1])
            except: continue
            if mo:
                parsed.append({'year': yr, 'month': mo, 'qty': qty})
        pdf2 = pd.DataFrame(parsed)
        if pdf2.empty:
            p(f"\n--- {name} (id={cid}): sin data")
            continue
        pivot2 = pdf2.pivot(index='month', columns='year', values='qty').fillna(0)
        p(f"\n--- {name} (id={cid}) ---")
        p(pivot2.to_string())
        years = sorted(pivot2.columns.tolist())
        if len(years) >= 2:
            for i in range(1, len(years)):
                y_now = years[i]; y_prev = years[i-1]
                ratio = (pivot2[y_now] / pivot2[y_prev].replace(0, float('nan'))).round(3)
                avg = ratio.dropna().mean()
                p(f"  ratio {y_now}/{y_prev} avg: {avg:.3f}  ({(avg-1)*100:+.1f}%)")

    OUT_PATH.write_text(buf.getvalue(), encoding="utf-8")
    print(f"Output saved to: {OUT_PATH}")


if __name__ == "__main__":
    main()
