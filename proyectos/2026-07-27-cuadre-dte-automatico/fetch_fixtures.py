"""fetch_fixtures — baja XML reales + los montos de Odoo para los tests de T1.

Read-only. Guarda en resultados/: un .xml por factura y fixtures.json con los
montos y las lineas que necesita test_helpers.py. Se corre una vez; despues los
tests son offline (no tocan Odoo).

    python proyectos/2026-07-27-cuadre-dte-automatico/fetch_fixtures.py
"""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))
from shared.odoo_xmlrpc import OdooReader  # noqa: E402

# Casos canonicos del diseno §7 + la exenta (riesgo abierto §8).
CASOS = {
    'FAC 104357157': 'control formula impuesto: IVA 9480 + ImptoReten 2044 = 11524',
    'FAC 104357158': 'caso reportado: linea CERVEZA con ILA origen 33 sin mapear',
    'FAC 104357155': 'ILA destino errado (tax 9 vs CodImpAdic 24) y sin SKU',
    'FAC 071682':    'Google Workspace, proveedor Sistemas -> NO exige SKU',
    'FAC 5166219':   'EXENTA: MntNeto 4320 + MntExe 9 = 4329 (riesgo abierto)',
    'FAC 007426':    'control simple que ya cuadra',
    'FAC 10142151':  'recargo GLOBAL (DscRcgGlobal): 13 lineas Odoo vs 12 Detalle',
    'FAC 7471136':   'recargo EMBEBIDO en MontoItem (Peumo): flete 166.800 fuera de la base del ILA',
    'FAC 7473435':   'recargo EMBEBIDO (Peumo): flete 195.624',
    'FAC 7472785':   'recargo EMBEBIDO (Peumo): flete 78.962',
    'FAC 7472784':   'recargo EMBEBIDO (Peumo): flete 73.170, mezcla ILA 31,5%',
    'FAC 10149821':  'recargo FUERA del MontoItem (Embonor): NO debe tocarse (regresion)',
    'FAC 007375':    'HDOSO sin CdgItem, variante capitalizada: Hielo kilo / Hielo 2 k / Recargas',
    'FAC 007378':    'HDOSO sin CdgItem, variante MAYUSCULAS: HIELO KILO / HIELO 2 KILOS / RECARGAS',
    'FAC 007390':    'HDOSO sin CdgItem, con typo del proveedor: recragas',
}


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
    o = OdooReader()
    out = HERE / 'resultados'
    out.mkdir(exist_ok=True)

    moves = o.search_read(
        'account.move', [('name', 'in', sorted(CASOS))],
        fields=['id', 'name', 'state', 'partner_id', 'amount_untaxed',
                'amount_tax', 'amount_total', 'l10n_cl_dte_file'], limit=40)
    print('encontradas %d de %d' % (len(moves), len(CASOS)))

    pids = [m['partner_id'][0] for m in moves if m['partner_id']]
    tipos = {p['id']: (p.get('x_studio_tipo_proveedor') or '')
             for p in o.search_read('res.partner', [('id', 'in', pids)],
                                    fields=['x_studio_tipo_proveedor'], limit=50)}

    lines = o.search_read(
        'account.move.line',
        [('move_id', 'in', [m['id'] for m in moves]), ('display_type', '=', 'product')],
        fields=['move_id', 'name', 'product_id', 'quantity', 'price_unit',
                'price_subtotal', 'tax_ids', 'account_id'], limit=500)

    fx = {}
    for m in moves:
        raw = o.execute('ir.attachment', 'read', [m['l10n_cl_dte_file'][0]], ['datas'])
        xml = base64.b64decode(raw[0]['datas']).decode('latin-1', 'ignore')
        fname = m['name'].replace(' ', '_') + '.xml'
        (out / fname).write_text(xml, encoding='utf-8')
        fx[m['name']] = {
            'nota': CASOS[m['name']],
            'xml': fname,
            'state': m['state'],
            'tipo_proveedor': tipos.get(m['partner_id'][0] if m['partner_id'] else 0, ''),
            'amount_untaxed': m['amount_untaxed'],
            'amount_tax': m['amount_tax'],
            'amount_total': m['amount_total'],
            'lineas': [{'name': l['name'] or '',
                        'has_product': bool(l['product_id']),
                        'quantity': l['quantity'],
                        'price_unit': l['price_unit'],
                        'price_subtotal': l['price_subtotal'],
                        'tax_ids': l['tax_ids'],
                        'cuenta': (l['account_id'] or [0, ''])[1]}
                       for l in lines if l['move_id'][0] == m['id']],
        }
        print('  %-16s %-7s %-12s lineas=%d' %
              (m['name'], m['state'], fx[m['name']]['tipo_proveedor'][:12],
               len(fx[m['name']]['lineas'])))

    (out / 'fixtures.json').write_text(
        json.dumps(fx, indent=1, ensure_ascii=False), encoding='utf-8')
    print('\n-> %s' % (out / 'fixtures.json'))


if __name__ == '__main__':
    main()
