"""DIAG read-only: codigo de proveedor (VlrCodigo del DTE) de cada linea sin SKU.
Cruza las lineas sin producto (codigos_sin_vinculo.csv) contra el <Detalle> del
DTE, matcheando por nombre. Salida: codigos_dte_sin_producto.csv (es-CL).

Solo las facturas afectadas (~227). Batcheado. Read-only."""
from __future__ import annotations

import base64
import csv
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader  # noqa: E402
from dte_detalle import items_dte  # noqa: E402

OUT = Path(__file__).resolve().parent / 'resultados'
CHUNK = 80


def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def _norm(s):
    return ' '.join((s or '').lower().split())


def main():
    odoo = OdooReader()
    # 1) leer lineas sin SKU ya detectadas
    rows = list(csv.DictReader(
        open(OUT / 'codigos_sin_vinculo.csv', encoding='utf-8-sig'), delimiter=';'))
    facturas = sorted({r['factura'] for r in rows})
    print(f"lineas sin SKU: {len(rows)} | facturas: {len(facturas)}")

    # 2) traer esos moves (por name) con su DTE adjunto (batch)
    move_by_name = {}
    for ch in _chunks(facturas, CHUNK):
        for m in odoo.search_read('account.move',
                [('move_type', '=', 'in_invoice'), ('name', 'in', ch)],
                ['name', 'partner_id', 'l10n_cl_dte_file']):
            move_by_name[m['name']] = m

    # 3) adjuntos (batch)
    att_ids = sorted({m['l10n_cl_dte_file'][0] for m in move_by_name.values()
                      if m.get('l10n_cl_dte_file')})
    datas = {}
    for ch in _chunks(att_ids, CHUNK):
        for a in odoo.search_read('ir.attachment', [('id', 'in', ch)], ['datas']):
            datas[a['id']] = a.get('datas')

    # 4) parsear Detalle de cada factura -> dict nombre_norm -> codigo
    detalle_by_factura = {}
    for name, m in move_by_name.items():
        if not m.get('l10n_cl_dte_file'):
            continue
        raw = datas.get(m['l10n_cl_dte_file'][0])
        if not raw:
            continue
        try:
            xml = base64.b64decode(raw).decode('latin-1', 'ignore')
        except Exception:
            continue
        idx = defaultdict(list)
        for it in items_dte(xml):
            idx[_norm(it['nombre'])].append(it)
        detalle_by_factura[name] = idx

    # 5) cruzar cada linea sin SKU con el Detalle por nombre
    out_rows, sin_match = [], 0
    for r in rows:
        fac = r['factura']
        idx = detalle_by_factura.get(fac, {})
        match = idx.get(_norm(r['descripcion_linea']), [])
        codigo = match[0]['codigo'] if match else ''
        if not codigo:
            sin_match += 1
        out_rows.append({
            'rut_proveedor': r['rut_proveedor'],
            'factura': fac,
            'codigo_dte': codigo,
            'descripcion': r['descripcion_linea'],
            'monto': r['monto'],
            'match': 'si' if match else 'no',
        })

    # 6) salida detalle + agregado de codigos unicos
    with open(OUT / 'codigos_dte_sin_producto.csv', 'w', newline='',
              encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=['rut_proveedor', 'factura', 'codigo_dte',
                                          'descripcion', 'monto', 'match'],
                           delimiter=';')
        w.writeheader()
        w.writerows(out_rows)

    # agregado: codigo unico por proveedor (lo que se mapea en el maestro)
    agg = defaultdict(lambda: {'desc': '', 'n': 0, 'facturas': set()})
    for o in out_rows:
        if o['codigo_dte']:
            k = (o['rut_proveedor'], o['codigo_dte'])
            agg[k]['desc'] = o['descripcion']
            agg[k]['n'] += 1
            agg[k]['facturas'].add(o['factura'])
    with open(OUT / 'codigos_unicos_a_mapear.csv', 'w', newline='',
              encoding='utf-8-sig') as f:
        w = csv.writer(f, delimiter=';')
        w.writerow(['rut_proveedor', 'codigo_dte', 'descripcion', 'n_lineas', 'n_facturas'])
        for (rut, cod), v in sorted(agg.items(), key=lambda x: -x[1]['n']):
            w.writerow([rut, cod, v['desc'], v['n'], len(v['facturas'])])

    print(f"lineas con codigo DTE: {len(out_rows) - sin_match} | sin match nombre: {sin_match}")
    print(f"codigos unicos a mapear: {len(agg)}")
    print("\n-- muestra codigos --")
    for (rut, cod), v in sorted(agg.items(), key=lambda x: -x[1]['n'])[:15]:
        print(f"  {str(rut):14} {cod:14} {v['desc'][:40]:40} x{v['n']}")


if __name__ == '__main__':
    main()
