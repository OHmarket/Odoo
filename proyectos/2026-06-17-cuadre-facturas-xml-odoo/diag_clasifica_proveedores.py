"""DIAG read-only CHUNKED: clasifica proveedores por comportamiento historico.
Para cada proveedor: cuenta contable dominante de sus lineas, % de lineas con SKU,
tipo sugerido (mercaderia si dominante=210230, servicio si no) y codigo/desc de flete.

Gentil con produccion: read_group (agregado server-side) + chunks por proveedor.
Ventana 2025+ (representativa). Salida: resultados/clasificacion_proveedores.csv (es-CL)."""
from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader  # noqa: E402

VENTANA = '2025-01-01'
CHUNK = 40
OUT = Path(__file__).resolve().parent / 'resultados'
FLETE_TERMS = ['flete', 'transport', 'despacho', 'reparto', 'acarreo']


def _chunks(seq, n):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def main():
    o = OdooReader()
    base_move = [('move_type', '=', 'in_invoice'), ('invoice_date', '>=', VENTANA)]

    # 1) proveedores con facturas (agregado, barato)
    sup = o.execute('account.move', 'read_group', base_move,
                    ['amount_total:sum'], ['partner_id'], lazy=False)
    proveedores = {r['partner_id'][0]: {'nombre': r['partner_id'][1],
                                        'n_facturas': r['__count']}
                   for r in sup if r['partner_id']}
    pids = list(proveedores)
    print(f"proveedores 2025+: {len(pids)}")

    # 2) vat por proveedor (chunked)
    for ch in _chunks(pids, CHUNK):
        for p in o.search_read('res.partner', [('id', 'in', ch)], ['vat']):
            proveedores[p['id']]['vat'] = p.get('vat') or ''

    # 3) por chunk: distribucion de cuenta y conteo con/sin SKU (read_group)
    acc_dist = defaultdict(lambda: defaultdict(int))  # pid -> {cuenta_label: n}
    con_sku = defaultdict(int)
    tot_lin = defaultdict(int)
    lprod = [('display_type', '=', 'product')]
    for i, ch in enumerate(_chunks(pids, CHUNK), 1):
        dom = base_move + lprod + [('partner_id', 'in', ch)]
        # (partner, cuenta) -> count
        for r in o.execute('account.move.line', 'read_group', dom,
                           ['balance:sum'], ['partner_id', 'account_id'], lazy=False):
            if not r['partner_id']:
                continue
            pid = r['partner_id'][0]
            lab = r['account_id'][1] if r['account_id'] else 'SIN CUENTA'
            acc_dist[pid][lab] += r['__count']
            tot_lin[pid] += r['__count']
        # con product_id
        for r in o.execute('account.move.line', 'read_group',
                           dom + [('product_id', '!=', False)],
                           ['balance:sum'], ['partner_id'], lazy=False):
            if r['partner_id']:
                con_sku[r['partner_id'][0]] += r['__count']
        print(f"  chunk {i}: {len(ch)} proveedores procesados")

    # 4) flete por proveedor (1 query acotada: solo lineas-flete en 210230 sin SKU)
    flete_dom = (base_move + lprod +
                 [('account_id.code', '=', '210230'), ('product_id', '=', False)])
    flete_or = ['|'] * (len(FLETE_TERMS) - 1) + \
               [('name', 'ilike', t) for t in FLETE_TERMS]
    flete_rows = o.search_read('account.move.line', flete_dom + flete_or,
                               ['partner_id', 'name'], limit=5000)
    flete_by_p = defaultdict(set)
    for r in flete_rows:
        if r['partner_id']:
            flete_by_p[r['partner_id'][0]].add((r['name'] or '').strip())
    print(f"  lineas-flete detectadas: {len(flete_rows)}")

    # 5) armar tabla
    filas = []
    for pid, info in proveedores.items():
        dist = acc_dist.get(pid, {})
        dom_cta, dom_n = ('', 0)
        if dist:
            dom_cta, dom_n = max(dist.items(), key=lambda kv: kv[1])
        total = tot_lin.get(pid, 0)
        share = (dom_n / total) if total else 0
        pct_sku = (con_sku.get(pid, 0) / total) if total else 0
        es_merc = dom_cta.startswith('210230')
        flete = ' | '.join(sorted(flete_by_p.get(pid, ()))) if pid in flete_by_p else ''
        filas.append({
            'proveedor_id': pid,
            'proveedor': info['nombre'],
            'vat': info.get('vat', ''),
            'n_facturas': info['n_facturas'],
            'n_lineas': total,
            'tipo_sugerido': 'mercaderia' if es_merc else 'servicio',
            'cuenta_registro': dom_cta,
            'share_cuenta': round(share, 2),
            'pct_lineas_con_sku': round(pct_sku, 2),
            'codigo_flete': flete,
        })

    filas.sort(key=lambda r: -r['n_facturas'])
    OUT.mkdir(exist_ok=True)
    cols = ['proveedor_id', 'proveedor', 'vat', 'n_facturas', 'n_lineas',
            'tipo_sugerido', 'cuenta_registro', 'share_cuenta',
            'pct_lineas_con_sku', 'codigo_flete']
    with open(OUT / 'clasificacion_proveedores.csv', 'w', newline='',
              encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=cols, delimiter=';')
        w.writeheader()
        for r in filas:
            w.writerow(r)

    merc = sum(r['tipo_sugerido'] == 'mercaderia' for r in filas)
    print(f"\nmercaderia: {merc} | servicio: {len(filas) - merc}")
    print("con codigo_flete:", sum(1 for r in filas if r['codigo_flete']))
    print("\n-- top 12 por n_facturas --")
    for r in filas[:12]:
        print(f"  {r['proveedor'][:34]:34} {r['tipo_sugerido']:10} "
              f"cta={r['cuenta_registro'][:28]:28} sku={r['pct_lineas_con_sku']:.0%} "
              f"flete={'si' if r['codigo_flete'] else '-'}")


if __name__ == '__main__':
    main()
