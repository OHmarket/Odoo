"""Lista campos x_studio_* del modelo x_pos_week_sku_sale."""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader


def main():
    odoo = OdooReader()
    f = odoo.fields_get('x_pos_week_sku_sale')
    keys = sorted(k for k in f.keys() if k.startswith('x_'))
    print(f"Campos x_* en x_pos_week_sku_sale ({len(keys)}):")
    for k in keys:
        t = f[k].get('type', '?')
        print(f"  {k:42s} {t}")

    # Verificar especificamente
    print("\nVerificacion campos clave para backfill_chunked:")
    for k in ('x_studio_source_version', 'x_studio_calendar_version', 'x_studio_has_combo_explosion'):
        exists = k in f
        print(f"  {k}: {'OK' if exists else 'NO EXISTE'}")


if __name__ == "__main__":
    main()
