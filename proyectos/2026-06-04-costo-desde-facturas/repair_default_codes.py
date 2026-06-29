"""repair_default_codes.py — READ-ONLY.

Detecta default_code "limpiados" (espacio quitado) que rompen el vinculo con el
DTE. El link es product.default_code == <VlrCodigo> EXACTO. Si el DTE manda
"8791 0" pero el producto tiene default_code "87910", no vincula.

Para cada codigo INT1 de lineas SIN vincular:
  stripped = codigo sin espacio
  si NO existe producto con default_code == codigo (con espacio)
  y existe UNO con default_code == stripped
  -> proponer: ese producto default_code "stripped" -> "codigo" (formato DTE)

Genera resultados/reparar_default_codes.csv (dry-run, para revisar). No escribe.

Uso: python proyectos/2026-06-04-costo-desde-facturas/repair_default_codes.py [d_from d_to] [limit]
"""
import sys, os, re, base64
sys.path.insert(0, '.')
from shared.odoo_xmlrpc import OdooReader

ILA = [5, 9, 10, 11, 12, 26, 31, 33, 34]


def norm(s):
    return ' '.join((s or '').strip().split())


def main():
    d_from = sys.argv[1] if len(sys.argv) > 1 else '2026-03-06'
    d_to = sys.argv[2] if len(sys.argv) > 2 else '2026-06-04'
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else 600
    o = OdooReader()

    ila = o.search_read('account.move.line', [('parent_state', '=', 'posted'), ('move_id.move_type', '=', 'in_invoice'),
                        ('date', '>=', d_from), ('date', '<=', d_to), ('tax_ids', 'in', ILA)], fields=['partner_id'], limit=300000)
    ilap = set(l['partner_id'][0] for l in ila if l['partner_id']); ilap.add(301)
    moves = o.search_read('account.move', [('state', '=', 'posted'), ('move_type', '=', 'in_invoice'),
                          ('invoice_date', '>=', d_from), ('invoice_date', '<=', d_to)], fields=['id', 'partner_id'], limit=20000)
    mp = {m['id']: (m['partner_id'][1] if m['partner_id'] else '') for m in moves}
    ids = [m['id'] for m in moves if m['partner_id'] and m['partner_id'][0] not in ilap][:limit]
    print('parseando hasta %d facturas...' % len(ids))

    # codigo DTE -> {n, sum, desc, sup}
    agg = {}
    nxml = 0
    for i in range(0, len(ids), 60):
        chunk = ids[i:i+60]
        frees = o.search_read('account.move.line', [('move_id', 'in', chunk), ('display_type', '=', 'product'),
                              ('product_id', '=', False)], fields=['move_id', 'name', 'price_subtotal'])
        by_move = {}
        for l in frees:
            if (l['name'] or '').strip():
                by_move.setdefault(l['move_id'][0], []).append(l)
        if not by_move:
            continue
        att = o.search_read('ir.attachment', [('res_model', '=', 'account.move'), ('res_id', 'in', list(by_move.keys())),
                            ('name', 'like', 'DTE_%')], fields=['datas', 'res_id'], limit=300)
        xml_by_move = {}
        for a in att:
            if a.get('datas') and a['res_id'] not in xml_by_move:
                try:
                    xml_by_move[a['res_id']] = base64.b64decode(a['datas']).decode('latin-1', 'ignore')
                except Exception:
                    pass
        for mid, lines in by_move.items():
            xml = xml_by_move.get(mid)
            if not xml:
                continue
            nxml += 1
            code_by_name = {}
            for d in re.findall(r'<Detalle>(.*?)</Detalle>', xml, re.S):
                v = re.search(r'<TpoCodigo>INT1</TpoCodigo>\s*<VlrCodigo>(.*?)</VlrCodigo>', d, re.S)
                n = re.search(r'<NmbItem>(.*?)</NmbItem>', d, re.S)
                if v and n:
                    code_by_name[norm(n.group(1))] = v.group(1)
            for l in lines:
                cod = code_by_name.get(norm(l['name']))
                if not cod:
                    continue
                a = agg.setdefault(cod, {'n': 0, 'sum': 0.0, 'desc': l['name'].strip(), 'sup': mp.get(mid, '')})
                a['n'] += 1
                a['sum'] += float(l['price_subtotal'] or 0.0)

    print('facturas con XML: %d | codigos DTE distintos (lineas libres): %d' % (nxml, len(agg)))

    # buscar default_codes: exacto y stripped
    allk = set()
    for cod in agg:
        allk.add(cod)
        allk.add(cod.replace(' ', ''))
    dc_map = {}
    keys = list(allk)
    for i in range(0, len(keys), 400):
        for p in o.search_read('product.product', [('default_code', 'in', keys[i:i+400])],
                               fields=['id', 'name', 'default_code']):
            dc_map.setdefault(p['default_code'], []).append(p)

    rows = []
    for cod, a in agg.items():
        if ' ' not in cod:
            continue  # sin espacio no aplica esta reparacion
        if cod in dc_map:
            continue  # ya existe exacto -> deberia vincular (libre por otra razon)
        stripped = cod.replace(' ', '')
        cand = dc_map.get(stripped, [])
        if len(cand) == 1:
            p = cand[0]
            rows.append((a['sum'], a['n'], a['sup'], stripped, cod, p['name'], a['desc']))

    rows.sort(reverse=True)
    outdir = os.path.join('proyectos', '2026-06-04-costo-desde-facturas', 'resultados')
    if not os.path.isdir(outdir):
        os.makedirs(outdir)
    path = os.path.join(outdir, 'reparar_default_codes.csv')
    with open(path, 'w', encoding='utf-8-sig') as fh:
        fh.write('proveedor;default_code_actual;default_code_propuesto;producto;n_lineas_libres;total_neto;desc_factura\n')
        for s, n, sup, dc_now, dc_new, pname, desc in rows:
            fh.write('%s;%s;%s;%s;%d;%s;%s\n' % (sup[:30].replace(';', ','), dc_now, dc_new,
                     (pname or '').replace(';', ',')[:40], n, ('%.0f' % s).replace('.', ','), desc.replace(';', ',')[:36]))

    tot = sum(r[0] for r in rows)
    print('\nProductos a corregir (default_code limpiado -> formato DTE): %d  | $ libre afectado: %s'
          % (len(rows), ('%.0f' % tot).replace('.', ',')))
    print('\nTop por $:')
    print('  $total      actual -> propuesto   producto')
    for s, n, sup, dc_now, dc_new, pname, desc in rows[:20]:
        print('  $%9s  %-8s -> %-9s  %s' % (('%.0f' % s), dc_now, dc_new, pname[:32]))
    print('\nCSV -> %s' % path)


if __name__ == '__main__':
    main()
