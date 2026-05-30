"""
Para cada uno de los 5 SKUs en Cervezas Promocion (categ_id=1721),
inferir cual era su categoria original mirando hermanos por marca + formato.

Heuristica: extraer marca (primera palabra significativa) + formato (ML/CC/L)
y buscar matches en categorias hermanas.
"""
from __future__ import annotations
import sys
from pathlib import Path
import re
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

pd.set_option("display.width", 240)
pd.set_option("display.max_columns", 20)
pd.set_option("display.max_colwidth", 80)

PROMO_CAT_ID = 1721
SISTER_CAT_IDS = [1622, 1623, 1624, 1626, 1625]  # Artesanales, Importadas, Premium, sin Alcohol, Tradicionales


def _marca(name):
    """Tercera palabra del nombre = marca (ej 'CERVEZA STELLA ARTOIS' -> 'STELLA')."""
    s = str(name or '').upper()
    s = s.replace('CERVEZA', '').strip()
    parts = [p for p in s.split() if p and not p[0].isdigit()]
    return parts[0] if parts else ''


def _formato(name):
    """Extrae primer 'NNN CC' / 'NNN ML' / 'N L' del nombre."""
    s = str(name or '').upper()
    m = re.search(r'(\d+(?:\.\d+)?)\s*(CC|ML|L)\b', s)
    if not m:
        return ''
    return f"{m.group(1)} {m.group(2)}"


def main():
    odoo = OdooReader()
    print(f"Conectado: {odoo}")

    # 1. Los 5 SKUs en Cervezas Promocion
    promo_skus = odoo.search_read(
        'product.template',
        domain=[('categ_id', '=', PROMO_CAT_ID), ('active', '=', True)],
        fields=['id', 'name', 'default_code', 'categ_id'],
        order='name',
    )
    print(f"\n=== {len(promo_skus)} SKUs en Cervezas Promocion ===")
    for s in promo_skus:
        s['marca'] = _marca(s['name'])
        s['formato'] = _formato(s['name'])
        print(f"  tmpl={s['id']:>5} code={s['default_code']!r:<8} marca={s['marca']:<12} fmt={s['formato']:<8} {s['name']}")

    # 2. Pull todos los SKUs hermanos
    hermanos = odoo.search_read(
        'product.template',
        domain=[('categ_id', 'in', SISTER_CAT_IDS), ('active', '=', True)],
        fields=['id', 'name', 'default_code', 'categ_id'],
    )
    print(f"\n=== {len(hermanos)} SKUs en sub-cat hermanas ===")
    df_h = pd.DataFrame(hermanos)
    df_h['categ_id'] = df_h['categ_id'].apply(lambda v: v[1] if isinstance(v, (list, tuple)) else v)
    df_h['marca'] = df_h['name'].apply(_marca)
    df_h['formato'] = df_h['name'].apply(_formato)

    # 3. Para cada SKU promo, encontrar matches por marca + formato
    print("\n========== INFERENCIA DE CATEGORIA ORIGINAL ==========")
    for s in promo_skus:
        marca = s['marca']
        fmt = s['formato']
        print(f"\n--- [{s['default_code']}] {s['name']}  (marca={marca}, fmt={fmt}) ---")

        # Match exacto marca + formato
        m_exact = df_h[(df_h['marca'] == marca) & (df_h['formato'] == fmt)]
        if not m_exact.empty:
            print(f"  Match exacto marca+formato:")
            print(f"  {m_exact[['default_code', 'name', 'categ_id']].to_string(index=False)}")
            # Voto por categoria
            cat_votes = m_exact['categ_id'].value_counts()
            destino = cat_votes.idxmax()
            print(f"  -> destino sugerido: {destino} ({cat_votes[destino]} matches)")
            continue

        # Match solo por marca
        m_marca = df_h[df_h['marca'] == marca]
        if not m_marca.empty:
            print(f"  Match solo por marca ({len(m_marca)} filas):")
            print(f"  {m_marca[['default_code', 'name', 'categ_id']].head(5).to_string(index=False)}")
            cat_votes = m_marca['categ_id'].value_counts()
            destino = cat_votes.idxmax()
            print(f"  -> destino sugerido (por marca): {destino} ({cat_votes[destino]}/{len(m_marca)} matches)")
            continue

        # Match solo por formato
        m_fmt = df_h[df_h['formato'] == fmt] if fmt else pd.DataFrame()
        if not m_fmt.empty:
            cat_votes = m_fmt['categ_id'].value_counts()
            print(f"  Sin match por marca. Por formato ({fmt}): destinos {dict(cat_votes.head(3))}")
            print(f"  -> destino sugerido (formato dominante): {cat_votes.idxmax()}")
            continue

        print("  *** SIN MATCHES - inspeccionar manualmente ***")


if __name__ == "__main__":
    main()
