"""DIAG read-only: cruza los codigos DTE sin producto contra default_code del maestro.
Clasifica cada codigo: existe_activo / existe_archivado / formato (variante sin espacio)
/ no_existe. Salida: cruce_codigos_maestro.csv (es-CL)."""
from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader  # noqa: E402

OUT = Path(__file__).resolve().parent / 'resultados'


def nospace(c):
    return c.replace(' ', '')


def main():
    odoo = OdooReader()
    rows = list(csv.DictReader(
        open(OUT / 'codigos_unicos_a_mapear.csv', encoding='utf-8-sig'), delimiter=';'))
    codes = [r['codigo_dte'] for r in rows if r['codigo_dte']]
    print(f"codigos a cruzar: {len(codes)}")

    # 1) match exacto (activos + archivados)
    exact = {}
    prods = odoo.search_read('product.product',
        [('default_code', 'in', codes), ('active', 'in', [True, False])],
        ['default_code', 'name', 'active', 'barcode'])
    for p in prods:
        exact.setdefault(p['default_code'], []).append(p)

    # 2) para los que no matchean exacto, probar variante sin espacio
    faltan = [c for c in codes if c not in exact]
    variantes = {nospace(c): c for c in faltan if nospace(c) != c}
    var_hit = {}
    if variantes:
        pv = odoo.search_read('product.product',
            [('default_code', 'in', list(variantes)), ('active', 'in', [True, False])],
            ['default_code', 'name', 'active'])
        for p in pv:
            orig = variantes.get(p['default_code'])
            if orig:
                var_hit.setdefault(orig, []).append(p)

    out = []
    cnt = {'existe_activo': 0, 'existe_archivado': 0, 'formato': 0, 'no_existe': 0}
    for r in rows:
        c = r['codigo_dte']
        if not c:
            continue
        if c in exact:
            act = any(p['active'] for p in exact[c])
            estado = 'existe_activo' if act else 'existe_archivado'
            detalle = exact[c][0]['name']
        elif c in var_hit:
            estado = 'formato'  # existe sin el espacio -> no vincula
            detalle = '%s (default_code=%s)' % (var_hit[c][0]['name'], var_hit[c][0]['default_code'])
        else:
            estado = 'no_existe'
            detalle = ''
        cnt[estado] += 1
        out.append({'rut_proveedor': r['rut_proveedor'], 'codigo_dte': c,
                    'descripcion': r['descripcion'], 'n_lineas': r['n_lineas'],
                    'estado': estado, 'detalle_maestro': detalle})

    with open(OUT / 'cruce_codigos_maestro.csv', 'w', newline='',
              encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=['rut_proveedor', 'codigo_dte', 'descripcion',
                                          'n_lineas', 'estado', 'detalle_maestro'],
                           delimiter=';')
        w.writeheader()
        w.writerows(out)

    print("\nresumen:")
    for k, v in cnt.items():
        print(f"  {k:18} {v}")
    print("\n-- 'formato' (existe sin espacio, fix barato) --")
    for o in out:
        if o['estado'] == 'formato':
            print(f"   {o['codigo_dte']:14} {o['descripcion'][:38]:38} -> {o['detalle_maestro'][:45]}")
    print("\n-- 'existe_activo' pero no vinculo (revisar) --")
    n = 0
    for o in out:
        if o['estado'] == 'existe_activo' and n < 12:
            print(f"   {o['codigo_dte']:14} {o['descripcion'][:42]:42}"); n += 1


if __name__ == '__main__':
    main()
