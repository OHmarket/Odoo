"""
Verifica que los 5 SKUs que estaban en categ_id=1721 (Cervezas Promocion)
fueron migrados a su categoria correcta.
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

SKUS_MIGRADOS = ['9413', '9958', '1726', '9430', '9407']
DESTINO_ESPERADO = {
    '9413': 1625,  # Tradicionales
    '9958': 1625,
    '1726': 1625,
    '9430': 1625,
    '9407': 1624,  # Premium
}


def main():
    odoo = OdooReader()
    print(f"Conectado: {odoo}")

    # 1. Cuantos quedan en Cervezas Promocion (1721)?
    rest_promo = odoo.search_read(
        'product.template',
        domain=[('categ_id', '=', 1721), ('active', '=', True)],
        fields=['id', 'name', 'default_code'],
    )
    print(f"\n=== SKUs aun en Cervezas Promocion (1721): {len(rest_promo)} ===")
    for s in rest_promo:
        print(f"  tmpl={s['id']:>5} code={s['default_code']!r:<10} {s['name']}")

    # 2. Estado actual de los 5 SKUs migrados
    print("\n=== Estado actual de los 5 SKUs ===")
    skus = odoo.search_read(
        'product.template',
        domain=[('default_code', 'in', SKUS_MIGRADOS), ('active', '=', True)],
        fields=['id', 'name', 'default_code', 'categ_id'],
    )
    for s in skus:
        cat_id = s['categ_id'][0] if isinstance(s['categ_id'], (list, tuple)) else s['categ_id']
        cat_name = s['categ_id'][1] if isinstance(s['categ_id'], (list, tuple)) else ''
        esperado = DESTINO_ESPERADO.get(s['default_code'])
        ok = '✓' if cat_id == esperado else ('×' if esperado else '?')
        print(f"  {ok}  code={s['default_code']!r:<10} categ_id={cat_id:>5} ({cat_name})  esperado={esperado}")


if __name__ == "__main__":
    main()
