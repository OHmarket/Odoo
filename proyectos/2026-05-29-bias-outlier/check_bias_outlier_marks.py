"""
Validacion POST-DEPLOY de la capa bias-outlier (v3.48) — read-only via XML-RPC.

Corre DESPUES de ejecutar el motor HM-SI con apply_bias_outlier=True. Lee las
marcas persistidas en x_hm_si_forecast y reporta:
  - cuantos SKU/filas quedaron marcados
  - top por |delta| (mayor masa de error corregida)
  - chequeo de casos canonicos: Stella (factor>1), Royal Guard (factor<1),
    Cusquena (NO deberia estar marcado: lo limpia el quiebre)

No depende del backtest. No modifica nada.
"""
from __future__ import annotations
import sys
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

CANON = {
    '9407':   ('Stella Artois 660',          '>1'),
    '451500': ('Royal Guard Golden 710',     '<1'),
    '9958':   ('Cusquena Golden 710',        'OUT'),  # debe quedar fuera (quiebre)
}


def main():
    odoo = OdooReader()
    print('Conectado: %s' % odoo)

    rows = odoo.search_read(
        'x_hm_si_forecast',
        domain=[('x_studio_bias_outlier', '=', True)],
        fields=['x_studio_product_id', 'x_studio_team_id', 'x_studio_mu_week',
                'x_studio_mu_week_pre_bias_outlier', 'x_studio_bias_outlier_factor',
                'x_studio_bias_outlier_delta'],
    )
    print('Filas marcadas bias_outlier=True: %s' % len(rows))
    if not rows:
        print('  (nada marcado — revisa que el motor corrio con apply_bias_outlier=True')
        print('   y que los 4 campos Studio existen)')
        return 0

    # Agregar por SKU
    by_sku = defaultdict(lambda: {'rows': 0, 'factor': None, 'delta': None,
                                  'mu': 0.0, 'pre': 0.0})
    for r in rows:
        pid = r['x_studio_product_id']
        pid = pid[0] if isinstance(pid, (list, tuple)) else pid
        name = r['x_studio_product_id'][1] if isinstance(r['x_studio_product_id'], (list, tuple)) else ''
        s = by_sku[(pid, name)]
        s['rows'] += 1
        s['factor'] = r.get('x_studio_bias_outlier_factor')
        s['delta'] = r.get('x_studio_bias_outlier_delta')
        s['mu'] += float(r.get('x_studio_mu_week') or 0.0)
        s['pre'] += float(r.get('x_studio_mu_week_pre_bias_outlier') or 0.0)

    ordered = sorted(by_sku.items(), key=lambda kv: -abs(kv[1]['delta'] or 0.0))
    print('\nSKU marcados: %s' % len(ordered))
    print('%-46s %6s %7s %9s %9s %9s' % ('SKU', 'factor', 'delta', 'mu_pre', 'mu_post', 'rows'))
    for (pid, name), s in ordered[:40]:
        print('%-46s %6.2f %+7.1f %9.1f %9.1f %9d' % (
            (name or str(pid))[:46], s['factor'] or 0.0, s['delta'] or 0.0,
            s['pre'], s['mu'], s['rows']))

    # Chequeo casos canonicos por default_code
    print('\nCasos canonicos:')
    prods = odoo.search_read('product.product',
                             domain=[('default_code', 'in', list(CANON.keys()))],
                             fields=['id', 'default_code'])
    pid_to_code = {p['id']: p['default_code'] for p in prods}
    marked_pids = {pid for (pid, _n) in by_sku.keys()}
    for code, (label, expect) in CANON.items():
        pid = next((p['id'] for p in prods if p['default_code'] == code), None)
        is_marked = pid in marked_pids if pid else False
        factor = None
        if is_marked:
            for (p, _n), s in by_sku.items():
                if p == pid:
                    factor = s['factor']
                    break
        if expect == 'OUT':
            ok = not is_marked
            detail = 'no marcado' if not is_marked else 'MARCADO factor=%.2f (revisar quiebre)' % (factor or 0)
        elif expect == '>1':
            ok = is_marked and (factor or 0) > 1.0
            detail = ('factor=%.2f' % factor) if is_marked else 'NO marcado'
        else:  # '<1'
            ok = is_marked and 0 < (factor or 0) < 1.0
            detail = ('factor=%.2f' % factor) if is_marked else 'NO marcado'
        print('  %s %-26s esperado %-4s -> %s' % (
            'OK  ' if ok else 'FAIL', label, expect, detail))

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
