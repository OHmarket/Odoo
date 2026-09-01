"""test_report_smoke — corre main() completo contra un Odoo FALSO.

No toca Odoo real: valida el plumbing (domains, parseo de read_group, armado
del reporte) con data sintetica de uplift conocido, antes de gastar queries
contra produccion.

    python proyectos/2026-09-01-crecimiento-compras-embonor/test_report_smoke.py
"""

from __future__ import annotations

import datetime
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import diag_embonor_uplift as diag  # noqa: E402

UPLIFT = 1.60          # indice sembrado en la data falsa
PRE_FILL = 1.25        # llenado en la semana previa
BASE_SELLIN = 13_000_000.0
BASE_UNITS = 9_000.0
TEAMS = [5, 6, 7]


def _week_factor(ws):
    """Factor sintetico: peak en la semana del 18-sep de cada ano."""
    for year in (2024, 2025, 2026):
        we = diag.event_week_start(year)
        if ws == we:
            return UPLIFT
        if ws == diag.week_offset(we, -1):
            return PRE_FILL
        if ws == diag.week_offset(we, 1):
            return 0.80
    return 1.0


class FakeOdoo:
    """Implementa solo lo que usa el diag: read-only y sin red."""

    def fields_get(self, model, attributes=None):
        if model == 'product.template':
            return {diag.PROV_FIELD: {'string': 'Proveedor Compra'}}
        if model == 'account.move':
            return {'amount_untaxed_signed': {'string': 'Neto con signo'}}
        return {}

    def search_count(self, model, domain=None):
        return 1200

    def search_read(self, model, domain=None, fields=None, limit=None, offset=0, order=None):
        if model == 'res.partner':
            return [{'id': 41, 'name': 'COCA COLA EMBONOR S.A.', 'parent_id': False}]
        if model == 'product.template':
            return [{'id': i} for i in range(100, 140)]
        if model == 'product.supplierinfo':
            return [{'product_tmpl_id': [i, 'p%s' % i], 'product_id': False} for i in range(100, 140)]
        if model == 'product.product':
            return [{'id': i + 1000} for i in range(100, 140)]
        if model == 'account.move':
            return self._invoices()
        raise AssertionError('modelo inesperado en search_read: %s' % model)

    def execute(self, model, method, *args, **kwargs):
        assert model == diag.SALE_MODEL and method == 'read_group', (model, method)
        return self._sellout_groups()

    # --- data sintetica -------------------------------------------------
    def _weeks(self):
        ws = diag.oh_week_start(datetime.date.fromisoformat(diag.DATE_FROM))
        end = diag.week_offset(diag.event_week_start(diag.TARGET_YEAR), -1)
        out = []
        while ws <= end:
            out.append(ws)
            ws = diag.week_offset(ws, 1)
        return out

    def _invoices(self):
        rows = []
        for i, ws in enumerate(self._weeks()):
            # dos facturas por semana + una nota de credito chica
            amount = BASE_SELLIN * _week_factor(ws) / 2.0
            for day in (1, 3):
                rows.append({
                    'invoice_date': (ws + datetime.timedelta(days=day)).isoformat(),
                    'move_type': 'in_invoice',
                    'amount_untaxed_signed': amount,
                })
            rows.append({
                'invoice_date': (ws + datetime.timedelta(days=4)).isoformat(),
                'move_type': 'in_refund',
                'amount_untaxed_signed': -50_000.0,
            })
        return rows

    def _sellout_groups(self):
        gkey = 'x_studio_week_start:day'
        rows = []
        for ws in self._weeks():
            for team in TEAMS:
                units = BASE_UNITS * _week_factor(ws) / len(TEAMS)
                rows.append({
                    gkey: ws.strftime('%d %b %Y'),          # label locale-dependiente
                    '__range': {gkey: {'from': ws.isoformat(), 'to': diag.week_offset(ws, 1).isoformat()}},
                    'x_studio_team_id': [team, 'Sala %s' % team],
                    'x_studio_qty_sold': units,
                    'x_studio_sales_gross': units * 1200.0,
                    '__count': 40,
                })
        return rows


# El diag importa OdooReader adentro de main(); se intercepta el modulo.
class _FakeModule:
    OdooReader = FakeOdoo


sys.modules['shared.odoo_xmlrpc'] = _FakeModule  # type: ignore[assignment]

diag.OUT_DIR = Path(__file__).resolve().parent / 'resultados' / '_smoke'
diag.main()

texto = sorted(diag.OUT_DIR.glob('embonor_uplift_*.txt'))[-1].read_text(encoding='utf-8')
fails = []


def check(nombre, cond):
    print('  %-4s %s' % ('OK' if cond else 'FAIL', nombre))
    if not cond:
        fails.append(nombre)


print()
print('Chequeos sobre el reporte generado')
check('recupera el indice sembrado (x1.60) en sell-in', 'indice evento 2025: x1.60' in texto)
check('recupera el indice sembrado (x1.60) en sell-out unidades',
      'indice evento 2025 (unidades): x1.60' in texto)
check('detecta el llenado de la semana previa (x1.25)', 'sem-1 x1.25' in texto)
check('detecta el payback de la semana siguiente (x0.80)', 'sem+1 x0.80' in texto)
check('mide tambien el evento 2024', 'indice evento 2024: x1.60' in texto)
check('semana objetivo correcta', 'Semana objetivo (OH lun-dom): 2026-09-14' in texto)
check('reporta crecimiento vs semana normal', 'crecimiento vs semana normal: +60%' in texto)
check('imprime las advertencias de incertidumbre', 'Reportar como ESTIMACION' in texto)

# La data es sintetica: no dejar el output tirado en resultados/.
for _f in diag.OUT_DIR.glob('embonor_uplift_*.txt'):
    _f.unlink()
diag.OUT_DIR.rmdir()

print()
if fails:
    print('%d TEST(S) FALLARON:' % len(fails))
    for x in fails:
        print('  - %s' % x)
    sys.exit(1)
print('TODOS LOS TESTS PASARON')
