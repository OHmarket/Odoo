"""
sweep_codigos.py — READ-ONLY.

Barrido del MAPEO POR CODIGO (el vinculo real). El DTE del proveedor manda
<CdgItem><VlrCodigo> = codigo interno del proveedor; Odoo lo matchea contra
product.default_code. Las lineas sin vincular son las cuyo codigo no existe como
default_code (ni hay supplierinfo.product_code).

Este barrido:
  1. Toma lineas de compra SIN product_id (texto libre), de proveedores de
     mercaderia (no tabaco, no servicios).
  2. Parsea el XML DTE adjunto de cada factura y extrae, por linea, el VlrCodigo.
  3. Agrupa por (proveedor, codigo) y sugiere el SKU interno por descripcion.
  -> insumo para cargar product.supplierinfo.product_code (codigo -> SKU).

NO escribe nada. Genera resultados/mapeo_codigo_sku.csv.

Uso: python proyectos/2026-06-04-costo-desde-facturas/sweep_codigos.py [YYYY-MM-DD YYYY-MM-DD] [pid,pid,...]
Default: 2026-03-06..2026-06-04, proveedores NORKOSHE/HDOSO/HAMBURGO (282,470,286).
"""

import sys
import os
import re
import base64
import unicodedata
sys.path.insert(0, '.')
from shared.odoo_xmlrpc import OdooReader

STOPWORDS = {'de', 'la', 'el', 'con', 'sin', 'gr', 'kg', 'ml', 'cc', 'lt', 'un', 'nvo', 'cl', 'pr', 'rrp'}


def norm(s):
    s = (s or '').strip().upper()
    s = ''.join(c for c in unicodedata.normalize('NFKD', s) if not unicodedata.combining(c))
    return ' '.join(''.join(c if (c.isalnum() or c == ' ') else ' ' for c in s).split())


def toks(s):
    return set(t for t in norm(s).split() if len(t) >= 3 and not any(d.isdigit() for d in t) and t not in STOPWORDS)


BAT_PARTNER = 301  # tabaco, precio fijo por ley -> fuera


def main():
    # default: TODOS los proveedores (excepto tabaco). Pasar pids para acotar.
    d_from, d_to = '2026-03-06', '2026-06-04'
    partner_ids = None
    if len(sys.argv) >= 3:
        d_from, d_to = sys.argv[1], sys.argv[2]
    if len(sys.argv) >= 4 and sys.argv[3].lower() not in ('all', 'todos', '*'):
        partner_ids = [int(x) for x in sys.argv[3].split(',')]

    o = OdooReader()

    dom = [('state', '=', 'posted'), ('move_type', '=', 'in_invoice'),
           ('invoice_date', '>=', d_from), ('invoice_date', '<=', d_to)]
    if partner_ids:
        dom.append(('partner_id', 'in', partner_ids))
    else:
        dom.append(('partner_id', '!=', BAT_PARTNER))
    moves = o.search_read('account.move', dom, fields=['id', 'partner_id'], limit=50000)
    print("facturas: %d  (alcance: %s)" % (len(moves), 'TODOS los proveedores' if not partner_ids else partner_ids))

    # catalogo codificado para sugerir SKU
    cat = o.search_read('product.product', [('default_code', '!=', False), ('type', '=', 'product')],
                        fields=['default_code', 'name'], limit=100000)
    cat_t = [(p['default_code'], p['name'], toks(p['name'])) for p in cat]
    index = {}
    by_code = {}   # default_code y su version sin espacios -> (code, name)
    for i, (c, n, tk) in enumerate(cat_t):
        for t in tk:
            index.setdefault(t, []).append(i)
        by_code.setdefault(c, (c, n))
        by_code.setdefault(c.replace(' ', ''), (c, n))

    def code_match(cod):
        # match por codigo: exacto o quitando espacios (el espacio rompe el link)
        hit = by_code.get(cod) or by_code.get(cod.replace(' ', ''))
        return hit if hit else ('', '')

    def suggest(desc):
        dt = toks(desc)
        if not dt:
            return '', '', 0.0
        cand = {}
        for t in dt:
            for i in index.get(t, []):
                cand[i] = cand.get(i, 0) + 1
        best, bs = None, 0.0
        for i, _ in sorted(cand.items(), key=lambda x: -x[1])[:40]:
            ct = cat_t[i][2]
            j = len(dt & ct) / len(dt | ct) if (dt | ct) else 0.0
            if j > bs:
                bs, best = j, i
        if best is None:
            return '', '', 0.0
        return cat_t[best][0], cat_t[best][1], bs

    def parse_dte(mid):
        # devuelve {NmbItem_norm: (vlrcodigo, tpocodigo)}
        att = o.search_read('ir.attachment',
                            [('res_model', '=', 'account.move'), ('res_id', '=', mid),
                             ('name', 'like', 'DTE_%')],
                            fields=['datas', 'name'], limit=3)
        out = {}
        for a in att:
            if not a.get('datas'):
                continue
            try:
                xml = base64.b64decode(a['datas']).decode('latin-1', 'ignore')
            except Exception:
                continue
            for d in re.findall(r'<Detalle>(.*?)</Detalle>', xml, re.S):
                m = re.search(r'<NmbItem>(.*?)</NmbItem>', d, re.S)
                if not m:
                    continue
                nmb = norm(m.group(1))
                codes = re.findall(r'<CdgItem>(.*?)</CdgItem>', d, re.S)
                vlr, tpo = '', ''
                # preferir TpoCodigo INT* (interno proveedor); sino el primero
                chosen = None
                parsed = []
                for c in codes:
                    t = (re.search(r'<TpoCodigo>(.*?)</TpoCodigo>', c) or [None])
                    t = re.search(r'<TpoCodigo>(.*?)</TpoCodigo>', c)
                    v = re.search(r'<VlrCodigo>(.*?)</VlrCodigo>', c)
                    if v:
                        parsed.append(((t.group(1) if t else ''), v.group(1)))
                for t, v in parsed:
                    if t.upper().startswith('INT'):
                        chosen = (v, t)
                        break
                if not chosen and parsed:
                    chosen = (parsed[0][1], parsed[0][0])
                if chosen:
                    out[nmb] = chosen
            if out:
                break
        return out

    pname = {m['id']: (m['partner_id'][1] if m['partner_id'] else '') for m in moves}
    agg = {}            # (partner, codigo, tpo) -> {n, sum, desc}
    sincodigo = {}      # (partner, desc_norm) -> {n, sum, desc}
    n_moves_xml = 0

    for m in moves:
        mid = m['id']
        ls = o.search_read('account.move.line',
                           [('move_id', '=', mid), ('display_type', '=', 'product'), ('product_id', '=', False)],
                           fields=['name', 'price_subtotal'])
        ls = [l for l in ls if (l['name'] or '').strip()]
        if not ls:
            continue
        dte = parse_dte(mid)
        if dte:
            n_moves_xml += 1
        for l in ls:
            nm = (l['name'] or '').strip()
            sub = float(l['price_subtotal'] or 0.0)
            hit = dte.get(norm(nm))
            if hit:
                key = (pname[mid], hit[0], hit[1])
                a = agg.setdefault(key, {'n': 0, 'sum': 0.0, 'desc': nm})
                a['n'] += 1
                a['sum'] += sub
            else:
                key = (pname[mid], norm(nm))
                a = sincodigo.setdefault(key, {'n': 0, 'sum': 0.0, 'desc': nm})
                a['n'] += 1
                a['sum'] += sub

    print("facturas con XML DTE parseado:", n_moves_xml)
    print("(proveedor, codigo) distintos:", len(agg), "| lineas SIN codigo en XML:", len(sincodigo))

    outdir = os.path.join('proyectos', '2026-06-04-costo-desde-facturas', 'resultados')
    if not os.path.isdir(outdir):
        os.makedirs(outdir)
    path = os.path.join(outdir, 'mapeo_codigo_sku.csv')

    def numc(x):
        return ('%.0f' % x).replace('.', ',')

    rows = []
    for (sup, cod, tpo), a in agg.items():
        cc, cn = code_match(cod)
        if cc:
            rows.append((sup, cod, tpo, a['desc'], a['n'], a['sum'], cc, cn, 1.0, 'CODIGO'))
        else:
            sc, sn, score = suggest(a['desc'])
            tier = 'DESC' if (sc and score >= 0.4) else 'SIN_MATCH'
            rows.append((sup, cod, tpo, a['desc'], a['n'], a['sum'],
                         sc if tier == 'DESC' else '', sn if tier == 'DESC' else '', score, tier))
    rows.sort(key=lambda r: ({'CODIGO': 0, 'DESC': 1, 'SIN_MATCH': 2}[r[9]], -r[5]))

    with open(path, 'w', encoding='utf-8-sig') as fh:
        fh.write('match;proveedor;codigo_dte;tpo;descripcion;n_lineas;total_neto;sugerencia_sku;sugerencia_nombre;score;sku_confirmado\n')
        for sup, cod, tpo, desc, n, s, sc, sn, score, tier in rows:
            fh.write('%s;%s;%s;%s;%s;%d;%s;%s;%s;%s;\n' % (
                tier, sup[:38].replace(';', ','), cod, tpo, desc.replace(';', ',')[:50], n, numc(s),
                sc, (sn or '').replace(';', ',')[:38], ('%.2f' % score).replace('.', ',')))
        for (sup, ndesc), a in sorted(sincodigo.items(), key=lambda kv: -kv[1]['sum']):
            fh.write('SIN_CODIGO_DTE;%s;;;%s;%d;%s;;;;\n' % (
                sup[:38].replace(';', ','), a['desc'].replace(';', ',')[:50], a['n'], numc(a['sum'])))

    from collections import Counter
    tc = Counter(r[9] for r in rows)
    sv = Counter()
    for r in rows:
        sv[r[9]] += r[5]
    print("\nResultado por tipo de match:")
    for t in ('CODIGO', 'DESC', 'SIN_MATCH'):
        print("  %-9s: %3d codigos | $ %s" % (t, tc.get(t, 0), numc(sv.get(t, 0))))
    print("  %-9s: %3d lineas (sin codigo en XML)" % ('SIN_XML', len(sincodigo)))
    print("\nCSV -> %s" % path)
    print("\nTop match por CODIGO (alta confianza, codigo DTE -> default_code):")
    for r in [x for x in rows if x[9] == 'CODIGO'][:16]:
        print("  $%9s  DTE=%-8s -> [%s] %s" % (numc(r[5]), r[1], r[6], r[7][:30]))


if __name__ == '__main__':
    main()
