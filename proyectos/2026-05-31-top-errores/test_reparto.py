"""
Replica local del modelo de reparto (MCI / attraction) sobre el pool de cervezas.
Pregunta clave: ¿el reparto toca a TODA la categoria, o solo a los sustitutos
que de verdad se mueven? -> medir distribucion de factores.

Casos esperados (demanda real): RoyalGuard +30%->-92% (f~0.08), Cristal -17%->+1900% (f~20), Stella 0%->+100% (f~2)
"""
from pathlib import Path
import pandas as pd

CACHE = Path(__file__).resolve().parents[1] / '2026-05-27-harness-local' / 'cache'
EVENT_WEEK = pd.Timestamp('2026-04-13').date()
ELAST_ABC = {'A': 1.30, 'B': 1.00, 'C': 0.70}
NAMES = {18727: 'Budweiser', 28382: 'RoyalGuard', 11797: 'Stella'}


def reparto(share_base, ratios, elast):
    rm = sum(share_base[i] * ratios[i] for i in share_base)
    attr = {i: share_base[i] * (ratios[i] / rm) ** (-elast[i]) for i in share_base}
    tot = sum(attr.values())
    return {i: (attr[i] / tot) / share_base[i] for i in share_base}


def main():
    prod = pd.read_parquet(CACHE / 'catalog_products.parquet')
    cerv_ids = set(prod[prod['categ_complete_name'].astype(str).str.contains('Cerveza', case=False, na=False)]['id'])
    code2id = dict(zip(prod['default_code'].astype(str), prod['id']))
    for code, nm in [('451548', 'Cristal'), ('9430', 'Quilmes'), ('9958', 'Cusquena')]:
        if code in code2id:
            NAMES[int(code2id[code])] = nm

    pos = pd.read_parquet(CACHE / 'pos_weekly.parquet')
    pos['week_start'] = pd.to_datetime(pos['week_start']).dt.date
    cerv = pos[pos['product_id'].isin(cerv_ids)]
    pre = cerv[cerv['week_start'] < EVENT_WEEK]
    post = cerv[cerv['week_start'] >= EVENT_WEEK]
    vol = pre.groupby('product_id')['qty_sold'].sum()
    vol = vol[vol > 0]
    share_base = (vol / vol.sum()).to_dict()
    vol_pre = pre.groupby('product_id')['qty_sold'].mean()
    vol_post = post.groupby('product_id')['qty_sold'].mean()
    print(f'Pool cervezas: {len(share_base)} SKU con venta pre-evento')

    pc = pd.read_parquet(CACHE / 'price_corr.parquet')
    var_map = dict(zip(pc['product_id'], pc['x_studio_var_pct']))
    ratios = {i: 1.0 + float(var_map.get(i, 0.0) or 0.0) for i in share_base}
    n_evt = sum(1 for i in ratios if abs(ratios[i] - 1.0) > 1e-6)
    print(f'SKU con evento de precio propio: {n_evt} de {len(share_base)}')

    abc = pd.read_parquet(CACHE / 'abcxyz.parquet')
    abc_map = {r['product_id']: str(r['x_studio_abc'])[:1].upper() for _, r in abc.iterrows()}

    foco = [k for k in NAMES]
    print()
    for eb in [2.0, 3.0]:
        elast = {i: eb * ELAST_ABC.get(abc_map.get(i, 'B'), 1.0) for i in share_base}
        f = reparto(share_base, ratios, elast)
        neutro = sum(f[i] * vol.get(i, 0) for i in share_base) / vol.sum()
        # distribucion: cuantos se mueven
        movidos_10 = sum(1 for i in f if abs(f[i] - 1.0) > 0.10)
        movidos_25 = sum(1 for i in f if abs(f[i] - 1.0) > 0.25)
        sin_evento_movidos = sum(1 for i in f if abs(ratios[i] - 1.0) < 1e-6 and abs(f[i] - 1.0) > 0.10)
        print(f'=== ELAST_BASE={eb}  (neutralidad={neutro:.3f}) ===')
        print(f'  SKU que se mueven >10%: {movidos_10}/{len(f)} | >25%: {movidos_25}/{len(f)} | sin evento propio pero movidos: {sin_evento_movidos}')
        print(f"  {'SKU':<12} {'var%':>6} {'factor_MCI':>11} {'factor_real':>12}")
        for pid in sorted(foco, key=lambda x: -f.get(x, 0)):
            if pid not in f:
                continue
            vp = (ratios.get(pid, 1.0) - 1.0) * 100
            rf = (vol_post.get(pid, 0) / vol_pre.get(pid, 1)) if vol_pre.get(pid, 0) > 0 else 0
            print(f"  {NAMES.get(pid, str(pid)):<12} {vp:>5.0f}% {f[pid]:>11.3f} {rf:>12.2f}")
        print()


if __name__ == '__main__':
    main()
