# -*- coding: utf-8 -*-
"""DIAG read-only: que categorias tienen factor != 1 en iso week 36 y por que."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

odoo = OdooReader()
rows = odoo.search_read(
    'x_forecast_factor_week',
    domain=[('x_studio_iso_week', '=', 36)],
    fields=['x_studio_categ_id', 'x_studio_week_start', 'x_studio_factor_verano',
            'x_studio_factor_evento', 'x_studio_factor_total'],
)
print('filas iso 36: %d (semana %s)' % (len(rows), rows[0]['x_studio_week_start'] if rows else '-'))
off = [r for r in rows if abs(r['x_studio_factor_total'] - 1.0) > 1e-9]
print('con factor != 1: %d' % len(off))
for r in sorted(off, key=lambda x: -abs(x['x_studio_factor_total'] - 1.0)):
    print('  fv=%.2f fe=%.2f ft=%.2f  %s' % (
        r['x_studio_factor_verano'], r['x_studio_factor_evento'],
        r['x_studio_factor_total'], r['x_studio_categ_id'][1][:55]))
