# -*- coding: utf-8 -*-
"""
split_flete_ila.py - READ-ONLY. Mide el split producto/flete en facturas
mono-producto y cuanto distorsiona el modelo de margen al aplicar ILA sobre la
porcion de flete (que solo lleva IVA).

Modelo (correccion de Marco): raw_product_price = precio a pagar, YA incluye flete.
El total es correcto; lo que esta mal es la descomposicion. El modelo de margen
hace costo_neto = raw/(1+ila+iva) asumiendo 100% producto -> aplica ILA al flete.

Por factura mono-producto (1 sola linea con product_id):
  neto_p, ila      (linea producto)
  neto_f           (lineas flete: product_id NULL + nombre patron)
  gross_p = neto_p*(1+ila+0.19);  gross_f = neto_f*1.19
  raw_total = gross_p + gross_f                      (= precio a pagar)
  f = gross_f/raw_total                              (split flete real)
  costo_oh_model = (raw_total/(1+ila+0.19))*(1+ila)  (lo que calcula el margen hoy)
  costo_oh_real  = neto_p*(1+ila) + neto_f           (correcto: flete sin ILA)
  err_oh = costo_oh_model/costo_oh_real - 1          (sobre-costo del modelo)

Salida: consola + CSV es-CL. NO escribe en Odoo.
Correr desde la raiz:  python proyectos/2026-06-06-flujo-caja-12m/split_flete_ila.py
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from shared.odoo_xmlrpc import OdooReader

IVA = 0.19
DATE_FROM = '2025-06-01'
OUT_DIR = Path(__file__).resolve().parent / 'resultados'
GENERIC_FREIGHT_KW = ('flete', 'recargo', 'transporte', 'despacho', 'acarreo')


def norm(s):
    return (s or '').strip().lower()


def pct(values, p):
    """Percentil simple sin numpy."""
    xs = sorted(v for v in values if v is not None)
    if not xs:
        return 0.0
    k = (len(xs) - 1) * (p / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def median(values):
    return pct(values, 50)


def batched(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def main():
    odoo = OdooReader()
    print(odoo)
    print(f"Ventana: facturas in_invoice posted desde {DATE_FROM}\n")

    # ---- catalogo de impuestos: clasificar ILA vs IVA ----
    taxes = odoo.search_read('account.tax', [], ['name', 'amount', 'amount_type'])
    TAX = {}
    for t in taxes:
        name = norm(t['name'])
        is_pct = t['amount_type'] == 'percent'
        amt = t['amount'] or 0.0
        is_iva = 'iva' in name
        is_ret = 'reten' in name or amt < 0
        is_ila = is_pct and amt > 0 and not is_iva and not is_ret
        TAX[t['id']] = {'name': t['name'], 'amount': amt, 'ila': is_ila, 'iva': is_iva}

    # ---- patrones de flete por proveedor ----
    PARTNER_PATS = {}
    try:
        rules = odoo.search_read('x_vendor_freight_rule',
                                 [('x_studio_active', '=', True)],
                                 ['x_studio_partner_id', 'x_studio_freight_patterns'])
        for r in rules:
            pid = r['x_studio_partner_id'][0] if r.get('x_studio_partner_id') else None
            pats = [p.strip().lower() for p in (r.get('x_studio_freight_patterns') or '').split(',') if p.strip()]
            if pid:
                PARTNER_PATS[pid] = pats
        print(f"Reglas de flete cargadas: {len(PARTNER_PATS)} proveedores")
    except Exception as e:
        print(f"(sin x_vendor_freight_rule: {e})")

    def is_freight_line(partner_id, name):
        lab = norm(name)
        if not lab:
            return False
        for p in PARTNER_PATS.get(partner_id, []):
            if p and p in lab:
                return True
        return any(kw in lab for kw in GENERIC_FREIGHT_KW)

    # ---- paso A: moves mono-producto (exactamente 1 linea con product_id) ----
    base_dom = [('parent_state', '=', 'posted'),
                ('move_id.move_type', '=', 'in_invoice'),
                ('date', '>=', DATE_FROM),
                ('display_type', '=', 'product')]
    g = odoo.execute('account.move.line', 'read_group',
                     base_dom + [('product_id', '!=', False)],
                     ['__count'], ['move_id'], lazy=False)
    mono_ids = [row['move_id'][0] for row in g
                if row.get('move_id') and row.get('__count') == 1]
    print(f"Facturas mono-producto: {len(mono_ids)}\n")
    if not mono_ids:
        print("No hay facturas mono-producto en la ventana.")
        return

    # ---- paso B: lineas de esos moves (producto + flete) ----
    lines = []
    for chunk in batched(mono_ids, 200):
        lines += odoo.search_read(
            'account.move.line',
            [('move_id', 'in', chunk), ('display_type', '=', 'product')],
            ['move_id', 'product_id', 'name', 'quantity', 'price_subtotal', 'tax_ids'])

    # ---- moves: partner + nombre + fecha ----
    moves = {}
    for chunk in batched(mono_ids, 200):
        for m in odoo.search_read('account.move', [('id', 'in', chunk)],
                                  ['partner_id', 'name', 'invoice_date']):
            moves[m['id']] = m

    # ---- productos: categ, template, costo ----
    prod_ids = sorted({l['product_id'][0] for l in lines if l.get('product_id')})
    # detectar nombre del campo raw
    pp_fields = odoo.fields_get('product.product')
    raw_field = next((c for c in ('raw_product_price', 'x_studio_raw_product_price')
                      if c in pp_fields), None)
    pp_cols = ['categ_id', 'product_tmpl_id', 'standard_price', 'default_code', 'name']
    if raw_field:
        pp_cols.append(raw_field)
    PROD = {}
    for chunk in batched(prod_ids, 300):
        for p in odoo.search_read('product.product', [('id', 'in', chunk)], pp_cols):
            PROD[p['id']] = p
    print(f"Campo raw detectado: {raw_field}\n")

    # ---- paso C: armar por factura ----
    by_move = {}
    for l in lines:
        by_move.setdefault(l['move_id'][0], []).append(l)

    rows = []
    for mid, ls in by_move.items():
        mv = moves.get(mid, {})
        partner_id = mv['partner_id'][0] if mv.get('partner_id') else None
        prod_line = None
        neto_f = 0.0
        for l in ls:
            if l.get('product_id'):
                prod_line = l
            elif is_freight_line(partner_id, l.get('name')):
                neto_f += l['price_subtotal'] or 0.0
            # else: linea NULL no-flete (descuento/redondeo) -> ignorar
        if not prod_line:
            continue
        neto_p = prod_line['price_subtotal'] or 0.0
        qty = prod_line['quantity'] or 0.0
        if neto_p <= 0:
            continue
        ila = sum(TAX.get(tid, {}).get('amount', 0.0) / 100.0
                  for tid in prod_line.get('tax_ids', [])
                  if TAX.get(tid, {}).get('ila'))

        gross_p = neto_p * (1 + ila + IVA)
        gross_f = neto_f * (1 + IVA)
        raw_total = gross_p + gross_f
        f = gross_f / raw_total if raw_total else 0.0

        costo_oh_model = (raw_total / (1 + ila + IVA)) * (1 + ila)
        costo_oh_real = neto_p * (1 + ila) + neto_f
        err_oh = (costo_oh_model / costo_oh_real - 1) if costo_oh_real else 0.0

        pid = prod_line['product_id'][0]
        prod = PROD.get(pid, {})
        categ = prod.get('categ_id')
        raw_unit = float(prod.get(raw_field) or 0.0) if raw_field else 0.0

        rows.append({
            'move': mv.get('name'),
            'fecha': mv.get('invoice_date'),
            'proveedor': mv['partner_id'][1] if mv.get('partner_id') else '',
            'producto': '%s %s' % (prod.get('default_code') or '', prod.get('name') or ''),
            'categoria': categ[1] if categ else '',
            'qty': qty,
            'neto_p': neto_p, 'neto_f': neto_f, 'ila_pct': ila,
            'gross_p': gross_p, 'gross_f': gross_f, 'raw_total': raw_total,
            'f_split': f,
            'costo_oh_model': costo_oh_model, 'costo_oh_real': costo_oh_real,
            'err_oh': err_oh,
            'raw_unit_master': raw_unit,
            'raw_total_unit': raw_total / qty if qty else 0.0,
            'gross_p_unit': gross_p / qty if qty else 0.0,
        })

    print(f"Facturas mono-producto con linea de producto valida: {len(rows)}\n")
    report(rows)
    write_csv(rows)


def report(rows):
    clean = [r for r in rows if r['f_split'] <= 0.60]   # anomalias f>60% aparte
    anom = [r for r in rows if r['f_split'] > 0.60]

    f_all = [r['f_split'] for r in clean]
    err_all = [r['err_oh'] for r in clean]
    f_con_flete = [r['f_split'] for r in clean if r['neto_f'] > 0]

    print("=" * 74)
    print("SPLIT FLETE (gross_f / raw_total) y ERROR del modelo (err_oh)")
    print("=" * 74)
    print(f"  Facturas limpias (f<=60%): {len(clean)}  | con flete>0: {len(f_con_flete)}  "
          f"| anomalias f>60%: {len(anom)}")
    print(f"  split f  -> mediana {median(f_all):.1%}  p25 {pct(f_all,25):.1%}  p75 {pct(f_all,75):.1%}")
    if f_con_flete:
        print(f"  split f (solo con flete) -> mediana {median(f_con_flete):.1%}  "
              f"p25 {pct(f_con_flete,25):.1%}  p75 {pct(f_con_flete,75):.1%}")
    print(f"  err_oh   -> mediana {median(err_all):.2%}  p25 {pct(err_all,25):.2%}  p75 {pct(err_all,75):.2%}")
    print("  (err_oh+ = el modelo SOBRE-cuesta por aplicar ILA al flete)")

    # por categoria
    print("\n" + "-" * 74)
    print("POR CATEGORIA (solo facturas con flete>0, f<=60%)")
    print("-" * 74)
    cats = {}
    for r in clean:
        if r['neto_f'] > 0:
            cats.setdefault(r['categoria'], []).append(r)
    cat_rows = sorted(cats.items(), key=lambda kv: -len(kv[1]))
    print(f"  {'Categoria':<42}{'N':>4}{'f med':>9}{'err_oh med':>12}")
    for cat, rs in cat_rows[:20]:
        flag = '  (poca muestra)' if len(rs) < 5 else ''
        print(f"  {str(cat)[:40]:<42}{len(rs):>4}{median([x['f_split'] for x in rs]):>8.1%}"
              f"{median([x['err_oh'] for x in rs]):>11.2%}{flag}")

    # validacion raw
    print("\n" + "-" * 74)
    print("VALIDACION: que contiene raw_product_price (por unidad)")
    print("-" * 74)
    have_raw = [r for r in clean if r['raw_unit_master'] > 0 and r['qty'] > 0]
    if have_raw:
        near_total = near_prod = otro = 0
        for r in have_raw:
            ru = r['raw_unit_master']
            d_total = abs(ru / r['raw_total_unit'] - 1) if r['raw_total_unit'] else 9
            d_prod = abs(ru / r['gross_p_unit'] - 1) if r['gross_p_unit'] else 9
            if d_total <= 0.05:
                near_total += 1
            elif d_prod <= 0.05:
                near_prod += 1
            else:
                otro += 1
        n = len(have_raw)
        print(f"  Productos con raw>0: {n}")
        print(f"   raw ~ total CON flete : {near_total} ({near_total/n:.0%})")
        print(f"   raw ~ solo producto   : {near_prod} ({near_prod/n:.0%})")
        print(f"   no calza ninguno      : {otro} ({otro/n:.0%})")
    else:
        print("  No hay productos con raw_product_price > 0 para validar.")

    # caso ancla
    print("\n" + "-" * 74)
    print("CASO ANCLA FAC 178421273 (esperado AGUA CACHANTUN, neto~3711 flete~1967)")
    print("-" * 74)
    anchor = [r for r in rows if '178421273' in str(r['move'])]
    for r in anchor:
        print(f"  {r['move']} | {r['producto'][:40]}")
        print(f"   neto_p={r['neto_p']:,.0f} neto_f={r['neto_f']:,.0f} ila={r['ila_pct']:.1%} "
              f"f={r['f_split']:.1%} err_oh={r['err_oh']:.2%}")
    if not anchor:
        print("  (no aparece en mono-producto; quiza tiene >1 producto en la ventana)")


def write_csv(rows):
    OUT_DIR.mkdir(exist_ok=True)
    path = OUT_DIR / 'split_flete_ila.csv'
    cols = ['move', 'fecha', 'proveedor', 'producto', 'categoria', 'qty',
            'neto_p', 'neto_f', 'ila_pct', 'raw_total', 'f_split',
            'costo_oh_model', 'costo_oh_real', 'err_oh',
            'raw_unit_master', 'raw_total_unit', 'gross_p_unit']
    with open(path, 'w', newline='', encoding='utf-8-sig') as fh:
        w = csv.writer(fh, delimiter=';')
        w.writerow(cols)
        for r in sorted(rows, key=lambda x: -x['raw_total']):
            w.writerow([str(r.get(c, '')).replace('.', ',') if isinstance(r.get(c), float)
                        else r.get(c, '') for c in cols])
    print(f"\nCSV -> {path}")


if __name__ == '__main__':
    main()
