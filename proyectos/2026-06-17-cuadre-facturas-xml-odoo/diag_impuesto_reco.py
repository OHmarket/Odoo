"""DIAG read-only: por cada codigo CCU con ILA -> impuesto ACTUAL del producto en
Odoo (supplier_taxes_id) vs impuesto RECOMENDADO (CodImpAdic del DTE -> factor).
Salida: ccu_impuesto_actual_vs_reco.csv"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader  # noqa: E402

OUT = Path(__file__).resolve().parent / 'resultados'
RATE = {'24': '31.5%', '25': '20.5%', '26': '20.5%', '27': '10%', '271': '18%'}


def main():
    o = OdooReader()
    rows = list(csv.DictReader(open(OUT / 'ccu_codigos_config.csv', encoding='utf-8-sig'),
                               delimiter=';'))
    rows = [r for r in rows if r['cod_imp_adic'] and r['en_maestro'] != 'NO']
    print(f"codigos CCU con ILA y en maestro: {len(rows)}")

    # resolver product.product por default_code / barcode
    dc = [r['codigo_ccu'] for r in rows if r['en_maestro'] == 'default_code']
    bc = [r['ean'] for r in rows if r['en_maestro'] == 'barcode' and r['ean']]
    prod_by_dc, prod_by_bc = {}, {}
    for i in range(0, len(dc), 80):
        for p in o.search_read('product.product', [('default_code', 'in', dc[i:i+80]),
                ('active', 'in', [True, False])], ['default_code', 'name', 'supplier_taxes_id']):
            prod_by_dc[p['default_code']] = p
    for i in range(0, len(bc), 80):
        for p in o.search_read('product.product', [('barcode', 'in', bc[i:i+80]),
                ('active', 'in', [True, False])], ['barcode', 'name', 'supplier_taxes_id']):
            prod_by_bc[p['barcode']] = p

    # leer impuestos (name+amount)
    tax_ids = set()
    for p in list(prod_by_dc.values()) + list(prod_by_bc.values()):
        tax_ids.update(p.get('supplier_taxes_id') or [])
    taxes = {}
    tl = list(tax_ids)
    for i in range(0, len(tl), 80):
        for t in o.search_read('account.tax', [('id', 'in', tl[i:i+80])], ['name', 'amount']):
            taxes[t['id']] = '%s (%.1f%%)' % (t['name'][:18], t['amount'])

    out = []
    cnt = {'OK': 0, 'falta_ILA': 0, 'revisar': 0, 'sin_producto': 0}
    for r in rows:
        p = (prod_by_dc.get(r['codigo_ccu']) if r['en_maestro'] == 'default_code'
             else prod_by_bc.get(r['ean']))
        if not p:
            cnt['sin_producto'] += 1
            continue
        actual = ' + '.join(taxes.get(tid, str(tid)) for tid in (p.get('supplier_taxes_id') or [])) or '(sin impuesto)'
        reco = 'IVA 19% + ILA ' + RATE.get(r['cod_imp_adic'], '?') + ' (cod ' + r['cod_imp_adic'] + ')'
        # estado: tiene la tasa ILA recomendada en sus impuestos?
        rate_txt = RATE.get(r['cod_imp_adic'], '')
        tiene_ila = rate_txt and rate_txt in actual
        estado = 'OK' if tiene_ila else 'falta_ILA'
        cnt[estado] += 1
        out.append({'codigo': r['codigo_ccu'], 'producto': p['name'],
                    'impuesto_actual': actual, 'impuesto_recomendado': reco,
                    'estado': estado, 'n_facturas': r['n_facturas']})

    out.sort(key=lambda x: (x['estado'] != 'falta_ILA', -int(x['n_facturas'])))
    with open(OUT / 'ccu_impuesto_actual_vs_reco.csv', 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=['codigo', 'producto', 'impuesto_actual',
                           'impuesto_recomendado', 'estado', 'n_facturas'], delimiter=';')
        w.writeheader()
        w.writerows(out)

    print("resumen:", cnt)
    print(f"\n{'codigo':9} {'estado':10} {'actual':26} {'recomendado':22} producto")
    for r in out[:25]:
        print(f"  {r['codigo']:9} {r['estado']:10} {r['impuesto_actual'][:26]:26} {r['impuesto_recomendado'][:22]:22} {r['producto'][:24]}")


if __name__ == '__main__':
    main()
