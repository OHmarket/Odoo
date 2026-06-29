"""DIAG read-only: extrae codigos de producto de los DTE de BAT + su impuesto
adicional (CodImpAdic por linea / ImptoReten del encabezado) para configurar.
Cruza contra default_code del maestro. Salida: bat_codigos_config.csv"""
from __future__ import annotations

import base64
import csv
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader  # noqa: E402

OUT = Path(__file__).resolve().parent / 'resultados'


def _seg(s, o, c):
    a = s.find(o)
    if a == -1:
        return ''
    a += len(o)
    b = s.find(c, a)
    return s[a:b].strip() if b != -1 else ''


def items(xml):
    # tipos de impuesto adicional declarados en el encabezado (ImptoReten TipoImp)
    hdr = []
    i = 0
    while True:
        a = xml.find('<ImptoReten>', i)
        if a == -1:
            break
        b = xml.find('</ImptoReten>', a)
        hdr.append(_seg(xml[a:b], '<TipoImp>', '</TipoImp>'))
        i = b
    out = []
    i = 0
    while True:
        a = xml.find('<Detalle>', i)
        if a == -1:
            break
        b = xml.find('</Detalle>', a)
        if b == -1:
            break
        blk = xml[a:b]
        cod = _seg(blk, '<VlrCodigo>', '</VlrCodigo>')
        nmb = _seg(blk, '<NmbItem>', '</NmbItem>')
        imp = _seg(blk, '<CodImpAdic>', '</CodImpAdic>')
        out.append({'codigo': cod, 'nombre': nmb, 'cod_imp_adic': imp,
                    'hdr_imp': ','.join([h for h in hdr if h])})
        i = b
    return out


def main():
    o = OdooReader()
    moves = o.search_read('account.move',
        [('move_type', '=', 'in_invoice'), ('partner_id.vat', 'like', '88502900'),
         ('invoice_date', '>=', '2026-01-01'), ('l10n_cl_dte_file', '!=', False)],
        ['name', 'l10n_cl_dte_file'])
    att_ids = [m['l10n_cl_dte_file'][0] for m in moves]
    datas = {}
    for i in range(0, len(att_ids), 80):
        for a in o.search_read('ir.attachment', [('id', 'in', att_ids[i:i+80])], ['datas']):
            datas[a['id']] = a['datas']

    agg = {}
    for m in moves:
        raw = datas.get(m['l10n_cl_dte_file'][0])
        if not raw:
            continue
        xml = base64.b64decode(raw).decode('latin-1', 'ignore')
        for it in items(xml):
            if not it['codigo']:
                continue
            k = it['codigo']
            if k not in agg:
                agg[k] = {'nombre': it['nombre'], 'cod_imp_adic': set(),
                          'hdr_imp': set(), 'n': 0, 'fac': set()}
            if it['cod_imp_adic']:
                agg[k]['cod_imp_adic'].add(it['cod_imp_adic'])
            if it['hdr_imp']:
                agg[k]['hdr_imp'].add(it['hdr_imp'])
            agg[k]['n'] += 1
            agg[k]['fac'].add(m['name'])

    # cruce maestro
    codes = list(agg)
    existe = set()
    for i in range(0, len(codes), 80):
        for p in o.search_read('product.product',
                [('default_code', 'in', codes[i:i+80]), ('active', 'in', [True, False])],
                ['default_code']):
            existe.add(p['default_code'])

    rows = []
    for c, v in agg.items():
        rows.append({'codigo_dte': c, 'nombre': v['nombre'],
                     'cod_imp_adic': '|'.join(sorted(v['cod_imp_adic'])),
                     'imp_encabezado': '|'.join(sorted(v['hdr_imp'])),
                     'existe_maestro': 'si' if c in existe else 'no',
                     'n_lineas': v['n'], 'n_facturas': len(v['fac'])})
    rows.sort(key=lambda r: (-r['n_lineas']))
    with open(OUT / 'bat_codigos_config.csv', 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=['codigo_dte', 'nombre', 'cod_imp_adic',
                           'imp_encabezado', 'existe_maestro', 'n_lineas', 'n_facturas'],
                           delimiter=';')
        w.writeheader()
        w.writerows(rows)

    print(f"BAT 2026: {len(moves)} facturas | codigos distintos: {len(rows)}")
    print(f"  en maestro: {sum(1 for r in rows if r['existe_maestro']=='si')} | faltan: {sum(1 for r in rows if r['existe_maestro']=='no')}")
    from collections import Counter
    print("  imp adicional (CodImpAdic) por codigo:", dict(Counter(r['cod_imp_adic'] for r in rows)))
    print(f"\n{'codigo':12} {'imp':6} {'mae':4} {'nombre'}")
    for r in rows[:30]:
        print(f"  {r['codigo']:12} {r['cod_imp_adic']:6} {r['existe_maestro']:4} {r['nombre'][:44]}")


if __name__ == '__main__':
    main()
