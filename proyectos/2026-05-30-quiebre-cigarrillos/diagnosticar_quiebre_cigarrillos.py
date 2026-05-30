#!/usr/bin/env python3
"""
Diagnosticar: ¿por qué cigarrillos no se filtran por quiebre en bias-outlier?

Buscar cigarrillos en x_stock_balance_daily y ver si hay quiebre registrado.
"""

from datetime import datetime, timedelta
from shared.odoo_xmlrpc import OdooReader


def main():
    print("=" * 80)
    print("DIAGNOSTICO: QUIEBRE DE CIGARRILLOS EN x_stock_balance_daily")
    print("=" * 80)

    odoo = OdooReader()
    print(f"\n[OK] Conectado a Odoo")

    # Buscar SKU de cigarrillos (asume que contiene "cigarrillo" en el nombre)
    print("\n[1] Buscando SKUs de cigarrillos...")
    cigarro_skus = odoo.search_read('product.product',
                                     domain=[('name', 'ilike', 'cigarrillo')],
                                     fields=['id', 'name'],
                                     limit=20)

    if not cigarro_skus:
        print("[WARN] No encontre SKUs con 'cigarrillo' en el nombre.")
        print("    Intenta buscar por otro nombre (e.g., 'tabaco', 'marlboro', etc.)")
        return

    print(f"[OK] Encontrados {len(cigarro_skus)} SKUs:")
    for s in cigarro_skus:
        print(f"    - SKU {s['id']}: {s['name'][:70]}")

    # Obtener semana mas reciente en stock_balance
    print("\n[2] Buscando semana mas reciente en x_stock_balance_daily...")
    recent = odoo.search_read('x_stock_balance_daily',
                               fields=['x_studio_date'],
                               limit=1,
                               order='x_studio_date desc')
    if not recent:
        print("[WARN] No hay datos en x_stock_balance_daily")
        return

    recent_date = str(recent[0]['x_studio_date'])
    print(f"[OK] Fecha mas reciente: {recent_date}")

    # Ventana de 3 semanas atras
    from datetime import datetime, timedelta
    dt = datetime.strptime(recent_date, '%Y-%m-%d').date()
    window_start = dt - timedelta(weeks=3)

    print(f"    Ventana: {window_start} -> {dt}")

    # Revisar registros de cigarrillos en stock_balance
    print("\n[3] Buscando registros de cigarrillos en x_stock_balance_daily...")
    sku_ids = [s['id'] for s in cigarro_skus]

    domain = [
        ('x_studio_product_id', 'in', sku_ids),
        ('x_studio_date', '>=', str(window_start)),
        ('x_studio_date', '<=', recent_date),
    ]

    stock_recs = odoo.search_read('x_stock_balance_daily',
                                   domain=domain,
                                   fields=[
                                       'id',
                                       'x_studio_product_id',
                                       'x_studio_team_id',
                                       'x_studio_date',
                                       'x_studio_stockout',
                                       'x_studio_stockout_partial',
                                       'x_studio_qty_balance',
                                   ],
                                   limit=100)

    if not stock_recs:
        print("[WARN] No hay registros en x_stock_balance_daily para cigarrillos!")
        print("    -> Esto es el problema: sin registro, bias-outlier NO detecta quiebre")
        return

    print(f"[OK] Encontrados {len(stock_recs)} registros")

    # Analizar quiebre
    print("\n[4] Analizando quiebre registrado...")
    quiebre_count = 0
    stockout_true = 0
    stockout_partial_true = 0
    qty_balance_le_0 = 0

    for r in stock_recs:
        so = r.get('x_studio_stockout')
        sop = r.get('x_studio_stockout_partial')
        qb = r.get('x_studio_qty_balance')

        if bool(so) or bool(sop) or (qb and float(qb) <= 0):
            quiebre_count += 1
            if bool(so):
                stockout_true += 1
            if bool(sop):
                stockout_partial_true += 1
            if qb and float(qb) <= 0:
                qty_balance_le_0 += 1

    print(f"   Total registros: {len(stock_recs)}")
    print(f"   Con quiebre detectado: {quiebre_count} ({100*quiebre_count/len(stock_recs):.1f}%)")
    print(f"     - x_studio_stockout=TRUE: {stockout_true}")
    print(f"     - x_studio_stockout_partial=TRUE: {stockout_partial_true}")
    print(f"     - x_studio_qty_balance<=0: {qty_balance_le_0}")

    if quiebre_count == 0:
        print("\n[ERROR] CIGARRILLOS NO TIENEN QUIEBRE REGISTRADO")
        print("        Los campos de quiebre estan NULL o FALSE")
        print("        -> bias-outlier NO puede filtrarlos")
        print("\n[FIX] Revisa:")
        print("  - ¿x_stock_balance_daily se calcula para cigarrillos?")
        print("  - ¿El cron que detecta quiebre marca estos SKUs?")
        print("  - ¿Los campos x_studio_stockout estan mapeados en Studio?")
    else:
        print(f"\n[OK] Cigarrillos TIENEN quiebre registrado")
        print("     La capa bias-outlier DEBERIA filtrarlos")
        print("     Si no los filtra, revisar:")
        print("     - ¿La query de quiebre en bias_outlier_layer falla?")
        print("     - ¿El window de 3 semanas es muy corto?")

    # Muestra sample
    print("\n[5] Sample de registros:")
    for i, r in enumerate(stock_recs[:5]):
        pid = r.get('x_studio_product_id', [None, 'N/A'])[1] if isinstance(r.get('x_studio_product_id'), (list, tuple)) else r.get('x_studio_product_id')
        tid = r.get('x_studio_team_id', [None, 'N/A'])[1] if isinstance(r.get('x_studio_team_id'), (list, tuple)) else r.get('x_studio_team_id')
        so = r.get('x_studio_stockout')
        sop = r.get('x_studio_stockout_partial')
        qb = r.get('x_studio_qty_balance')
        dt = r.get('x_studio_date')
        print(f"   {i+1}. SKU={pid} TEAM={tid} DATE={dt}")
        print(f"      stockout={so} stockout_partial={sop} qty_balance={qb}")


if __name__ == '__main__':
    main()
