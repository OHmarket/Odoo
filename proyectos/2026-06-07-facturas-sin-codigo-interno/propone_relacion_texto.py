# -*- coding: utf-8 -*-
"""
Propone la relacion codigo_proveedor -> codigo_interno (default_code OH) por
similitud de TEXTO, usando marca/keywords + gramaje unitario para desambiguar.

Lee el CSV de 544 (codigos con referencia interna del proveedor) y para cada uno
propone el top-2 de productos OH mas parecidos. Los 90 'codigo_exacto' quedan como
CONFIRMADO (score 1.0).

Read-only. Correr desde la raiz.
"""
from __future__ import annotations
import sys, os, re, csv
from difflib import SequenceMatcher

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))
from shared.odoo_xmlrpc import OdooReader

OUT_DIR = os.path.join(os.path.dirname(__file__), 'resultados')
SRC = os.path.join(OUT_DIR, 'codigos_544_con_codigo.csv')

_STOP = {'DE', 'EL', 'LA', 'CON', 'X', 'Y', 'UN', 'UND', 'UNID', 'UNIDADES',
         'PRECIO', 'DISPLAY', 'NVO', 'NUEVO', 'CL', 'N1', 'BAR', 'BARRA',
         'COUNTLINE', 'PACK', 'CAJA', 'BOLSA', 'PROMO', 'OFERTA', 'IMPULSIVO',
         'TRADICIONAL', 'REGULAR', 'CLASICA', 'CLASICO'}

_UNIT = r'(?:G|GR|GRS|GRM|GRAMOS|KG|KGS|ML|CC|LT|LTS|L|MG)'


def norm(s):
    return re.sub(r'\s+', ' ', (s or '')).strip().upper()


def gramaje(s):
    """Gramaje unitario en gramos/ml. En 'NxMxK GRS' toma K (la ultima cifra)."""
    u = norm(s)
    # formato cajaXcajaXunit: tomar el ultimo numero del bloque NxNxN
    m = re.findall(r'(\d+(?:[.,]\d+)?)\s*X\s*(\d+(?:[.,]\d+)?)(?:\s*X\s*(\d+(?:[.,]\d+)?))?', u)
    cand = []
    if m:
        for grp in m:
            vals = [g for g in grp if g]
            if vals:
                cand.append(vals[-1])
    # formato 'NNN G' / 'NNN ML'
    m2 = re.findall(r'(\d+(?:[.,]\d+)?)\s*' + _UNIT + r'\b', u)
    cand += m2
    out = []
    for c in cand:
        try:
            out.append(round(float(c.replace(',', '.')), 1))
        except ValueError:
            pass
    return set(out)


def kw(s):
    u = norm(s)
    u = re.sub(r'\b\d+\s*X\s*\d+(?:\s*X\s*\d+)?\b', ' ', u)   # quitar NxMxK
    u = re.sub(r'\b\d+(?:[.,]\d+)?\s*' + _UNIT + r'\b', ' ', u)  # quitar gramajes
    u = re.sub(r'[^A-Z0-9 ]', ' ', u)
    u = re.sub(r'\b\d+\b', ' ', u)   # quitar numeros sueltos
    return {t for t in u.split() if t and t not in _STOP and len(t) > 1}


def score(desc_kw, desc_g, name_kw, name_g, dn, nn):
    if not desc_kw or not name_kw:
        return 0.0
    inter = len(desc_kw & name_kw)
    if inter == 0:
        return 0.0
    jac = inter / len(desc_kw | name_kw)
    ratio = SequenceMatcher(None, dn, nn).ratio()
    s = 0.55 * jac + 0.25 * ratio
    if desc_g and name_g:
        s += 0.20 if (desc_g & name_g) else -0.05
    return s


def main():
    o = OdooReader()
    rows = list(csv.DictReader(open(SRC, encoding='utf-8-sig'), delimiter=';'))
    print('filas origen:', len(rows))

    prods = o.search_read('product.product', [('default_code', '!=', False)],
                          fields=['default_code', 'name'])
    cat = []
    for p in prods:
        nm = p.get('name') or ''
        cat.append((p['default_code'], nm, kw(nm), gramaje(nm), norm(nm)))
    default_codes = {p['default_code'] for p in prods}
    print('catalogo:', len(cat))

    out = []
    for r in rows:
        cod = r['REFERENCIA_INTERNA']
        desc = r['DESCRIPCION_PROVEEDOR']
        base = {
            'PROVEEDOR': r['PROVEEDOR'],
            'CODIGO_PROVEEDOR': cod,
            'DESCRIPCION_PROVEEDOR': desc,
            'n_facturas': r['n_facturas'],
            'monto_total': r['monto_total'],
        }
        if cod in default_codes:
            nm = next((c[1] for c in cat if c[0] == cod), '')
            out.append({**base, 'CODIGO_INTERNO_PROPUESTO': cod,
                        'NOMBRE_INTERNO_PROPUESTO': nm, 'SCORE': '1,00',
                        'GRAMAJE_OK': 'SI', 'ALT_CODIGO': '', 'ALT_NOMBRE': '',
                        'ALT_SCORE': '', 'confianza': 'CONFIRMADO'})
            continue
        dk, dg, dn = kw(desc), gramaje(desc), norm(desc)
        scored = []
        for code, nm, nk, ng, nn in cat:
            s = score(dk, dg, nk, ng, nn, dn)
            if s > 0:
                scored.append((s, code, nm, bool(dg and ng and (dg & ng))))
        scored.sort(reverse=True)
        top = scored[:2]
        if top:
            s1, c1, n1, g1 = top[0]
            conf = 'ALTA' if s1 >= 0.65 else 'MEDIA' if s1 >= 0.45 else 'BAJA'
            alt = top[1] if len(top) > 1 else (0, '', '', False)
            out.append({**base, 'CODIGO_INTERNO_PROPUESTO': c1,
                        'NOMBRE_INTERNO_PROPUESTO': n1,
                        'SCORE': ('%.2f' % s1).replace('.', ','),
                        'GRAMAJE_OK': 'SI' if g1 else 'NO',
                        'ALT_CODIGO': alt[1], 'ALT_NOMBRE': alt[2],
                        'ALT_SCORE': ('%.2f' % alt[0]).replace('.', ',') if alt[0] else '',
                        'confianza': conf})
        else:
            out.append({**base, 'CODIGO_INTERNO_PROPUESTO': '',
                        'NOMBRE_INTERNO_PROPUESTO': '', 'SCORE': '',
                        'GRAMAJE_OK': '', 'ALT_CODIGO': '', 'ALT_NOMBRE': '',
                        'ALT_SCORE': '', 'confianza': 'SIN_CANDIDATO'})

    cols = ['PROVEEDOR', 'CODIGO_PROVEEDOR', 'DESCRIPCION_PROVEEDOR',
            'CODIGO_INTERNO_PROPUESTO', 'NOMBRE_INTERNO_PROPUESTO', 'SCORE',
            'GRAMAJE_OK', 'ALT_CODIGO', 'ALT_NOMBRE', 'ALT_SCORE', 'confianza',
            'n_facturas', 'monto_total']
    orden = {'CONFIRMADO': 0, 'ALTA': 1, 'MEDIA': 2, 'BAJA': 3, 'SIN_CANDIDATO': 4}
    out.sort(key=lambda r: (orden[r['confianza']], -int(r['n_facturas'])))

    dst = os.path.join(OUT_DIR, 'relacion_codigo_proveedor_interno.csv')
    with open(dst, 'w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=cols, delimiter=';')
        w.writeheader()
        for r in out:
            w.writerow({k: r.get(k, '') for k in cols})

    from collections import Counter
    cc = Counter(r['confianza'] for r in out)
    print('\n=== RESUMEN relacion propuesta ===')
    for k in ['CONFIRMADO', 'ALTA', 'MEDIA', 'BAJA', 'SIN_CANDIDATO']:
        print('  %-14s %d' % (k, cc.get(k, 0)))
    print('archivo:', dst)


if __name__ == '__main__':
    main()
