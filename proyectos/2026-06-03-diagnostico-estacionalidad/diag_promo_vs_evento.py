# -*- coding: utf-8 -*-
"""DIAG read-only: los 4 candidatos SKU-evento sospechosos (Ballantines,
Lays, RedBull Summer, Castillo de Molina) tuvieron PROMO en la semana que
el detector atribuye al evento? Cruce contra x_loyalty_promo_event."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

odoo = OdooReader()
pp = odoo.search_read(
    'product.product',
    domain=['|', '|', '|',
            ('name', 'ilike', 'ballantines'),
            ('name', 'ilike', 'lays corte americano'),
            ('name', 'ilike', 'redbull summer'),
            ('name', 'ilike', 'castillo de molina gran reserva sauvignon')],
    fields=['name'])
print('productos matcheados: %d' % len(pp))
for p in pp:
    print('  %s %s' % (p['id'], p['name'][:70]))

ev = odoo.search_read(
    'x_loyalty_promo_event',
    domain=[('x_studio_product_variant_id', 'in', [p['id'] for p in pp])],
    fields=['x_studio_product_variant_id', 'x_studio_period_start',
            'x_studio_date_from', 'x_studio_weeks_active',
            'x_studio_lift_qty', 'x_studio_program_name'])
print('\neventos promo: %d' % len(ev))
for e in sorted(ev, key=lambda x: str(x.get('x_studio_period_start'))):
    nm = e['x_studio_product_variant_id'][1] if e['x_studio_product_variant_id'] else '?'
    print('%-12s sem_activas=%-4s lift=%-10s %-28s %s' % (
        e.get('x_studio_period_start'), e.get('x_studio_weeks_active'),
        e.get('x_studio_lift_qty'),
        (e.get('x_studio_program_name') or '')[:28], nm[:55]))
