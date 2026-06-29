# -*- coding: utf-8 -*-
"""
tabla_costo_facturas.py - READ-ONLY. Tabla Excel es-CL con costo-desde-facturas
para una lista de codigos, con detalle de producto y flete.

Por cada linea (factura x producto objetivo):
  - neto producto, ILA, flete atribuido (exacto si mono-producto; prorrateo por
    neto si multi-producto -> marcado como PROXY).
  - costo sin flete = neto*(1+ila);  costo con flete = +flete/unidad.
  - valor a pagar = neto*(1+ila+iva) + flete*(1+iva).

Salida: resultados/costo_facturas_3codigos.csv (sep=';', decimal=',', utf-8-sig).
Correr desde la raiz: python proyectos/2026-06-06-flujo-caja-12m/tabla_costo_facturas.py
"""
from __future__ import annotations
import csv, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from shared.odoo_xmlrpc import OdooReader

IVA = 0.19
CODES = ['9407', '445761', '0136']
DATE_FROM = '2025-06-01'
OUT = Path(__file__).resolve().parent / 'resultados' / 'costo_facturas_3codigos.csv'
GENERIC_FREIGHT_KW = ('flete', 'recargo', 'transporte', 'despacho', 'acarreo')


def norm(s): return (s or '').strip().lower()
def batched(seq, n):
    for i in range(0, len(seq), n): yield seq[i:i+n]


def main():
    o = OdooReader(); print(o, "\n")
    taxes = {t['id']: t for t in o.search_read('account.tax', [], ['name','amount','amount_type'])}
    def ila_of(tids):
        return sum(taxes[t]['amount']/100.0 for t in tids
                   if taxes.get(t) and taxes[t]['amount_type']=='percent'
                   and taxes[t]['amount']>0 and 'iva' not in norm(taxes[t]['name'])
                   and 'reten' not in norm(taxes[t]['name']))
    PP = {}
    for r in o.search_read('x_vendor_freight_rule',[('x_studio_active','=',True)],
                           ['x_studio_partner_id','x_studio_freight_patterns']):
        if r.get('x_studio_partner_id'):
            PP[r['x_studio_partner_id'][0]] = [p.strip().lower() for p in
                (r.get('x_studio_freight_patterns') or '').split(',') if p.strip()]
    def is_freight(pid,name):
        lab=norm(name)
        return bool(lab) and (any(p in lab for p in PP.get(pid,[])) or
                              any(k in lab for k in GENERIC_FREIGHT_KW))

    # productos objetivo
    prods = o.search_read('product.product',[('default_code','in',CODES)],
        ['id','default_code','name','raw_product_price','standard_price','categ_id'])
    pmap = {p['id']: p for p in prods}
    print("Productos:", [(p['default_code'],p['name']) for p in prods])

    # lineas de esos productos en facturas de compra
    tlines = o.search_read('account.move.line',
        [('product_id','in',list(pmap)),('parent_state','=','posted'),
         ('move_id.move_type','=','in_invoice'),('display_type','=','product'),
         ('date','>=',DATE_FROM)],
        ['move_id','product_id','quantity','price_subtotal','tax_ids','product_uom_id'])
    move_ids = sorted({l['move_id'][0] for l in tlines})
    print(f"Facturas involucradas: {len(move_ids)} | lineas objetivo: {len(tlines)}\n")

    # todas las lineas de esas facturas (para flete y total neto producto)
    alllines = {}
    for ch in batched(move_ids,150):
        for l in o.search_read('account.move.line',
            [('move_id','in',ch),('display_type','=','product')],
            ['move_id','product_id','name','price_subtotal']):
            alllines.setdefault(l['move_id'][0],[]).append(l)
    moves = {}
    for ch in batched(move_ids,150):
        for m in o.search_read('account.move',[('id','in',ch)],
                               ['name','invoice_date','partner_id']):
            moves[m['id']] = m
    # uom ratios
    uids = sorted({l['product_uom_id'][0] for l in tlines if l.get('product_uom_id')})
    ratios = {u['id']: (u['ratio'] or 1.0) for u in
              o.search_read('uom.uom',[('id','in',uids)],['ratio'])}

    rows = []
    for l in tlines:
        mid = l['move_id'][0]; mv = moves.get(mid,{})
        pid_partner = mv['partner_id'][0] if mv.get('partner_id') else None
        prod = pmap[l['product_id'][0]]
        siblings = alllines.get(mid,[])
        prod_lines = [s for s in siblings if s.get('product_id')]
        flete_total = sum(s['price_subtotal'] or 0 for s in siblings
                          if not s.get('product_id') and is_freight(pid_partner, s.get('name')))
        n_prod = len(prod_lines)
        tot_net = sum(s['price_subtotal'] or 0 for s in prod_lines) or 1.0
        neto = l['price_subtotal'] or 0.0
        if n_prod == 1:
            flete_alloc = flete_total; metodo = 'exacto (mono)'
        else:
            flete_alloc = flete_total * (neto / tot_net); metodo = 'prorrateo neto (PROXY)'
        ratio = ratios.get(l['product_uom_id'][0],1.0) if l.get('product_uom_id') else 1.0
        units = (l['quantity'] or 0) * ratio
        ila = ila_of(l.get('tax_ids',[]))
        neto_u = neto/units if units else 0.0
        flete_u = flete_alloc/units if units else 0.0
        costo_sin = neto_u*(1+ila)
        costo_con = costo_sin + flete_u
        valor_pagar = neto_u*(1+ila+IVA) + flete_u*(1+IVA)
        rows.append({
            'codigo': prod['default_code'], 'producto': prod['name'],
            'categoria': prod['categ_id'][1] if prod.get('categ_id') else '',
            'factura': mv.get('name'), 'fecha': mv.get('invoice_date'),
            'proveedor': mv['partner_id'][1] if mv.get('partner_id') else '',
            'tipo_factura': 'mono' if n_prod==1 else f'multi ({n_prod})',
            'qty': l['quantity'], 'ratio_uom': ratio, 'unid_equiv': units,
            'neto_prod_total': neto, 'neto_prod_unit': neto_u,
            'ila_pct': ila, 'ila_unit': neto_u*ila, 'iva_prod_unit': neto_u*IVA,
            'flete_factura_total': flete_total, 'flete_atribuido': flete_alloc,
            'metodo_flete': metodo, 'flete_unit': flete_u,
            'costo_sin_flete_unit': costo_sin, 'costo_con_flete_unit': costo_con,
            'valor_pagar_unit': valor_pagar,
            'raw_actual': prod['raw_product_price'], 'std_actual': prod['standard_price'],
        })

    rows.sort(key=lambda r:(r['codigo'], str(r['fecha'])), reverse=False)
    cols = ['codigo','producto','categoria','factura','fecha','proveedor','tipo_factura',
            'qty','ratio_uom','unid_equiv','neto_prod_total','neto_prod_unit','ila_pct',
            'ila_unit','iva_prod_unit','flete_factura_total','flete_atribuido','metodo_flete',
            'flete_unit','costo_sin_flete_unit','costo_con_flete_unit','valor_pagar_unit',
            'raw_actual','std_actual']
    OUT.parent.mkdir(exist_ok=True)
    with open(OUT,'w',newline='',encoding='utf-8-sig') as fh:
        w = csv.writer(fh, delimiter=';')
        w.writerow(cols)
        for r in rows:
            w.writerow([(f"{r[c]:.4f}".replace('.',',') if isinstance(r[c],float) else
                         ('' if r[c] is None else r[c])) for c in cols])
    print(f"Filas: {len(rows)}  ->  {OUT}\n")

    # resumen consola por codigo (promedio simple)
    print(f"{'cod':<8}{'N':>4}{'neto_u':>9}{'ila%':>6}{'flete_u':>9}"
          f"{'c_sin':>9}{'c_con':>9}{'pagar_u':>9}{'raw':>9}")
    for code in CODES:
        rs = [r for r in rows if r['codigo']==code]
        if not rs: print(f"{code:<8}  sin facturas"); continue
        n=len(rs); avg=lambda k: sum(r[k] for r in rs)/n
        print(f"{code:<8}{n:>4}{avg('neto_prod_unit'):>9.0f}{avg('ila_pct'):>6.1%}"
              f"{avg('flete_unit'):>9.0f}{avg('costo_sin_flete_unit'):>9.0f}"
              f"{avg('costo_con_flete_unit'):>9.0f}{avg('valor_pagar_unit'):>9.0f}{rs[0]['raw_actual']:>9.0f}")


if __name__ == '__main__':
    main()
