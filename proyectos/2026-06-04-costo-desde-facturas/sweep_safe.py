"""sweep_safe.py — READ-ONLY. Lista los 'seguros para arreglar' en TODO el historial.

Eficiente: deduplica las lineas de compra SIN vincular por (proveedor, descripcion),
parsea UN XML por factura representativa, saca el VlrCodigo (INT1) y clasifica:

  SEGURO  = el codigo del DTE, quitando el espacio, calza con UN solo product
            default_code existente, sin colision (no existe el codigo con espacio).
            -> fix 1:1 trivial: default_code -> codigo_DTE (con espacio).
  REVISAR = match ambiguo / por descripcion.
  SIN     = sin producto (codigo ajeno / crear o mapear manual).

Genera resultados/seguros_para_arreglar.csv.
Uso: python proyectos/2026-06-04-costo-desde-facturas/sweep_safe.py [d_from]
"""
import sys, os, re, base64, unicodedata
sys.path.insert(0, '.')
from shared.odoo_xmlrpc import OdooReader

BAT = 301


def norm(s):
    s = (s or '').strip().upper()
    s = ''.join(c for c in unicodedata.normalize('NFKD', s) if not unicodedata.combining(c))
    return ' '.join(s.split())


def main():
    d_from = sys.argv[1] if len(sys.argv) > 1 else '2023-01-01'
    o = OdooReader()

    # 1) todas las lineas de compra SIN vincular (texto libre), no tabaco
    print('leyendo lineas sin vincular desde %s ...' % d_from)
    dedup = {}   # (partner_id, norm_name) -> {move, sum, n, name, partner}
    offset = 0
    while True:
        ls = o.search_read('account.move.line',
                           [('move_id.move_type', '=', 'in_invoice'), ('parent_state', '=', 'posted'),
                            ('display_type', '=', 'product'), ('product_id', '=', False),
                            ('date', '>=', d_from), ('partner_id', '!=', BAT)],
                           fields=['move_id', 'partner_id', 'name', 'price_subtotal'],
                           limit=5000, offset=offset, order='id')
        if not ls:
            break
        offset += len(ls)
        for l in ls:
            nm = (l['name'] or '').strip()
            if not nm or not l['partner_id']:
                continue
            k = (l['partner_id'][0], norm(nm))
            d = dedup.get(k)
            if d is None:
                dedup[k] = {'move': l['move_id'][0], 'sum': 0.0, 'n': 0,
                            'name': nm, 'partner': l['partner_id'][1]}
                d = dedup[k]
            d['sum'] += float(l['price_subtotal'] or 0.0)
            d['n'] += 1
    print('descripciones distintas (proveedor x texto): %d' % len(dedup))

    # 2) parsear UN xml por move representativo
    moves = sorted(set(d['move'] for d in dedup.values()))
    print('parseando %d XML representativos ...' % len(moves))
    code_by_move_name = {}   # move_id -> {norm_name: vlrcodigo}
    for i in range(0, len(moves), 80):
        att = o.search_read('ir.attachment',
                            [('res_model', '=', 'account.move'), ('res_id', 'in', moves[i:i+80]),
                             ('name', 'like', 'DTE_%')], fields=['datas', 'res_id'], limit=300)
        for a in att:
            if not a.get('datas') or a['res_id'] in code_by_move_name:
                continue
            try:
                xml = base64.b64decode(a['datas']).decode('latin-1', 'ignore')
            except Exception:
                continue
            mp = {}
            for det in re.findall(r'<Detalle>(.*?)</Detalle>', xml, re.S):
                v = re.search(r'<TpoCodigo>INT1</TpoCodigo>\s*<VlrCodigo>(.*?)</VlrCodigo>', det, re.S)
                n = re.search(r'<NmbItem>(.*?)</NmbItem>', det, re.S)
                if v and n:
                    mp[norm(n.group(1))] = v.group(1)
            code_by_move_name[a['res_id']] = mp

    # 3) recolectar codigos y buscar default_code (exacto y stripped)
    rows = []
    for (pid, nname), d in dedup.items():
        cod = code_by_move_name.get(d['move'], {}).get(nname)
        d['cod'] = cod
    allcods = set(d['cod'] for d in dedup.values() if d.get('cod'))
    keys = set()
    for c in allcods:
        keys.add(c)
        keys.add(c.replace(' ', ''))
    dc_map = {}
    keys = list(keys)
    for i in range(0, len(keys), 400):
        for p in o.search_read('product.product', [('default_code', 'in', keys[i:i+400])],
                               fields=['id', 'name', 'default_code']):
            dc_map.setdefault(p['default_code'], []).append(p)

    seguros = []
    for (pid, nname), d in dedup.items():
        cod = d.get('cod')
        if not cod or ' ' not in cod:
            continue
        if cod in dc_map:
            continue  # ya existe exacto (deberia vincular)
        cand = dc_map.get(cod.replace(' ', ''), [])
        if len(cand) == 1:
            seguros.append((d['sum'], d['n'], d['partner'], cand[0]['default_code'], cod, cand[0]['name'], d['name']))

    seguros.sort(reverse=True)
    outdir = os.path.join('proyectos', '2026-06-04-costo-desde-facturas', 'resultados')
    if not os.path.isdir(outdir):
        os.makedirs(outdir)
    path = os.path.join(outdir, 'seguros_para_arreglar.csv')
    with open(path, 'w', encoding='utf-8-sig') as fh:
        fh.write('proveedor;default_code_actual;default_code_correcto;producto;n_lineas;total_neto;desc_factura\n')
        for s, n, sup, dcn, dcc, pname, desc in seguros:
            fh.write('%s;%s;%s;%s;%d;%s;%s\n' % (sup[:30].replace(';', ','), dcn, dcc,
                     (pname or '').replace(';', ',')[:42], n, ('%.0f' % s).replace('.', ','), desc.replace(';', ',')[:34]))

    tot = sum(r[0] for r in seguros)
    print('\n=== SEGUROS PARA ARREGLAR (default_code 1:1, sin ambiguedad): %d  | $ %s ===' % (len(seguros), ('%.0f' % tot).replace('.', ',')))
    from collections import Counter
    bysup = Counter()
    for r in seguros:
        bysup[r[2]] += 1
    print('por proveedor:')
    for sup, c in bysup.most_common(12):
        print('  %3d  %s' % (c, sup[:46]))
    print('\nTop por $:')
    for s, n, sup, dcn, dcc, pname, desc in seguros[:20]:
        print('  $%9s  %-8s -> %-9s  %s' % (('%.0f' % s), dcn, dcc, pname[:34]))
    print('\nCSV -> %s' % path)


if __name__ == '__main__':
    main()
