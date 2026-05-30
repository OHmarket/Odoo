"""
1. Chequear si product.template.categ_id esta trackeado (mail.tracking.value).
2. Si si: listar cambios de categ_id del 9407 y de N SKUs en sub-cat "Cervezas Promocion".
3. Listar sub-categorias hermanas de "Cervezas Promocion" como candidatas
   de destino (camino #2 de inferencia por hermanos).
"""
from __future__ import annotations
import sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

pd.set_option("display.width", 240)
pd.set_option("display.max_columns", 20)
pd.set_option("display.max_colwidth", 80)


def main():
    odoo = OdooReader()
    print(f"Conectado: {odoo}")

    # ----------------------------------------------------------
    # 1. Existe ir.model.fields.tracking activo para product.template.categ_id?
    # ----------------------------------------------------------
    print("\n=== A. Tracking de product.template.categ_id ===")
    field_meta = odoo.search_read(
        'ir.model.fields',
        domain=[('model', '=', 'product.template'), ('name', '=', 'categ_id')],
        fields=['name', 'model', 'tracking', 'ttype', 'relation'],
    )
    if field_meta:
        f = field_meta[0]
        print(f"  field id={f.get('id')} ttype={f.get('ttype')} relation={f.get('relation')}")
        print(f"  tracking={f.get('tracking')}  (None/False = no esta trackeado)")
    else:
        print("  No se encontro definicion del campo")

    # ----------------------------------------------------------
    # 2. Cuantos registros mail.tracking.value existen para product.template?
    # ----------------------------------------------------------
    print("\n=== B. mail.tracking.value para product.template ===")
    try:
        # Filtrar por field name "categ_id" y modelo product.template
        # Schema Odoo 17: mail.tracking.value tiene field_id (m2o ir.model.fields),
        # old_value_integer, new_value_integer, old_value_char, mail_message_id.
        # mail.message tiene model + res_id.
        tv_count = odoo.search_count(
            'mail.tracking.value',
            domain=[
                ('mail_message_id.model', '=', 'product.template'),
                ('field_id.name', '=', 'categ_id'),
            ],
        )
        print(f"  total tracking values categ_id sobre product.template: {tv_count:,}")
    except Exception as e:
        print(f"  ERROR al consultar mail.tracking.value: {e}")
        tv_count = 0

    # ----------------------------------------------------------
    # 3. Si hay tracking: listar cambios para template 11797 (9407)
    # ----------------------------------------------------------
    if tv_count:
        print("\n=== C. Cambios de categ_id para template 11797 (9407 STELLA 660) ===")
        try:
            changes = odoo.search_read(
                'mail.tracking.value',
                domain=[
                    ('mail_message_id.model', '=', 'product.template'),
                    ('mail_message_id.res_id', '=', 11797),
                    ('field_id.name', '=', 'categ_id'),
                ],
                fields=[
                    'create_date', 'mail_message_id',
                    'old_value_integer', 'old_value_char',
                    'new_value_integer', 'new_value_char',
                ],
                order='create_date',
            )
            if changes:
                for c in changes:
                    old_id = c.get('old_value_integer') or 0
                    new_id = c.get('new_value_integer') or 0
                    old_name = c.get('old_value_char') or ''
                    new_name = c.get('new_value_char') or ''
                    print(f"  {c['create_date']}  {old_id:>5} {old_name!r:<60} -> {new_id:>5} {new_name!r}")
            else:
                print("  Sin cambios trackeados para 11797")
        except Exception as e:
            print(f"  ERROR: {e}")

    # ----------------------------------------------------------
    # 4. Sub-categorias hermanas de "Cervezas Promocion" (camino #2)
    # ----------------------------------------------------------
    print("\n=== D. Sub-cat hermanas de 'Cervezas Promocion' (cat padre) ===")
    cervezas_promo = odoo.search_read(
        'product.category',
        domain=[('complete_name', 'ilike', 'Cervezas Promoci')],
        fields=['id', 'name', 'complete_name', 'parent_id'],
    )
    for c in cervezas_promo:
        print(f"  Cervezas Promo: id={c['id']} parent={c['parent_id']}  full={c['complete_name']}")
        parent_id = c['parent_id'][0] if isinstance(c['parent_id'], (list, tuple)) else c['parent_id']
        if parent_id:
            sisters = odoo.search_read(
                'product.category',
                domain=[('parent_id', '=', parent_id)],
                fields=['id', 'name', 'complete_name'],
                order='name',
            )
            print(f"  Hermanas bajo parent {parent_id}:")
            for s in sisters:
                n_skus = odoo.search_count(
                    'product.template',
                    domain=[('categ_id', '=', s['id']), ('active', '=', True)],
                )
                print(f"    id={s['id']:>5}  n_skus_active={n_skus:>4}  {s['complete_name']}")

    # ----------------------------------------------------------
    # 5. Cuantos SKUs hay en TODAS las sub-cat con "Promo" en el nombre?
    # ----------------------------------------------------------
    print("\n=== E. Universo total sub-cat con 'Promo' (alcance migracion) ===")
    promo_cats = odoo.search_read(
        'product.category',
        domain=['|', ('name', 'ilike', 'Promo'), ('complete_name', 'ilike', 'Promo')],
        fields=['id', 'name', 'complete_name'],
        order='complete_name',
    )
    total_skus = 0
    for c in promo_cats:
        n = odoo.search_count(
            'product.template',
            domain=[('categ_id', '=', c['id']), ('active', '=', True)],
        )
        print(f"  id={c['id']:>5}  n_skus={n:>4}  {c['complete_name']}")
        total_skus += n
    print(f"\n  TOTAL SKUs activos en sub-cat 'Promo': {total_skus:,}")


if __name__ == "__main__":
    main()
