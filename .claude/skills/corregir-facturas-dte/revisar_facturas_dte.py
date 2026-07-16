"""
revisar_facturas_dte — Diagnostico read-only de facturas de compra vs XML del DTE.

Compara cada factura de compra de Odoo contra el XML del DTE adjunto
(ir.attachment 'DTE_<folio>.xml') y detecta los dos descuadres del proceso de
carga manual (vincular codigos -> aplicar posicion fiscal -> cuadrar montos):

  1. PRECIO pisado por el maestro   (price_subtotal != MontoItem del DTE)
     Causa: al vincular product_id, el onchange recalcula price_unit desde el
     precio historico del producto. Ver [[feedback-vincular-product-id-pisa-precio]].
  2. ILA sin mapear                 (la linea quedo con el impuesto ORIGEN "Compra (OC)")
     Causa: la posicion fiscal (id 12 "Facturas de Compra") no re-mapeo los
     impuestos de linea. El impuesto correcto lo define la posicion fiscal via
     map_tax(product.supplier_taxes_id), NO una tabla inventada.
     Ver [[ref_ila_descuadre_posicion_fiscal]].

NO escribe en Odoo. Corre read-only via shared/odoo_xmlrpc.py y EMITE un
Server Action safe_eval que, por cada factura afectada: (a) re-aplica la posicion
fiscal a cada linea (map_tax de supplier_taxes) y (b) cuadra el precio al XML.
Se corre en Odoo con DRY_RUN=True y luego False.

Uso (desde la raiz del repo):
    python .claude/skills/corregir-facturas-dte/revisar_facturas_dte.py 179103055 179103059
    python .claude/skills/corregir-facturas-dte/revisar_facturas_dte.py --proveedor CCU --fecha 2026-07-02
"""

from __future__ import annotations

import argparse
import base64
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

# .claude/skills/corregir-facturas-dte/este.py -> parents[3] = raiz del repo.
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from shared.odoo_xmlrpc import OdooReader  # noqa: E402

CENT = 1.0  # tolerancia en $ (redondeo del DTE)
FP_FACTURAS_COMPRA = 12  # posicion fiscal "Facturas de Compra" (mapea ILA de compra)


# ----------------------------------------------------------------------------- XML
def _strip_ns(tag: str) -> str:
    return tag.split('}', 1)[-1] if '}' in tag else tag


def parse_dte(raw: bytes) -> dict:
    root = ET.fromstring(raw)
    doc = {'neto': 0, 'iva': 0, 'total': 0, 'lineas': []}
    for el in root.iter():
        tag = _strip_ns(el.tag)
        if tag == 'Totales':
            for c in el:
                ct = _strip_ns(c.tag)
                if ct == 'MntNeto':
                    doc['neto'] = int(c.text)
                elif ct == 'IVA':
                    doc['iva'] = int(c.text)
                elif ct == 'MntTotal':
                    doc['total'] = int(c.text)
        elif tag == 'Detalle':
            ln = {'code': None, 'qty': 0.0, 'monto': 0, 'nombre': ''}
            for c in el:
                ct = _strip_ns(c.tag)
                if ct == 'CdgItem':
                    tpo = val = None
                    for cc in c:
                        cct = _strip_ns(cc.tag)
                        if cct == 'TpoCodigo':
                            tpo = cc.text
                        elif cct == 'VlrCodigo':
                            val = cc.text
                    if tpo == 'INT1':
                        ln['code'] = val
                elif ct == 'NmbItem':
                    ln['nombre'] = c.text or ''
                elif ct == 'QtyItem':
                    ln['qty'] = float(c.text)
                elif ct == 'MontoItem':
                    ln['monto'] = int(c.text)
            doc['lineas'].append(ln)
    return doc


# ----------------------------------------------------------------------------- Odoo
def resolve_moves(o: OdooReader, args) -> list[dict]:
    fields = ['id', 'name', 'partner_id', 'amount_untaxed', 'amount_tax',
              'amount_total', 'state', 'invoice_date', 'fiscal_position_id']
    if args.folios:
        names = ['FAC %s' % f for f in args.folios]
        return o.search_read('account.move', [('name', 'in', names)], fields=fields, limit=len(names) + 5)
    dom = [('move_type', '=', 'in_invoice'), ('partner_id.name', 'ilike', args.proveedor)]
    if args.fecha:
        dom.append(('invoice_date', '=', args.fecha))
    if args.estado:
        dom.append(('state', '=', args.estado))
    return o.search_read('account.move', dom, fields=fields, limit=200, order='name')


def dte_attachment(o: OdooReader, move_id: int) -> bytes | None:
    a = o.search_read('ir.attachment',
                      [('res_model', '=', 'account.move'), ('res_id', '=', move_id),
                       ('name', 'like', 'DTE_')], fields=['id'], limit=5)
    if not a:
        return None
    d = o.execute('ir.attachment', 'read', [a[0]['id']], ['datas'])
    return base64.b64decode(d[0]['datas'])


def fiscal_src_taxes(o: OdooReader, fp_id: int) -> set[int]:
    """tax_src_id de la posicion fiscal que cambian al mapear = impuestos ORIGEN 'OC'.
    Si una linea los tiene, la posicion fiscal aun no se aplico."""
    m = o.search_read('account.fiscal.position.tax', [('position_id', '=', fp_id)],
                      fields=['tax_src_id', 'tax_dest_id'], limit=100)
    return {r['tax_src_id'][0] for r in m if r['tax_src_id'][0] != r['tax_dest_id'][0]}


_CODE_RE = re.compile(r'^\[(\w+)\]')


def line_code(line: dict) -> str | None:
    p = line.get('product_id')
    if not p:
        return None
    m = _CODE_RE.match(p[1])
    return m.group(1) if m else None


# ----------------------------------------------------------------------------- Diagnostico
def diagnose(o: OdooReader, move: dict, src_oc: set[int]) -> dict:
    raw = dte_attachment(o, move['id'])
    if raw is None:
        return {'move': move, 'error': 'sin XML DTE adjunto'}
    dte = parse_dte(raw)

    lines = o.search_read('account.move.line',
                          [('move_id', '=', move['id']), ('display_type', '=', 'product')],
                          fields=['id', 'name', 'product_id', 'quantity',
                                  'price_unit', 'price_subtotal', 'tax_ids'], limit=200)
    by_code = {line_code(l): l for l in lines if line_code(l)}

    price_fixes = []   # (line_id, nombre, pu_now, pu_target, sub_now, sub_target)
    warns = []
    matched = set()

    for d in dte['lineas']:
        if d['code'] == '9999' or 'FLETE' in d['nombre'].upper():
            continue
        ol = by_code.get(d['code'])
        if ol is None:
            warns.append('linea DTE %s (%s) sin match en Odoo' % (d['code'], d['nombre'][:30]))
            continue
        matched.add(ol['id'])
        qty = ol['quantity']
        if abs(qty - d['qty']) > 1e-6:
            # qty redondeada (fraccion de pack; Odoo cap 2 decimales en UoM):
            # el price_unit YA es el correcto del DTE, el descuadre es ruido de
            # redondeo. NO se cuadra el precio (desviarlo contamina costo/WAC).
            # Solo se reporta y la linea queda EXCLUIDA del fix.
            warns.append('qty distinta en %s: Odoo %s vs DTE %s -> EXCLUIDA (redondeo, no se cuadra el precio)'
                         % (d['nombre'][:30], qty, d['qty']))
            continue
        if abs(ol['price_subtotal'] - d['monto']) > CENT:
            pu_target = round(d['monto'] / qty, 2) if qty else 0.0
            price_fixes.append((ol['id'], ol['name'][:38], ol['price_unit'], pu_target,
                                ol['price_subtotal'], d['monto']))

    # ILA sin mapear: alguna linea con impuesto ORIGEN 'OC' presente.
    tax_dirty = [l for l in lines if src_oc & set(l['tax_ids'])]

    delta = round(move['amount_total'] - dte['total'], 2)
    afectado = bool(price_fixes or tax_dirty) or abs(delta) > CENT
    return {'move': move, 'dte': dte, 'price_fixes': price_fixes,
            'tax_dirty': tax_dirty, 'warns': warns, 'delta_total': delta, 'afectado': afectado}


# ----------------------------------------------------------------------------- Reporte + SA
def print_report(results: list[dict]) -> None:
    n = 0
    for r in results:
        m = r['move']
        if r.get('error'):
            print('  %-16s  ERROR: %s' % (m['name'], r['error']))
            continue
        if not r['afectado']:
            print('  %-16s  OK  total=%s' % (m['name'], m['amount_total']))
            continue
        n += 1
        print('\n  %-16s  delta=%+d  (Odoo %s vs DTE %s)'
              % (m['name'], r['delta_total'], m['amount_total'], r['dte']['total']))
        if r['tax_dirty']:
            print('      tax: %d linea(s) con ILA origen sin mapear -> re-aplicar posicion fiscal'
                  % len(r['tax_dirty']))
        for (_lid, nombre, pu_now, pu_tgt, sub_now, sub_tgt) in r['price_fixes']:
            print('      precio: %-38s  pu %s->%s  (sub %s->%s)'
                  % (nombre, pu_now, pu_tgt, sub_now, sub_tgt))
        for w in r['warns']:
            print('      ! %s' % w)
    print('\n  %d factura(s) con descuadre de %d revisada(s).' % (n, len(results)))


def emit_server_action(results: list[dict], out: Path) -> tuple[int, int]:
    move_ids, price_rows = [], []
    for r in results:
        if r.get('error') or not r['afectado']:
            continue
        if not r['price_fixes'] and not r['tax_dirty']:
            continue  # solo descuadre por redondeo de qty (excluido): nada accionable
        move_ids.append((r['move']['id'], r['move']['name']))
        for (lid, nombre, _pn, pu_tgt, _sn, _st) in r['price_fixes']:
            price_rows.append('    %d: %r,  # %s | %s' % (lid, pu_tgt, r['move']['name'], nombre))
    # Siempre reescribir el archivo: si no hay nada que emitir, queda un SA no-op
    # (MOVES vacio) en vez de un SA STALE de una corrida anterior. Un archivo stale
    # se pega por error y aplica fixes ya obsoletos/incorrectos.
    moves_txt = '\n'.join('    %d,  # %s' % (mid, name) for mid, name in move_ids)
    body = (SA_TEMPLATE
            .replace('# __MOVES__', moves_txt)
            .replace('# __PRICE__', '\n'.join(price_rows)))
    out.write_text(body, encoding='utf-8')
    return len(move_ids), len(price_rows)


SA_TEMPLATE = '''# -*- coding: utf-8 -*-
# OH Corregir Facturas DTE -- generado por skill corregir-facturas-dte
# Pegar en ir.actions.server, Modelo = account.move, safe_eval.
# Corre PRIMERO con DRY_RUN=True (solo loguea), luego False para aplicar.
# Por cada factura afectada: (1) re-aplica la posicion fiscal a cada linea
# (map_tax de supplier_taxes -> mapea el ILA correcto) y (2) cuadra el precio.
# NO re-vincula product_id (eso vuelve a pisar el precio). Solo facturas en draft.

DRY_RUN = True
FP_DEFAULT = 12  # "Facturas de Compra"

MOVES = [
# __MOVES__
]
PRICE = {
# __PRICE__
}

msgs = []
for mid in MOVES:
    move = env['account.move'].browse(mid)
    if not move.exists() or move.state != 'draft':
        msgs.append('SKIP move %s: no existe o no esta en draft' % mid)
        continue
    fp = move.fiscal_position_id or env['account.fiscal.position'].browse(FP_DEFAULT)
    for line in move.invoice_line_ids:
        if line.display_type:
            continue
        vals = {}
        src = line.product_id.supplier_taxes_id
        if src:
            nuevo = fp.map_tax(src).ids
            if sorted(nuevo) != sorted(line.tax_ids.ids):
                vals['tax_ids'] = [(6, 0, nuevo)]
        if line.id in PRICE:
            vals['price_unit'] = PRICE[line.id]
            vals['discount'] = 0.0
        if not vals:
            continue
        if DRY_RUN:
            msgs.append('DRY %s L%s (%s): tax %s->%s pu=%s'
                        % (move.name, line.id, line.name[:24], line.tax_ids.ids,
                           vals.get('tax_ids'), vals.get('price_unit', '=')))
        else:
            line.write(vals)
            msgs.append('OK  %s L%s (%s)' % (move.name, line.id, line.name[:24]))

texto = '\\n'.join(msgs) or 'nada que hacer'
log(texto)
action = {
    'type': 'ir.actions.client', 'tag': 'display_notification',
    'params': {'title': 'Corregir Facturas DTE (%s)' % ('DRY_RUN' if DRY_RUN else 'APLICADO'),
               'message': texto, 'sticky': True},
}
'''


# ----------------------------------------------------------------------------- CLI
def main() -> None:
    ap = argparse.ArgumentParser(description='Diagnostico factura compra vs XML DTE (read-only).')
    ap.add_argument('folios', nargs='*', help='folios a revisar (ej: 179103055)')
    ap.add_argument('--proveedor', help='nombre (ilike) del proveedor, ej: CCU')
    ap.add_argument('--fecha', help='invoice_date exacta YYYY-MM-DD')
    ap.add_argument('--estado', default='draft', help='state (default draft; vacio = todos)')
    ap.add_argument('--out', help='ruta del Server Action emitido (.py)')
    args = ap.parse_args()
    if not args.folios and not args.proveedor:
        ap.error('da folios o --proveedor')
    if args.estado == '':
        args.estado = None
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

    o = OdooReader()
    src_oc = fiscal_src_taxes(o, FP_FACTURAS_COMPRA)
    moves = resolve_moves(o, args)
    if not moves:
        print('Sin facturas para el criterio dado.')
        return
    print('Revisando %d factura(s)...\n' % len(moves))
    results = [diagnose(o, m, src_oc) for m in moves]
    print_report(results)

    out = Path(args.out) if args.out else Path.cwd() / 'corregir_facturas_dte_SA.py'
    nm, npr = emit_server_action(results, out)
    if nm:
        print('\n  Server Action: %d factura(s), %d precio(s) a cuadrar -> %s' % (nm, npr, out))
        print('  Pegar en Odoo (account.move, safe_eval). DRY_RUN=True primero.')
    else:
        print('\n  Nada que corregir. SA reescrito como no-op (MOVES vacio) -> %s' % out)


if __name__ == '__main__':
    main()
