# -*- coding: utf-8 -*-
"""
ejemplo_3_productos.py - READ-ONLY. Comparativo concreto en 3 productos con ILA
distinto (STELLA 20.5%, PISCO 31.5%, COCA 18%):

  Metodo A (desde raw_product_price): costo_oh = neto + ILA
     neto_A = raw/(1+ila+iva);  costo_oh_A = neto_A*(1+ila)
  Metodo B (desde factura real):     costo_oh = neto + ILA + flete
     valor_pagar = neto_p*(1+ila+iva) + neto_f*(1+iva)
     costo_oh_B  = neto_p*(1+ila) + neto_f

Hipotesis Marco: valor a pagar igual, pero costo cambia porque el IVA se quita
sobre base distinta. Diferencia exacta = neto_f * ila * iva / (1+ila+iva).
"""
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from shared.odoo_xmlrpc import OdooReader

IVA = 0.19
CODES = ['9407', '445761', '0136']
GENERIC_FREIGHT_KW = ('flete', 'recargo', 'transporte', 'despacho', 'acarreo')


def norm(s): return (s or '').strip().lower()


def main():
    o = OdooReader()
    print(o, "\n")

    # catalogo impuestos
    taxes = {t['id']: t for t in o.search_read('account.tax', [], ['name', 'amount', 'amount_type'])}
    def ila_of(tax_ids):
        f = 0.0
        for tid in tax_ids:
            t = taxes.get(tid, {})
            nm = norm(t.get('name'))
            if t.get('amount_type') == 'percent' and (t.get('amount') or 0) > 0 \
               and 'iva' not in nm and 'reten' not in nm:
                f += t['amount'] / 100.0
        return f

    # patrones flete por proveedor
    PP = {}
    for r in o.search_read('x_vendor_freight_rule', [('x_studio_active', '=', True)],
                           ['x_studio_partner_id', 'x_studio_freight_patterns']):
        if r.get('x_studio_partner_id'):
            PP[r['x_studio_partner_id'][0]] = [p.strip().lower() for p in
                (r.get('x_studio_freight_patterns') or '').split(',') if p.strip()]
    def is_freight(pid, name):
        lab = norm(name)
        if not lab: return False
        if any(p in lab for p in PP.get(pid, [])): return True
        return any(k in lab for k in GENERIC_FREIGHT_KW)

    for code in CODES:
        ps = o.search_read('product.product', [('default_code', '=', code)],
                           ['id', 'name', 'raw_product_price', 'standard_price',
                            'supplier_taxes_id', 'uom_id'])
        if not ps:
            print(f"### {code}: no encontrado\n"); continue
        p = ps[0]
        ila = ila_of(p.get('supplier_taxes_id', []))
        raw = p['raw_product_price'] or 0.0
        neto_A = raw / (1 + ila + IVA)
        costo_oh_A = neto_A * (1 + ila)

        print("=" * 78)
        print(f"### {code}  {p['name']}   ILA={ila:.1%}")
        print("=" * 78)
        print(f"  raw_product_price = {raw:,.1f}  (std={p['standard_price']:,.1f})")
        print(f"  METODO A (desde raw):  neto={neto_A:,.1f}  +ILA  ->  costo_oh_A={costo_oh_A:,.1f}")

        # ultima factura mono-producto del producto
        mls = o.search_read('account.move.line',
                            [('product_id', '=', p['id']), ('parent_state', '=', 'posted'),
                             ('move_id.move_type', '=', 'in_invoice'),
                             ('display_type', '=', 'product')],
                            ['move_id', 'price_subtotal', 'quantity', 'product_uom_id'],
                            order='date desc', limit=40)
        chosen = None
        for ml in mls:
            mid = ml['move_id'][0]
            # mono-producto?
            cnt = o.search_count('account.move.line',
                                 [('move_id', '=', mid), ('display_type', '=', 'product'),
                                  ('product_id', '!=', False)])
            if cnt == 1:
                chosen = (mid, ml); break
        if not chosen:
            print("  (sin factura mono-producto reciente para Metodo B)\n"); continue
        mid, ml = chosen
        mv = o.search_read('account.move', [('id', '=', mid)],
                           ['name', 'invoice_date', 'partner_id'])[0]
        pid = mv['partner_id'][0] if mv.get('partner_id') else None
        # lineas flete de la factura
        all_lines = o.search_read('account.move.line',
                                  [('move_id', '=', mid), ('display_type', '=', 'product')],
                                  ['product_id', 'name', 'price_subtotal'])
        neto_f = sum(l['price_subtotal'] or 0 for l in all_lines
                     if not l.get('product_id') and is_freight(pid, l.get('name')))
        # uom ratio -> unidades equivalentes
        ratio = 1.0
        if ml.get('product_uom_id'):
            ur = o.search_read('uom.uom', [('id', '=', ml['product_uom_id'][0])], ['ratio'])
            if ur: ratio = ur[0]['ratio'] or 1.0
        units = (ml['quantity'] or 0) * ratio
        neto_p = ml['price_subtotal'] or 0.0
        neto_p_u = neto_p / units if units else 0.0
        neto_f_u = neto_f / units if units else 0.0

        valor_pagar = neto_p_u * (1 + ila + IVA) + neto_f_u * (1 + IVA)
        costo_oh_B = neto_p_u * (1 + ila) + neto_f_u
        f_split = (neto_f_u * (1 + IVA)) / valor_pagar if valor_pagar else 0.0
        dif = costo_oh_A - costo_oh_B
        dif_teor = neto_f_u * ila * IVA / (1 + ila + IVA)

        print(f"\n  METODO B (factura {mv['name']}, {mv['invoice_date']}, {mv['partner_id'][1][:24]}):")
        print(f"    qty={ml['quantity']} x ratio={ratio} = {units:g} u  | flete factura={neto_f:,.0f}")
        print(f"    por unidad:  neto_p={neto_p_u:,.1f}  neto_f={neto_f_u:,.1f}  split flete={f_split:.1%}")
        print(f"    valor a pagar/u = {valor_pagar:,.1f}   (raw={raw:,.1f})")
        print(f"    costo_oh_B = neto_p*(1+ila)+neto_f = {costo_oh_B:,.1f}")
        print(f"\n  >>> costo_oh:  A={costo_oh_A:,.1f}  vs  B={costo_oh_B:,.1f}   "
              f"dif={dif:,.1f} ({dif/costo_oh_B if costo_oh_B else 0:+.2%})")
        print(f"      dif teorica neto_f*ila*iva/(1+ila+iva) = {dif_teor:,.1f}  (check)")
        print()


if __name__ == '__main__':
    main()
