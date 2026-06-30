# Read-only: estima impacto del lote de cola larga sobre las filas SALA solo_bodega.
# Lee x_analisis_de_stock vigente (mu, moq, stock, target actual) y proyecta el nuevo
# lote/cadencia. NO escribe. Correr: python proyectos/2026-06-30-cola-larga-lote-caja/diag_cola_larga_impacto.py
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from shared.odoo_xmlrpc import OdooReader  # cliente read-only del repo

UMBRAL, OBJ, PAGO, PISO = 3.0, 30.0, 45.0, 1.0

def _safe_float(v, d=0.0):
    try: return float(v)
    except (TypeError, ValueError): return d

def _calc_cola_larga_lote(mu_week, moq, lead_weeks, objetivo_dias, plazo_pago_dias, piso_units):
    mu  = max(_safe_float(mu_week, 0.0), 0.0); moq = max(_safe_float(moq, 1.0), 1.0)
    piso = max(_safe_float(piso_units, 1.0), 1.0)
    if mu <= 0.0: return 0.0, 0.0
    if (moq / mu) * 7.0 <= max(_safe_float(plazo_pago_dias, 45.0), 1.0):
        S = moq
    else:
        S = max(float(int(mu * (max(_safe_float(objetivo_dias, 30.0), 1.0) / 7.0))), piso)
    return S, mu * max(_safe_float(lead_weeks, 0.0), 0.0) + piso

def run():
    cli = OdooReader()
    # Campos minimos; ajustar nombres x_studio_* si difieren (verificar via ir.model.fields).
    fields = ['x_studio_mu_week', 'x_studio_moq', 'x_studio_stock_proyectado',
              'x_studio_target_units', 'x_studio_solo_bodega', 'x_studio_lead_weeks']
    rows = cli.search_read('x_analisis_de_stock',
                           domain=[['x_studio_solo_bodega', '=', True]], fields=fields, limit=20000)
    gated = caja = frac = 0
    for r in rows:
        mu = _safe_float(r.get('x_studio_mu_week'))
        if not (0.0 < mu <= UMBRAL):
            continue
        gated += 1
        moq = _safe_float(r.get('x_studio_moq'), 1.0)
        S, rop = _calc_cola_larga_lote(mu, moq, 0.0, OBJ, PAGO, PISO)
        es_caja = ((moq / mu) * 7.0) <= PAGO
        caja += 1 if es_caja else 0
        frac += 0 if es_caja else 1
        cadencia_dias = (S / mu) * 7.0 if mu > 0 else 0.0
        if gated <= 25:
            print('mu=%.2f moq=%.0f | S=%.1f rop=%.1f | %s | cad~%.0fd | target_hoy=%.1f'
                  % (mu, moq, S, rop, 'CAJA' if es_caja else 'FRAC',
                     cadencia_dias, _safe_float(r.get('x_studio_target_units'))))
    print('\n--- gated=%d | caja_entera=%d | fraccion=%d ---' % (gated, caja, frac))

if __name__ == '__main__':
    run()
