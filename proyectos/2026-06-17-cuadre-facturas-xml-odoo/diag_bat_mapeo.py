"""DIAG read-only: mapea codigo BAT (DTE) -> producto interno (default_code).
Match por sufijo de barcode (el NmbItem trae los ultimos digitos del barcode) y,
si no, por nombre. Universo = arbol de categorias 'Cigarrillos y Tabacos'.
Salida: bat_mapeo.csv (para REVISAR antes de update)."""
from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader  # noqa: E402

OUT = Path(__file__).resolve().parent / 'resultados'
STOP = {'de', 'la', 'el', 's', 'x', 'cl', 'un'}
SYN = {'pal': 'pall mall', 'ken': 'kent', 'luc': 'lucky strike',
       'blu': 'azul', 'blue': 'azul', 'red': 'rojo', 'rj': 'rojo',
       'comp': 'compact', 'sc20': '20 blando', 'sc': 'blando', 'trop': 'tropic'}


def norm(s):
    out = []
    for ch in (s or '').lower():
        out.append(ch if ch.isalnum() else ' ')
    txt = ' '.join(''.join(out).split())
    return ' '.join(SYN.get(t, t) for t in txt.split())


def toks(s):
    return set(t for t in norm(s).split() if t not in STOP and len(t) > 1)


def lead_num(nombre):
    t = (nombre or '').split()
    return t[0] if t and t[0].isdigit() else ''


def main():
    o = OdooReader()
    bat = list(csv.DictReader(
        open(OUT / 'bat_codigos_config.csv', encoding='utf-8-sig'), delimiter=';'))

    # universo: categorias bajo 'Cigarrillos y Tabacos'
    cats = o.search_read('product.category',
                         [('complete_name', 'like', 'Cigarrillos y Tabacos')], ['id'])
    cids = [c['id'] for c in cats]
    prods = o.search_read('product.product',
        [('categ_id', 'in', cids), ('active', 'in', [True, False])],
        ['default_code', 'name', 'barcode'])
    print(f"universo tabaco: {len(prods)} productos en {len(cids)} categorias")

    by_bc_suffix = {}  # ultimos 4-5 digitos del barcode -> producto
    for p in prods:
        bc = (p['barcode'] or '').strip()
        if bc:
            by_bc_suffix.setdefault(bc[-4:], []).append(p)
            by_bc_suffix.setdefault(bc[-5:], []).append(p)

    rows = []
    cnt = {'barcode': 0, 'nombre': 0, 'sin_match': 0}
    for b in bat:
        nom = b['nombre']
        ln = lead_num(nom)
        prod = None
        modo = ''
        # 1) por sufijo de barcode (lo que trae el NmbItem)
        if ln:
            cand = by_bc_suffix.get(ln) or by_bc_suffix.get(ln[-4:])
            if cand and len({c['id'] for c in cand}) == 1:
                prod = cand[0]
                modo = 'barcode'
        # 2) por nombre (token overlap)
        if not prod:
            bt = toks(nom)
            best, bestsc = None, 0.0
            for p in prods:
                pt = toks(p['name'])
                if not pt:
                    continue
                inter = len(bt & pt)
                sc = inter / max(1, len(bt | pt))
                if sc > bestsc:
                    best, bestsc = p, sc
            if best and bestsc >= 0.4:
                prod = best
                modo = 'nombre(%.2f)' % bestsc
        if prod:
            cnt['barcode' if modo == 'barcode' else 'nombre'] += 1
        else:
            cnt['sin_match'] += 1
        rows.append({'codigo_bat': b['codigo_dte'], 'nombre_dte': nom,
                     'cod_imp_adic': b['cod_imp_adic'],
                     'default_code_interno': prod['default_code'] if prod else '',
                     'producto_interno': prod['name'] if prod else '',
                     'barcode': prod['barcode'] if prod else '',
                     'match_por': modo or 'sin_match', 'n_facturas': b['n_facturas']})

    rows.sort(key=lambda r: (r['match_por'] == 'sin_match', -int(r['n_facturas'])))
    with open(OUT / 'bat_mapeo.csv', 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=['codigo_bat', 'nombre_dte', 'cod_imp_adic',
                           'default_code_interno', 'producto_interno', 'barcode',
                           'match_por', 'n_facturas'], delimiter=';')
        w.writeheader()
        w.writerows(rows)

    print("match:", cnt)
    print(f"\n{'cod_bat':10} {'->dc':10} {'modo':12} nombre_dte / interno")
    for r in rows[:25]:
        print(f"  {r['codigo_bat']:10} {str(r['default_code_interno']):10} {r['match_por']:12} "
              f"{r['nombre_dte'][:26]:26} | {r['producto_interno'][:28]}")


if __name__ == '__main__':
    main()
