# -*- coding: utf-8 -*-
"""Contraste venta contable vs venta POS, mes a mes. Read-only.
Objetivo: decidir si la caida de venta de ene a jul es real (menos venta)
o contable (venta que dejo de registrarse / se fue a otra compania)."""
import sys
import datetime
from consulta_ratios_jsonrpc import Odoo, fmt_money, fmt_pct, pad_l, pad_r, ultimo_dia, MES

o = Odoo()
sys.stderr.write('conectado\n')

comps = o.call('res.company', 'search_read', [], ['name'])
print('COMPANIAS VISIBLES PARA EL USUARIO: %s' % len(comps))
for c in comps:
    print('   id=%s  %s' % (c['id'], c['name']))
print('')

ing = o.call('account.account', 'search_read',
             [('account_type', 'in', ['income'])], ['code', 'name'])
ing_ids = [a['id'] for a in ing]

print('%s | %s | %s | %s | %s | %s' % (pad_r('MES', 9), pad_l('VENTA CONTABLE', 16),
      pad_l('POS BRUTO', 16), pad_l('POS NETO/1,19', 15), pad_l('DIF %', 8), pad_l('TICKETS POS', 12)))
print('-' * 90)
for m in range(1, 10):
    d0 = datetime.date(2026, m, 1)
    d1 = ultimo_dia(2026, m)
    if d0 > datetime.date.today():
        break
    rows = o.call('account.move.line', 'read_group',
                  [('parent_state', '=', 'posted'), ('account_id', 'in', ing_ids),
                   ('date', '>=', d0.isoformat()), ('date', '<=', d1.isoformat())],
                  ['balance:sum'], [])
    vc = -float(rows[0].get('balance') or 0.0) if rows else 0.0
    pos = o.call('pos.order', 'read_group',
                 [('state', 'in', ['paid', 'done', 'invoiced']),
                  ('date_order', '>=', d0.isoformat() + ' 00:00:00'),
                  ('date_order', '<=', d1.isoformat() + ' 23:59:59')],
                 ['amount_total:sum'], [])
    pb = float(pos[0].get('amount_total') or 0.0) if pos else 0.0
    nt = o.call('pos.order', 'search_count',
                [('state', 'in', ['paid', 'done', 'invoiced']),
                 ('date_order', '>=', d0.isoformat() + ' 00:00:00'),
                 ('date_order', '<=', d1.isoformat() + ' 23:59:59')])
    pn = pb / 1.19
    dif = ('%.1f' % (100.0 * (vc - pn) / pn)).replace('.', ',') + '%' if pn else 'n/a'
    print('%s | %s | %s | %s | %s | %s'
          % (pad_r('%s-2026' % MES[m], 9), pad_l(fmt_money(vc), 16), pad_l(fmt_money(pb), 16),
             pad_l(fmt_money(pn), 15), pad_l(dif, 8), pad_l(str(nt), 12)))
