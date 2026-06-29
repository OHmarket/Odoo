# -*- coding: utf-8 -*-
"""
replica_tabla_margen.py - READ-ONLY. Replica la tabla RAW vs Factura (Bruto,
Neto Producto, Neto Flete, ILA, IVA, Costo Empresa, Valida, Venta, Margen) para
una lista de codigos, usando el PROMEDIO de sus facturas (12 meses).

RAW:     todo el bruto como producto -> aplica ILA tambien al flete (modelo actual).
Factura: producto (neto+ILA) + flete (neto, solo IVA) -> descomposicion correcta.
Salida: consola + CSV es-CL.
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
OUT = Path(__file__).resolve().parent / 'resultados' / 'tabla_margen_raw_vs_factura.csv'
FKW = ('flete', 'recargo', 'transporte', 'despacho', 'acarreo')


def norm(s): return (s or '').strip().lower()
def batched(s, n):
    for i in range(0, len(s), n): yield s[i:i+n]


def main():
    o = OdooReader(); print(o, "\n")
    taxes = {t['id']: t for t in o.search_read('account.tax', [], ['name','amount','amount_type'])}
    def ila_of(tids):
        return sum(taxes[t]['amount']/100 for t in tids if taxes.get(t)
                   and taxes[t]['amount_type']=='percent' and taxes[t]['amount']>0
                   and 'iva' not in norm(taxes[t]['name']) and 'reten' not in norm(taxes[t]['name']))
    PP = {}
    for r in o.search_read('x_vendor_freight_rule',[('x_studio_active','=',True)],
                           ['x_studio_partner_id','x_studio_freight_patterns']):
        if r.get('x_studio_partner_id'):
            PP[r['x_studio_partner_id'][0]] = [p.strip().lower() for p in
                (r.get('x_studio_freight_patterns') or '').split(',') if p.strip()]
    def is_freight(pid, name):
        lab = norm(name)
        return bool(lab) and (any(p in lab for p in PP.get(pid,[])) or any(k in lab for k in FKW))

    prods = {p['id']: p for p in o.search_read('product.product',
        [('default_code','in',CODES)],
        ['default_code','name','raw_product_price','standard_price','list_price','supplier_taxes_id'])}

    tlines = o.search_read('account.move.line',
        [('product_id','in',list(prods)),('parent_state','=','posted'),
         ('move_id.move_type','=','in_invoice'),('display_type','=','product'),
         ('date','>=',DATE_FROM)],
        ['move_id','product_id','quantity','price_subtotal','product_uom_id'])
    mids = sorted({l['move_id'][0] for l in tlines})
    alll = {}
    for ch in batched(mids,150):
        for l in o.search_read('account.move.line',
            [('move_id','in',ch),('display_type','=','product')],
            ['move_id','product_id','name','price_subtotal']):
            alll.setdefault(l['move_id'][0],[]).append(l)
    mvpart = {}
    for ch in batched(mids,150):
        for m in o.search_read('account.move',[('id','in',ch)],['partner_id']):
            mvpart[m['id']] = m['partner_id'][0] if m.get('partner_id') else None
    uids = sorted({l['product_uom_id'][0] for l in tlines if l.get('product_uom_id')})
    ratios = {u['id']: (u['ratio'] or 1.0) for u in o.search_read('uom.uom',[('id','in',uids)],['ratio'])}

    # acumular por codigo: sum(neto), sum(flete_alloc), sum(units), n, multi?
    agg = {c: {'neto':0.0,'flete':0.0,'units':0.0,'n':0,'multi':0} for c in CODES}
    for l in tlines:
        mid = l['move_id'][0]; partner = mvpart.get(mid)
        sib = alll.get(mid, [])
        plines = [s for s in sib if s.get('product_id')]
        ftot = sum(s['price_subtotal'] or 0 for s in sib
                   if not s.get('product_id') and is_freight(partner, s.get('name')))
        tot_net = sum(s['price_subtotal'] or 0 for s in plines) or 1.0
        neto = l['price_subtotal'] or 0.0
        falloc = ftot if len(plines)==1 else ftot*(neto/tot_net)
        ratio = ratios.get(l['product_uom_id'][0],1.0) if l.get('product_uom_id') else 1.0
        units = (l['quantity'] or 0)*ratio
        code = prods[l['product_id'][0]]['default_code']
        a = agg[code]
        a['neto']+=neto; a['flete']+=falloc; a['units']+=units; a['n']+=1
        if len(plines)>1: a['multi']+=1

    rows = []
    print(f"{'cod':<8}{'metodo':<10}{'Bruto':>9}{'NetoProd':>9}{'NetoFle':>8}"
          f"{'ILA':>8}{'IVA':>9}{'CostoEmp':>9}{'Valida':>9}{'Venta':>9}{'Margen':>8}")
    for code in CODES:
        a = agg[code]; pr = next(p for p in prods.values() if p['default_code']==code)
        if a['units'] <= 0:
            print(f"{code:<8} sin facturas"); continue
        ila = ila_of(pr.get('supplier_taxes_id',[]))
        neto_p = a['neto']/a['units']; neto_f = a['flete']/a['units']
        venta = (pr['list_price'] or 0)/(1+IVA)
        bruto = neto_p*(1+ila+IVA) + neto_f*(1+IVA)

        # RAW
        neto_r = bruto/(1+ila+IVA); ila_r = neto_r*ila; iva_r = neto_r*IVA
        costo_r = neto_r*(1+ila); val_r = costo_r+iva_r
        mar_r = (venta-costo_r)/venta if venta else 0
        # Factura
        ila_f = neto_p*ila; iva_f = (neto_p+neto_f)*IVA
        costo_f = neto_p*(1+ila)+neto_f; val_f = costo_f+iva_f
        mar_f = (venta-costo_f)/venta if venta else 0

        flete_flag = 'PROXY' if a['multi'] > a['n']*0.5 else 'exacto'
        for met, b, np_, nf, il, iv, ce, va, mg in [
            ('RAW', bruto, neto_r, 0.0, ila_r, iva_r, costo_r, val_r, mar_r),
            ('Factura', bruto, neto_p, neto_f, ila_f, iva_f, costo_f, val_f, mar_f)]:
            print(f"{code:<8}{met:<10}{b:>9.1f}{np_:>9.1f}{nf:>8.1f}{il:>8.1f}"
                  f"{iv:>9.1f}{ce:>9.1f}{va:>9.1f}{venta:>9.1f}{mg:>7.2%}")
            rows.append({'codigo':code,'producto':pr['name'],'metodo':met,'bruto':b,
                'neto_producto':np_,'neto_flete':nf,'ila':il,'iva':iv,'costo_empresa':ce,
                'valida':va,'venta_neta':venta,'margen':mg,'flete_tipo':flete_flag,
                'n_facturas':a['n']})
        print(f"{code:<8}{'':10}{'':9}{'':9}{'':8}{'':8}{'':9}"
              f"  var_margen={mar_f-mar_r:+.3%}pp  flete={flete_flag}  N={a['n']}\n")
        rows.append({'codigo':code,'producto':pr['name'],'metodo':'VARIACION',
            'margen':mar_f-mar_r,'flete_tipo':flete_flag,'n_facturas':a['n']})

    cols = ['codigo','producto','metodo','bruto','neto_producto','neto_flete','ila','iva',
            'costo_empresa','valida','venta_neta','margen','flete_tipo','n_facturas']
    OUT.parent.mkdir(exist_ok=True)
    with open(OUT,'w',newline='',encoding='utf-8-sig') as fh:
        w = csv.writer(fh, delimiter=';'); w.writerow(cols)
        for r in rows:
            w.writerow([(f"{r[c]:.4f}".replace('.',',') if isinstance(r.get(c),float)
                         else ('' if r.get(c) is None else r.get(c))) for c in cols])
    print(f"CSV -> {OUT}")


if __name__ == '__main__':
    main()
