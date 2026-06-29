"""
CALCULO read-only: cuantos DIAS de cobertura son razonables para el piso,
segun la demanda real y el ciclo de reposicion (x_analisis_de_stock).
Universo: AX de heladera (cerveza+gaseosa), salas (excl CD/web).
Compara, para d=1..4 dias: piso_unidades = d * demanda_diaria, contra:
  - piso fisico observado (1 pack: lata6/vidrio4/pet3)
  - ciclo de reposicion real (periodo_repos_weeks)
"""
import sys, statistics as st
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

odoo = OdooReader()
SALAS = [5,6,7,8,9,10,11,12,13,16,17,18]
BEB_CATS = [1621, 1614]
PISO_FMT = {'lata':6, 'vidrio':4, 'pet':3, 'sin_formato':3}
beb_ids = set(odoo.execute('product.category','search',[('id','child_of',BEB_CATS)]))

ax = odoo.search_read('x_analisis_de_stock',
    [('x_studio_abcxyz','=','AX'), ('x_studio_team_id','in',SALAS)],
    ['x_studio_product_id','x_studio_demanda_semanal','x_studio_periodo_repos_weeks',
     'x_studio_lead_weeks'])

tids = list({r['x_studio_product_id'][0] for r in ax if r['x_studio_product_id']})
tinfo = {}
for i in range(0, len(tids), 500):
    for t in odoo.search_read('product.template',[('id','in',tids[i:i+500])],
                              ['categ_id','x_studio_formato']):
        tinfo[t['id']] = t

# filtra a bebidas frias
beb = []
for r in ax:
    if not r['x_studio_product_id']:
        continue
    tid = r['x_studio_product_id'][0]
    cat = (tinfo.get(tid,{}).get('categ_id') or [0])[0]
    if cat in beb_ids:
        r['_fmt'] = tinfo.get(tid,{}).get('x_studio_formato') or 'sin_formato'
        beb.append(r)

dem_sem = [r['x_studio_demanda_semanal'] or 0 for r in beb]
dem_dia = [d/7 for d in dem_sem]
repos = [r['x_studio_periodo_repos_weeks'] or 0 for r in beb if r.get('x_studio_periodo_repos_weeks')]
lead = [r['x_studio_lead_weeks'] or 0 for r in beb]

print(f"AX bebidas (cerveza+gaseosa) x sala: {len(beb)} filas")
print(f"\n== demanda diaria (uds/dia) ==")
q = st.quantiles(dem_dia, n=4)
print(f"  p25={q[0]:.1f}  mediana={st.median(dem_dia):.1f}  p75={q[2]:.1f}  max={max(dem_dia):.0f}")
print(f"\n== ciclo de reposicion (periodo_repos_weeks -> dias) ==")
if repos:
    print(f"  mediana={st.median(repos)*7:.0f} dias  p25={st.quantiles(repos,n=4)[0]*7:.0f}  p75={st.quantiles(repos,n=4)[2]*7:.0f}")
print(f"  lead mediana={st.median(lead)*7:.1f} dias")

print(f"\n== piso por dias vs piso fisico (1 pack). 'manda' = cual gana el max ==")
print(f"{'dias':>4} {'piso_med_u':>11} {'piso_p75_u':>11} {'%manda_dias':>12} {'%manda_fisico':>14}")
for d in [1,2,3,4]:
    pisos = [d*(r['x_studio_demanda_semanal'] or 0)/7 for r in beb]
    manda_dias = sum(1 for r in beb
                     if d*(r['x_studio_demanda_semanal'] or 0)/7 >= PISO_FMT[r['_fmt']])
    pct_dias = 100*manda_dias/len(beb)
    print(f"{d:>4} {st.median(pisos):>11.1f} {st.quantiles(pisos,n=4)[2]:>11.1f} "
          f"{pct_dias:>11.0f}% {100-pct_dias:>13.0f}%")

print("\nLectura: '%manda_dias' = en cuantos SKU el piso por dias supera al piso fisico")
print("(donde manda demanda). Si es bajo, casi todo queda en el piso fisico de 1 pack.")
