"""
Sondeo de los modelos Studio que el harness va a snapshot-ear.
Sin pull pesado: solo fields_get + search_count.
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader


def probe(odoo, model):
    print(f"\n{'='*70}")
    print(f"Model: {model}")
    print(f"{'='*70}")
    try:
        cnt = odoo.search_count(model, [])
        print(f"  Filas totales: {cnt:,}")
    except Exception as e:
        print(f"  ERROR search_count: {e}")
        return

    try:
        f = odoo.fields_get(model)
    except Exception as e:
        print(f"  ERROR fields_get: {e}")
        return

    # Filtrar campos relevantes (no audit, no computed obvio)
    skip_prefix = ('create_', 'write_', '__last', 'message_', 'activity_', 'access_')
    keys = sorted(k for k in f.keys() if not k.startswith(skip_prefix))
    print(f"  Campos ({len(keys)}):")
    for k in keys:
        spec = f[k]
        t = spec.get('type', '?')
        rel = spec.get('relation', '')
        store = spec.get('store', True)
        marker = ' [computed-not-stored]' if not store else ''
        print(f"    {k:42s} {t:12s} {rel:30s}{marker}")


def main():
    odoo = OdooReader()
    print(f"Conectado: {odoo}")

    for m in (
        'x_calculo_abc_xyz',
        'x_price_coreccion',
        'x_demanda_normalizada',
        'x_hm_si_forecast',
        'crm.team',
        'pos.config',
    ):
        probe(odoo, m)


if __name__ == "__main__":
    main()
