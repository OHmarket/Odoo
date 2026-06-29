"""verify_codigos.py — READ-ONLY. Valida la regla: INT1 VlrCodigo sin espacio == default_code."""
import sys, base64, re
sys.path.insert(0, '.')
from shared.odoo_xmlrpc import OdooReader

ILA = [5, 9, 10, 11, 12, 26, 31, 33, 34]


def main():
    d_from = sys.argv[1] if len(sys.argv) > 1 else '2026-03-06'
    d_to = sys.argv[2] if len(sys.argv) > 2 else '2026-06-04'
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else 400
    o = OdooReader()
    ila = o.search_read('account.move.line', [('parent_state', '=', 'posted'), ('move_id.move_type', '=', 'in_invoice'),
                        ('date', '>=', d_from), ('date', '<=', d_to), ('tax_ids', 'in', ILA)], fields=['partner_id'], limit=300000)
    ilap = set(l['partner_id'][0] for l in ila if l['partner_id'])
    ilap.add(301)
    moves = o.search_read('account.move', [('state', '=', 'posted'), ('move_type', '=', 'in_invoice'),
                          ('invoice_date', '>=', d_from), ('invoice_date', '<=', d_to)], fields=['id', 'partner_id'], limit=20000)
    ids = [m['id'] for m in moves if m['partner_id'] and m['partner_id'][0] not in ilap][:limit]
    print('parseando hasta %d facturas (no tabaco, no ILA)...' % len(ids))

    codes = {}   # vlr -> {'uom':set, 'nmb':sample, 'n':0}
    nxml = 0
    for i in range(0, len(ids), 50):
        att = o.search_read('ir.attachment', [('res_model', '=', 'account.move'), ('res_id', 'in', ids[i:i+50]),
                            ('name', 'like', 'DTE_%')], fields=['datas', 'res_id'], limit=200)
        for a in att:
            if not a.get('datas'):
                continue
            try:
                xml = base64.b64decode(a['datas']).decode('latin-1', 'ignore')
            except Exception:
                continue
            nxml += 1
            for d in re.findall(r'<Detalle>(.*?)</Detalle>', xml, re.S):
                uom = re.search(r'<UnmdItem>(.*?)</UnmdItem>', d)
                nmb = re.search(r'<NmbItem>(.*?)</NmbItem>', d, re.S)
                for c in re.findall(r'<CdgItem>(.*?)</CdgItem>', d, re.S):
                    tpo = re.search(r'<TpoCodigo>(.*?)</TpoCodigo>', c)
                    vlr = re.search(r'<VlrCodigo>(.*?)</VlrCodigo>', c)
                    if tpo and vlr and tpo.group(1).upper().startswith('INT'):
                        v = vlr.group(1).strip()
                        e = codes.setdefault(v, {'uom': set(), 'nmb': '', 'n': 0})
                        e['n'] += 1
                        if uom:
                            e['uom'].add(uom.group(1))
                        if nmb and not e['nmb']:
                            e['nmb'] = nmb.group(1).strip()

    print('facturas con XML: %d | codigos INT1 distintos: %d' % (nxml, len(codes)))
    # chequear default_code (exacto y sin espacio)
    stripped = {v.replace(' ', ''): v for v in codes}
    exist = set()
    keys = list({v for v in codes} | set(stripped.keys()))
    for i in range(0, len(keys), 400):
        for p in o.search_read('product.product', [('default_code', 'in', keys[i:i+400])], fields=['default_code']):
            exist.add(p['default_code'])

    m_exact = m_strip = m_no = 0
    ej_strip, ej_no = [], []
    for v in codes:
        if v in exist:
            m_exact += 1
        elif v.replace(' ', '') in exist:
            m_strip += 1
            if len(ej_strip) < 12:
                ej_strip.append((v, codes[v]['uom'], codes[v]['nmb']))
        else:
            m_no += 1
            if len(ej_no) < 12:
                ej_no.append((v, codes[v]['uom'], codes[v]['nmb']))

    tot = len(codes)
    print('\n== Match contra default_code ==')
    print('  exacto (ya vincula)         : %d  (%.0f%%)' % (m_exact, 100*m_exact/max(tot, 1)))
    print('  SIN ESPACIO -> default_code : %d  (%.0f%%)  <- regla propuesta' % (m_strip, 100*m_strip/max(tot, 1)))
    print('  sin match                   : %d  (%.0f%%)' % (m_no, 100*m_no/max(tot, 1)))
    print('\nEjemplos SIN ESPACIO (DTE -> interno):')
    for v, uom, nmb in ej_strip:
        print('  %-9r uom=%-12s -> %-8s | %s' % (v, ','.join(uom), v.replace(' ', ''), nmb[:34]))
    print('\nEjemplos SIN MATCH (faltan en catalogo):')
    for v, uom, nmb in ej_no:
        print('  %-9r uom=%-12s | %s' % (v, ','.join(uom), nmb[:40]))


if __name__ == '__main__':
    main()
