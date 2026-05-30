"""
DIAGNOSTICO de por que la capa bias-outlier marco 0 — read-only via XML-RPC.

Separa las hipotesis (sin re-deployar el Server Action):
  H1  -> faltan los 4 campos Studio en x_hm_si_forecast
  H2  -> los campos existen y hay filas, pero el SA marco 0
         => el SELECT raw del SA no vio las filas recien creadas (flush ORM)
  H4  -> columnas del stockout mal nombradas (descarta exception)

Corre: python diag_bias_outlier.py
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

FWD = 'x_hm_si_forecast'
STOCK = 'x_stock_balance_daily'
REQ_FWD = ['x_studio_bias_outlier', 'x_studio_bias_outlier_factor',
           'x_studio_bias_outlier_delta', 'x_studio_mu_week_pre_bias_outlier']
REQ_STOCK = ['x_studio_stockout', 'x_studio_stockout_partial',
             'x_studio_qty_balance', 'x_studio_product_id',
             'x_studio_team_id', 'x_studio_date']


def _fields(odoo, model):
    try:
        fg = odoo.fields_get(model)
        if isinstance(fg, dict):
            return set(fg.keys())
    except Exception as e:
        print('  (no pude fields_get %s: %s)' % (model, e))
    return set()


def main():
    odoo = OdooReader()
    print('Conectado: %s\n' % odoo)

    # --- 1. Campos Studio en x_hm_si_forecast (H1) ---
    print('=== 1. Campos bias-outlier en %s ===' % FWD)
    fwd_fields = _fields(odoo, FWD)
    missing_fwd = [f for f in REQ_FWD if f not in fwd_fields]
    for f in REQ_FWD:
        print('  %s %s' % ('OK  ' if f in fwd_fields else 'FALTA', f))
    h1 = bool(missing_fwd)

    # --- 2. Columnas del stockout (H4) ---
    print('\n=== 2. Campos en %s ===' % STOCK)
    stock_fields = _fields(odoo, STOCK)
    missing_stock = [f for f in REQ_STOCK if f not in stock_fields]
    for f in REQ_STOCK:
        print('  %s %s' % ('OK  ' if f in stock_fields else 'FALTA', f))

    # --- 3. Filas del forecast: semana mas reciente y conteo ---
    print('\n=== 3. Filas en %s ===' % FWD)
    latest = None
    try:
        rows = odoo.search_read(FWD, domain=[], fields=['x_studio_week_start'],
                                limit=1, order='x_studio_week_start desc')
        latest = rows[0]['x_studio_week_start'] if rows else None
    except Exception as e:
        print('  (error leyendo week_start: %s)' % e)
    print('  semana mas reciente (target_date esperado): %s' % latest)
    n_week = 0
    if latest:
        try:
            n_week = odoo.search_count(FWD, [('x_studio_week_start', '=', latest)])
        except Exception as e:
            print('  (error contando: %s)' % e)
    print('  filas en esa semana: %s' % n_week)

    # --- 4. Cuantas marcadas bias_outlier=True ---
    n_marked = None
    if 'x_studio_bias_outlier' in fwd_fields:
        try:
            n_marked = odoo.search_count(FWD, [('x_studio_bias_outlier', '=', True)])
        except Exception as e:
            print('  (error contando marcadas: %s)' % e)
    print('  filas marcadas bias_outlier=True: %s' % n_marked)

    # --- 5. Filas de stock para esas semanas (sanity para el cruce) ---
    n_stock = None
    if latest and not missing_stock:
        try:
            # ~3 semanas antes del target
            import datetime
            d = latest if isinstance(latest, str) else str(latest)
            n_stock = odoo.search_count(STOCK, [('x_studio_date', '>=',
                                                 '2026-05-01'),
                                                ('x_studio_date', '<=', d)])
        except Exception as e:
            print('  (error contando stock: %s)' % e)
    print('  filas en %s (mayo): %s' % (STOCK, n_stock))

    # --- VEREDICTO ---
    print('\n=== VEREDICTO ===')
    if h1:
        print('  -> H1 CONFIRMADA: faltan campos %s' % ', '.join(missing_fwd))
        print('     Crear esos campos en Studio y volver a correr el motor.')
    elif missing_stock:
        print('  -> H4: faltan columnas en %s: %s' % (STOCK, ', '.join(missing_stock)))
        print('     El SELECT de quiebre tira exception -> capa marca 0.')
    elif n_week and (not n_marked):
        print('  -> H2 CONFIRMADA: campos OK + %s filas en la semana, pero 0 marcadas.' % n_week)
        print('     Las filas EXISTEN post-commit, asi que el SELECT raw del SA no las')
        print('     vio dentro de la transaccion => falta flush (env.flush_all()) antes')
        print('     de leer x_hm_si_forecast en _bias_outlier_layer. Ese es el fix.')
    elif not n_week:
        print('  -> No hay filas en el forecast. Revisar que el motor escribio (created>0).')
    else:
        print('  -> Inconcluso: %s marcadas. Revisar log del SA (skip/error/outliers=0).' % n_marked)

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
