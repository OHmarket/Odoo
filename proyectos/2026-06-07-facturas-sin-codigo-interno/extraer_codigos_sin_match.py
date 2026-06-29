# -*- coding: utf-8 -*-
"""
Lineas de factura de compra 2026 sin contraparte interna (product_id vacio) +
recomendacion de a que producto OH deberian vincularse.

Salida (sin duplicados, 1 fila por proveedor+codigo):
  PROVEEDOR ; REFERENCIA_INTERNA ; DESCRIPCION_PROVEEDOR ; CODIGO_PRODUCT_ID_RECOMENDADO
  (+ nombre_recomendado, confianza, metodo, n_facturas, monto_total)

REFERENCIA_INTERNA = VlrCodigo (TpoCodigo=INTERNA) recuperado del adjunto DTE XML.
Recomendacion: si el VlrCodigo existe como default_code -> match directo; si no,
fuzzy match de la descripcion contra el catalogo OH.

Read-only. Correr desde la raiz: python proyectos/.../extraer_codigos_sin_match.py
"""
from __future__ import annotations
import sys, os, base64, re, csv
import xml.etree.ElementTree as ET
from collections import defaultdict
from difflib import SequenceMatcher

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from shared.odoo_xmlrpc import OdooReader

OUT_DIR = os.path.join(os.path.dirname(__file__), 'resultados')
FUZZY_MIN = 0.60

# Cuenta de mercaderia de reventa. Filtro estructural (no keywords): solo las
# lineas imputadas a esta cuenta son producto de venta; el resto son gastos.
ACCOUNT_MERCADERIA = 82  # 210230 Facturas por Recibir

# Cargos dentro de mercaderia que no son un SKU (flete/recargo/descuento).
RUIDO = ('flete', 'recargo', 'recarga', 'descuento', 'bonificac',
         'uso del sitio', 'interes', 'redondeo', 'despacho')


def es_ruido(n):
    if not n:
        return True
    nl = n.lower()
    return any(k in nl for k in RUIDO)


def norm(s):
    if not s:
        return ''
    return re.sub(r'\s+', ' ', s).strip().upper()


_STOP = {'DE', 'EL', 'LA', 'CON', 'X', 'Y', 'G', 'GR', 'GRS', 'KG', 'ML', 'CC',
         'LT', 'LTS', 'L', 'UN', 'UND', 'UNID', 'UNIDADES'}


def tokens(s):
    s = norm(s)
    s = re.sub(r'[^A-Z0-9 ]', ' ', s)
    return {t for t in s.split() if t and t not in _STOP and len(t) > 1}


def parse_dte(xml_bytes):
    """{NmbItem_norm: VlrCodigo} priorizando TpoCodigo=INTERNA."""
    txt = xml_bytes.decode('latin-1', errors='replace')
    txt = re.sub(r'xmlns="[^"]+"', '', txt)
    out = {}
    try:
        root = ET.fromstring(txt)
    except ET.ParseError:
        return out
    for det in root.iter('Detalle'):
        nmb = norm(det.findtext('NmbItem'))
        if not nmb:
            continue
        cods = [((c.findtext('TpoCodigo') or '').upper(), c.findtext('VlrCodigo') or '')
                for c in det.findall('CdgItem')]
        cods = [c for c in cods if c[1]]
        if not cods:
            continue
        interna = [v for t, v in cods if t == 'INTERNA']
        out[nmb] = interna[0] if interna else cods[0][1]
    return out


def best_match(desc, catalogo):
    """Mejor candidato del catalogo para una descripcion. catalogo: [(code,name,toks)]."""
    dt = tokens(desc)
    if not dt:
        return None, None, 0.0
    best = (None, None, 0.0)
    dn = norm(desc)
    for code, name, ntoks in catalogo:
        if not ntoks:
            continue
        inter = len(dt & ntoks)
        if inter == 0:
            continue
        jac = inter / len(dt | ntoks)
        ratio = SequenceMatcher(None, dn, norm(name)).ratio()
        score = 0.6 * jac + 0.4 * ratio
        if score > best[2]:
            best = (code, name, score)
    return best


def main():
    o = OdooReader()
    print('conexion OK uid=%s' % o.uid)

    base = [('move_id.move_type', '=', 'in_invoice'),
            ('move_id.invoice_date', '>=', '2026-01-01'),
            ('display_type', '=', 'product'),
            ('product_id', '=', False),
            ('account_id', '=', ACCOUNT_MERCADERIA)]
    lines = o.search_read('account.move.line', base,
                          fields=['name', 'move_id', 'partner_id',
                                  'price_subtotal'], limit=0)
    lines = [l for l in lines if not es_ruido(l.get('name'))]
    print('lineas producto real sin match: %d' % len(lines))

    by_move = defaultdict(list)
    for l in lines:
        by_move[l['move_id'][0]].append(l)
    move_ids = list(by_move)
    print('facturas a revisar: %d' % len(move_ids))

    # prefetch adjuntos XML por factura
    att_by_move = {}
    for i in range(0, len(move_ids), 200):
        chunk = move_ids[i:i + 200]
        atts = o.search_read('ir.attachment',
                             [('res_model', '=', 'account.move'),
                              ('res_id', 'in', chunk),
                              ('mimetype', 'in', ['application/xml', 'text/xml'])],
                             fields=['res_id', 'name'])
        for a in atts:  # preferir DTE_*
            if (a.get('name') or '').upper().startswith('DTE'):
                att_by_move.setdefault(a['res_id'], a['id'])
        for a in atts:  # fallback cualquier xml
            att_by_move.setdefault(a['res_id'], a['id'])
    print('facturas con XML: %d' % len(att_by_move))

    # recuperar VlrCodigo por descripcion (descargar XML solo si aporta nuevas)
    resueltos = {}   # desc_norm -> VlrCodigo
    descargadas = 0
    for mid in move_ids:
        nuevas = [l for l in by_move[mid] if norm(l['name']) not in resueltos]
        if not nuevas:
            continue
        att_id = att_by_move.get(mid)
        if not att_id:
            continue
        rec = o.execute('ir.attachment', 'read', [att_id], ['datas'])
        descargadas += 1
        data = rec[0].get('datas') if rec else None
        if not data:
            continue
        mapa = parse_dte(base64.b64decode(data))
        for l in nuevas:
            d = norm(l['name'])
            if d in mapa:
                resueltos[d] = mapa[d]
        if descargadas % 100 == 0:
            print('  XML descargados=%d  desc resueltas=%d' % (descargadas, len(resueltos)))
    print('XML descargados=%d  descripciones con codigo=%d' % (descargadas, len(resueltos)))

    # catalogo OH
    prods = o.search_read('product.product', [('default_code', '!=', False)],
                          fields=['default_code', 'name'])
    catalogo = [(p['default_code'], p.get('name') or '', tokens(p.get('name')))
                for p in prods]
    default_codes = {p['default_code'] for p in prods}
    print('catalogo con default_code: %d' % len(catalogo))

    # agrupar por (proveedor, codigo)  (o por (proveedor, desc) si sin codigo)
    agg = {}
    for l in lines:
        d_raw = l['name']
        d = norm(d_raw)
        cod = resueltos.get(d, '')
        prov = l['partner_id'][1] if l.get('partner_id') else ''
        key = (prov, cod) if cod else (prov, 'DESC::' + d)
        a = agg.setdefault(key, {
            'proveedor': prov, 'referencia_interna': cod, 'descripcion': d_raw,
            'n_facturas': set(), 'monto': 0.0})
        a['n_facturas'].add(l['move_id'][0])
        a['monto'] += l.get('price_subtotal') or 0.0

    print('filas unicas (proveedor+codigo): %d' % len(agg))

    # recomendacion por fila + cache de fuzzy por descripcion
    fuzzy_cache = {}
    rows_out = []
    for a in agg.values():
        cod = a['referencia_interna']
        desc = a['descripcion']
        if cod and cod in default_codes:
            rec_code, rec_name, conf, metodo = cod, '(mismo codigo)', 'ALTA', 'codigo_exacto'
        else:
            dn = norm(desc)
            if dn not in fuzzy_cache:
                fuzzy_cache[dn] = best_match(desc, catalogo)
            mc, mn, score = fuzzy_cache[dn]
            if mc and score >= FUZZY_MIN:
                rec_code, rec_name = mc, mn
                conf = 'ALTA' if score >= 0.8 else 'MEDIA'
                metodo = 'fuzzy'
            else:
                rec_code, rec_name, conf, metodo = '', '', 'BAJA', 'sin_sugerencia'
        rows_out.append({
            'PROVEEDOR': a['proveedor'],
            'REFERENCIA_INTERNA': cod,
            'DESCRIPCION_PROVEEDOR': desc,
            'CODIGO_PRODUCT_ID_RECOMENDADO': rec_code,
            'nombre_recomendado': rec_name,
            'confianza': conf,
            'metodo': metodo,
            'n_facturas': len(a['n_facturas']),
            'monto_total': round(a['monto'], 2),
        })

    rows_out.sort(key=lambda r: (-r['n_facturas'], -r['monto_total']))

    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, 'codigos_recomendacion_match.csv')
    with open(path, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(rows_out[0].keys()), delimiter=';')
        w.writeheader()
        for r in rows_out:
            r = dict(r)
            r['monto_total'] = str(r['monto_total']).replace('.', ',')
            w.writerow(r)

    from collections import Counter
    cc = Counter(r['metodo'] for r in rows_out)
    print('\n=== RESUMEN ===')
    print('filas unicas exportadas: %d' % len(rows_out))
    for k, v in cc.items():
        print('  %-16s %d' % (k, v))
    print('archivo:', path)


if __name__ == '__main__':
    main()
