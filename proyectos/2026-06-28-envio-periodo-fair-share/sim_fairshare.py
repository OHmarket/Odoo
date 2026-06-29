# Test fair-share: cuando el CD no alcanza para la cadena, comparar 3 reglas.
# Algoritmo (no depende de realismo de demanda; valida la matematica del reparto).
# Magnitudes reales: SKU 20907 vende ~253 u/dia en cadena (cache cervezas),
# lo reparto en 6 salas de tamano distinto.
#
# Reglas:
#   greedy        : llena por prioridad hasta S; ultimas salas quedan en 0.
#   proporcional  : cada sala recibe (CD/necesidad_total)*necesidad_i.
#   igualar_cob   : water-filling -> sube a TODAS al mismo nivel de cobertura
#                   (dias de venta) hasta agotar CD. Fair-share DRP (SAP/Oracle).
#
# Metrica que importa: cobertura (dias) post-reparto por sala, y cuantas salas
# se quiebran antes del proximo camion (7d).
import numpy as np, pandas as pd

REVIEW_D = 7      # proximo camion
PERIOD_D = 15
Z = 1.28

# 6 salas: demanda diaria (u/d) y stock actual (u). Suman ~253/d (SKU real).
salas = pd.DataFrame({
    'sala':   ['Panguipulli','Los Lagos','Futrono','Lautaro','Coñaripe','Malalhue'],
    'mu_d':   [70,  55,  45,  35,  28,  20],
    'stock':  [40,  12,  60,   8,  45,   5],   # heterogeneo: algunas ya con stock, otras casi secas
})
salas['sigma_d'] = salas['mu_d']*0.5   # cv 0.5 supuesto
salas['safety']  = (Z*salas['sigma_d']*np.sqrt(REVIEW_D)).round(0)
salas['S']       = (PERIOD_D*salas['mu_d'] + salas['safety']).round(0)   # order-up-to
salas['need']    = (salas['S'] - salas['stock']).clip(lower=0)

NEED_TOTAL = salas['need'].sum()
CD = round(NEED_TOTAL*0.55)   # CD solo cubre 55% de la necesidad -> corto a proposito
print(f"Necesidad total cadena: {NEED_TOTAL:.0f}  |  Stock CD disponible: {CD}  (cubre {CD/NEED_TOTAL*100:.0f}%)\n")

def greedy(s, cd):
    # prioridad = menor cobertura actual primero (sin_stock/critico)
    a = np.zeros(len(s)); rem = cd
    order = (s['stock']/s['mu_d']).sort_values().index
    for i in order:
        give = min(s.loc[i,'need'], rem); a[s.index.get_loc(i)] = give; rem -= give
        if rem<=0: break
    return a

def proporcional(s, cd):
    return (s['need']*cd/s['need'].sum()).values

def igualar_cobertura(s, cd):
    # water-filling: hallar nivel de cobertura c* tal que
    # sum( clip(c**mu - stock, 0, need) ) = cd
    mu=s['mu_d'].values; stock=s['stock'].values; need=s['need'].values
    lo,hi=0.0, (PERIOD_D+50)
    for _ in range(100):
        c=(lo+hi)/2
        alloc=np.clip(c*mu-stock,0,need)
        if alloc.sum()>cd: hi=c
        else: lo=c
    return np.clip(c*mu-stock,0,need)

res = salas[['sala','mu_d','stock','S','need']].copy()
for name,fn in [('greedy',greedy),('proporcional',proporcional),('igualar_cob',igualar_cobertura)]:
    a=fn(salas,CD)
    res[name+'_qty']=np.round(a,0)
    res[name+'_cobd']=np.round((salas['stock'].values+a)/salas['mu_d'].values,1)  # dias cobertura post

print(res.to_string(index=False))
print()
print("Resumen (cobertura en DIAS post-reparto; camion vuelve en 7d):")
for name in ['greedy','proporcional','igualar_cob']:
    cob=res[name+'_cobd'].values
    quiebran=int((cob<REVIEW_D).sum())
    print(f"  {name:14s}: cob_min={cob.min():4.1f}d  cob_max={cob.max():5.1f}d  "
          f"spread={cob.max()-cob.min():4.1f}d  salas<7d(quiebran)={quiebran}")
