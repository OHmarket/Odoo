"""
mapping_worksheet.py — READ-ONLY.

Bootstrap de la tabla cross-reference (proveedor, descripcion) -> SKU interno.
Toma las lineas de factura de compra SIN product_id (texto libre), agrupa por
(proveedor, descripcion normalizada), y sugiere el SKU interno por similitud de
tokens contra el catalogo codificado. NO escribe nada: genera un CSV para que la
persona confirme/corrija el SKU.

Excluye tabaco (precio fijo por ley) e impuestos ILA.

Uso:  python proyectos/2026-06-04-costo-desde-facturas/mapping_worksheet.py [YYYY-MM-DD YYYY-MM-DD]
Default: 2026-03-06..2026-06-04.
"""

import sys
import os
import unicodedata
sys.path.insert(0, '.')
from shared.odoo_xmlrpc import OdooReader

ILA_TAX_IDS = [5, 9, 10, 11, 12, 26, 31, 33, 34]
BAT_PARTNER = 301  # tabaco, precio fijo por ley -> fuera
STOPWORDS = {'de', 'la', 'el', 'x', 'con', 'sin', 'y', 'gr', 'g', 'kg', 'ml', 'cc', 'lt', 'l', 'un'}


def norm(s):
    s = (s or '').strip().upper()
    s = ''.join(c for c in unicodedata.normalize('NFKD', s) if not unicodedata.combining(c))
    out = []
    for ch in s:
        out.append(ch if (ch.isalnum() or ch == ' ') else ' ')
    return ' '.join(''.join(out).split())


def tokens(s):
    # tokens alfabeticos de marca/producto: descarta numeros, formato de pack
    # (30X116G, 12X30X15GRS), unidades y palabras muy cortas.
    out = []
    for t in norm(s).split():
        if any(c.isdigit() for c in t):
            continue
        if len(t) < 3 or t in STOPWORDS:
            continue
        out.append(t)
    return set(out)


def main():
    if len(sys.argv) >= 3:
        d_from, d_to = sys.argv[1], sys.argv[2]
    else:
        d_from, d_to = '2026-03-06', '2026-06-04'

    o = OdooReader()

    ila_lines = o.search_read('account.move.line',
                              [('parent_state', '=', 'posted'), ('move_id.move_type', '=', 'in_invoice'),
                               ('date', '>=', d_from), ('date', '<=', d_to), ('tax_ids', 'in', ILA_TAX_IDS)],
                              fields=['partner_id'], limit=300000)
    ila_p = set(l['partner_id'][0] for l in ila_lines if l['partner_id'])
    ila_p.add(BAT_PARTNER)

    moves = o.search_read('account.move',
                          [('state', '=', 'posted'), ('move_type', '=', 'in_invoice'),
                           ('invoice_date', '>=', d_from), ('invoice_date', '<=', d_to)],
                          fields=['id', 'partner_id'], limit=200000)
    mp = {m['id']: (m['partner_id'][1] if m['partner_id'] else '') for m in moves}
    ids = [m['id'] for m in moves if m['partner_id'] and m['partner_id'][0] not in ila_p]

    # catalogo codificado almacenable -> indice de tokens
    cat = o.search_read('product.product', [('default_code', '!=', False), ('type', '=', 'product')],
                        fields=['default_code', 'name'], limit=100000)
    cat_tokens = [(p['default_code'], p['name'], tokens(p['name'])) for p in cat]
    index = {}
    for i, (code, name, tks) in enumerate(cat_tokens):
        for t in tks:
            index.setdefault(t, []).append(i)
    print("catalogo codificado: %d SKU" % len(cat_tokens))

    def best_match(desc):
        dt = tokens(desc)
        if not dt:
            return '', '', 0.0
        cand = {}
        for t in dt:
            for i in index.get(t, []):
                cand[i] = cand.get(i, 0) + 1
        if not cand:
            return '', '', 0.0
        best_i, best_score = None, 0.0
        for i, _ in sorted(cand.items(), key=lambda x: -x[1])[:30]:
            ct = cat_tokens[i][2]
            inter = len(dt & ct)
            union = len(dt | ct)
            jac = inter / union if union else 0.0
            if jac > best_score:
                best_score = jac
                best_i = i
        if best_i is None:
            return '', '', 0.0
        return cat_tokens[best_i][0], cat_tokens[best_i][1], best_score

    # agrupar lineas texto libre por (partner, desc normalizada)
    agg = {}
    for i in range(0, len(ids), 300):
        ls = o.search_read('account.move.line',
                           [('move_id', 'in', ids[i:i + 300]), ('display_type', '=', 'product'),
                            ('product_id', '=', False)],
                           fields=['name', 'move_id', 'price_subtotal'])
        for l in ls:
            raw = (l['name'] or '').strip()
            if not raw:
                continue  # blanco -> fix origen, no va a la worksheet
            key = (mp.get(l['move_id'][0], ''), norm(raw))
            a = agg.setdefault(key, {'n': 0, 'sum': 0.0, 'ej': raw})
            a['n'] += 1
            a['sum'] += float(l['price_subtotal'] or 0.0)

    # CSV
    outdir = os.path.join('proyectos', '2026-06-04-costo-desde-facturas', 'resultados')
    if not os.path.isdir(outdir):
        os.makedirs(outdir)
    path = os.path.join(outdir, 'mapeo_descripcion_sku.csv')

    def numc(x):
        return ('%.0f' % x).replace('.', ',')

    # clasificar en tiers por confianza
    out_rows = []
    for (sup, ndesc), a in agg.items():
        code, name, score = best_match(a['ej'])
        if score >= 0.50 and code:
            tier = 'AUTO'
        elif score >= 0.30 and code:
            tier = 'REVISAR'
        else:
            tier, code, name = 'SIN_MATCH', '', ''
        out_rows.append({'sup': sup, 'desc': a['ej'], 'n': a['n'], 'sum': a['sum'],
                         'code': code, 'name': name, 'score': score, 'tier': tier})

    order = {'AUTO': 0, 'REVISAR': 1, 'SIN_MATCH': 2}
    out_rows.sort(key=lambda r: (order[r['tier']], -r['sum']))
    with open(path, 'w', encoding='utf-8-sig') as fh:
        fh.write('tier;proveedor;descripcion_factura;n_lineas;total_neto;sugerencia_sku;sugerencia_nombre;score;sku_confirmado\n')
        for r in out_rows:
            fh.write('%s;%s;%s;%d;%s;%s;%s;%s;\n' % (
                r['tier'], r['sup'][:40].replace(';', ','), r['desc'].replace(';', ',')[:60],
                r['n'], numc(r['sum']), r['code'], (r['name'] or '').replace(';', ',')[:40],
                ('%.2f' % r['score']).replace('.', ',')))

    from collections import Counter
    tc = Counter(r['tier'] for r in out_rows)
    sv = Counter()
    for r in out_rows:
        sv[r['tier']] += r['sum']
    print("filas (proveedor x descripcion distinta): %d" % len(out_rows))
    for t in ('AUTO', 'REVISAR', 'SIN_MATCH'):
        print("  %-9s: %4d filas | $ %s" % (t, tc.get(t, 0), ('%.0f' % sv.get(t, 0)).replace('.', ',')))
    print("\nCSV -> %s" % path)
    print("\nTop AUTO (listo para supplierinfo):")
    for r in [x for x in out_rows if x['tier'] == 'AUTO'][:15]:
        print("  $%9s  %-30s -> [%s] %s" % (('%.0f' % r['sum']), r['desc'][:30], r['code'], r['name'][:30]))


if __name__ == '__main__':
    main()
