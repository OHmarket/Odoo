# -*- coding: utf-8 -*-
"""
DIAG read-only: cuanto stock parado libera la politica min/max sobre la
cola larga (u_mes<=4, list_price<=20000). Excedente = on_hand por encima
del order-up-to S. Sensibilidad por meses de cobertura de S.
"""
import pandas as pd, numpy as np

m = pd.read_parquet('proyectos/2026-06-22-cola-larga-minmax/resultados/demanda_stock_join.parquet')

GUARD = 20000
cola = m[(m['u_mes'] <= 4) & (m['list_price'] <= GUARD)].copy()
# costo unitario implicito (parado a costo / unidades on-hand)
cola['unit_cost'] = np.where(cola['stock_u'] > 0,
                             cola['stock_val'] / cola['stock_u'], 0.0)
cola = cola[cola['stock_u'] > 0]  # solo donde hay stock que liberar

u = cola['u_mes'].values            # unidades/mes
oh = cola['stock_u'].values         # on-hand actual (u)
uc = cola['unit_cost'].values
val_now = (oh * uc).sum()

print(f'Cola larga con stock (u_mes<=4, lp<=${GUARD:,}): {len(cola)} pares | '
      f'stock parado ${val_now:,.0f}')
print(f'on-hand medio {oh.mean():.1f} u | meses de cobertura actuales (mediana) '
      f'{np.median(np.where(u>0, oh/u, np.nan)):.1f}')
print()
print('--- Liberacion por cobertura de S (piso S>=2 u) ---')
print(f'{"S meses":>8} | {"S_u medio":>9} | {"pares sobre-S":>13} | {"libera $":>14} | {"% del parado":>12} | {"queda parado $":>15}')
for Smeses in [2, 3, 4, 6]:
    S = np.maximum(np.ceil(u * Smeses), 2)        # order-up-to, piso 2
    excess_u = np.maximum(oh - S, 0)
    libera = (excess_u * uc).sum()
    sobre = (excess_u > 0).sum()
    queda = val_now - libera
    print(f'{Smeses:>8} | {S.mean():>9.1f} | {sobre:>13} | {libera:>13,.0f} | '
          f'{100*libera/val_now:>11.1f}% | {queda:>14,.0f}')

# desglose: cuanto del parado esta en pares que NO venden nada en la ventana
muertos = cola[cola['u_mes'] <= 0.01]
print()
print(f'Sub-cola "muertos" (u_mes~0 pero con stock): {len(muertos)} pares | '
      f'${ (muertos.stock_u*np.where(muertos.stock_u>0, muertos.stock_val/muertos.stock_u,0)).sum():,.0f} '
      f'-> candidatos a liquidacion, no a min/max')
