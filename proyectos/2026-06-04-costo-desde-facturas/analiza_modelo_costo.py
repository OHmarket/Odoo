"""
analiza_modelo_costo.py — READ-ONLY.

Analiza x_vendor_bill_cost_lin (poblado por "OH Costo desde Facturas") para revisar:
  - estado del modelo (filas, rango de fechas, campos presentes/ausentes)
  - cobertura de raw_snapshot (comparar factura vs maestro)
  - consistencia: ratio costo bruto (con IVA) vs raw_product_price (que es bruto)
  - EVOLUCION de precio por codigo: primer vs ultimo neto unitario, % cambio
  - flete asignado y cuello de mapeo (lineas sin default_code)

Neto unitario = x_studio_line_net / x_studio_qty_units_equiv (derivado; no depende
de que el campo nuevo unit_net exista). Emite resumen por consola + CSV es-CL.

Uso (desde la raiz del repo):
    python proyectos/2026-06-04-costo-desde-facturas/analiza_modelo_costo.py
"""

import sys
from collections import defaultdict

sys.path.insert(0, '.')
from shared.odoo_xmlrpc import OdooReader

MODEL = 'x_vendor_bill_cost_lin'
OUT_CSV = 'proyectos/2026-06-04-costo-desde-facturas/resultados/evolucion_por_codigo.csv'


def f(v):
    try:
        return float(v or 0.0)
    except Exception:
        return 0.0


def m2o_id(v):
    return v[0] if isinstance(v, (list, tuple)) and v else None


def m2o_name(v):
    return v[1] if isinstance(v, (list, tuple)) and len(v) > 1 else ''


def main():
    o = OdooReader()
    have = set(o.fields_get(MODEL, ['type']).keys())

    want = ['x_studio_doc_date', 'x_studio_default_code', 'x_studio_product_id',
            'x_studio_partner_id', 'x_studio_line_net', 'x_studio_qty_units_equiv',
            'x_studio_unit_net', 'x_studio_unit_gross_no_freight',
            'x_studio_unit_gross_with_freight', 'x_studio_total_gross_with_freight',
            'x_studio_vat_amount', 'x_studio_ila_amount', 'x_studio_freight_alloc_net',
            'x_studio_raw_snapshot', 'x_studio_std_snapshot']
    fields = ['id'] + [c for c in want if c in have]
    missing = [c for c in want if c not in have]

    n = o.search_count(MODEL, [])
    print("=" * 64)
    print("MODELO %s | filas = %s" % (MODEL, n))
    if missing:
        print("CAMPOS AUSENTES (no creados en Studio): %s" % ', '.join(missing))
    else:
        print("CAMPOS: los 4 nuevos presentes OK")
    if n == 0:
        print("(modelo vacio — nada que analizar)")
        return
    if n > 60000:
        print("AVISO: %s filas, trayendo igual (puede tardar)." % n)

    rows = o.search_read(MODEL, [], fields=fields,
                         order='x_studio_doc_date asc, id asc')

    has_raw = 'x_studio_raw_snapshot' in have
    has_code = 'x_studio_default_code' in have
    has_unit_net = 'x_studio_unit_net' in have

    # UoM dudosa derivada de std_snapshot (funciona aunque el run no haya aplicado
    # el ancla): neto unitario que se desvia >15% del standard_price.
    def is_dudosa(r):
        std = f(r.get('x_studio_std_snapshot'))
        ueq = f(r.get('x_studio_qty_units_equiv'))
        net = f(r.get('x_studio_line_net'))
        if std > 0 and ueq > 0:
            return abs((net / ueq) - std) / std > 0.15
        return False

    # equivalente raw factura = neto+IVA+ILA+FLETE por unidad (raw INCLUYE flete).
    # total_gross_with_freight = gross_no_freight + flete_bruto asignado (por linea).
    def equiv_raw(r):
        ueq = f(r.get('x_studio_qty_units_equiv'))
        tg = f(r.get('x_studio_total_gross_with_freight'))
        if ueq > 0 and tg > 0:
            return tg / ueq
        return f(r.get('x_studio_unit_gross_no_freight'))  # fallback unitario (sin flete)

    # ---- agregados globales ----
    dates = [r.get('x_studio_doc_date') for r in rows if r.get('x_studio_doc_date')]
    d_min, d_max = (min(dates), max(dates)) if dates else ('?', '?')
    partners = {m2o_id(r.get('x_studio_partner_id')) for r in rows}
    partners.discard(None)
    prods = {m2o_id(r.get('x_studio_product_id')) for r in rows}
    prods.discard(None)

    sin_code = sum(1 for r in rows if not (r.get('x_studio_default_code') or '').strip()) if has_code else None
    con_flete = sum(1 for r in rows if f(r.get('x_studio_freight_alloc_net')) > 0)
    flete_sum = sum(f(r.get('x_studio_freight_alloc_net')) for r in rows)

    print("rango fechas : %s .. %s" % (d_min, d_max))
    print("proveedores  : %s | productos: %s" % (len(partners), len(prods)))
    print("lineas c/flete: %s | flete neto total asignado: %.0f" % (con_flete, flete_sum))
    if has_code:
        print("lineas SIN default_code (cuello mapeo): %s (%.0f%%)" % (sin_code, 100.0 * sin_code / n))
    n_dudosa = sum(1 for r in rows if is_dudosa(r))
    print("lineas UoM DUDOSA (|net/u - std| > 15%%): %s (%.0f%%)" % (n_dudosa, 100.0 * n_dudosa / n))

    # ---- consistencia vs raw (bruto con IVA): unit_gross_no_freight / raw ----
    if has_raw:
        b_ok = b_hi = b_lo = b_noraw = 0
        for r in rows:
            raw = f(r.get('x_studio_raw_snapshot'))
            gross_u = equiv_raw(r)
            if raw <= 0:
                b_noraw += 1
                continue
            if gross_u <= 0:
                continue
            ratio = gross_u / raw
            if 0.9 <= ratio <= 1.1:
                b_ok += 1
            elif ratio > 1.1:
                b_hi += 1
            else:
                b_lo += 1
        print("\n-- consistencia equiv_raw (neto+IVA+ILA+flete) vs raw_snapshot --")
        print("OK 0.9-1.1: %s | >1.1: %s | <0.9: %s | raw=0: %s" % (b_ok, b_hi, b_lo, b_noraw))

    # ---- evolucion por codigo (neto unitario derivado) ----
    def key_of(r):
        if has_code:
            c = (r.get('x_studio_default_code') or '').strip()
            if c:
                return c
        pid = m2o_id(r.get('x_studio_product_id'))
        return ('PID:%s' % pid) if pid else None

    # equivalente raw factura = bruto unitario con IVA+ILA (sin flete) = comparable
    # DIRECTO con raw_product_price (que tambien es bruto). NO se usa el neto.
    series = defaultdict(list)  # key -> [(date, equiv_raw, name, raw)]  (excluye dudosas)
    for r in rows:
        if is_dudosa(r):
            continue
        k = key_of(r)
        if not k:
            continue
        eq = equiv_raw(r)
        if eq <= 0:
            continue
        series[k].append((
            r.get('x_studio_doc_date') or '',
            eq,
            m2o_name(r.get('x_studio_product_id'))[:34],
            f(r.get('x_studio_raw_snapshot')) if has_raw else 0.0,
        ))

    multi = {k: sorted(v) for k, v in series.items() if len({x[0] for x in v}) >= 2}
    print("\n-- evolucion EQUIVALENTE RAW factura (bruto c/IVA+ILA) vs raw; EXCLUYE UoM dudosa --")
    print("codigos con compra: %s | con >=2 fechas (evolucion medible): %s"
          % (len(series), len(multi)))

    changes = []
    for k, v in multi.items():
        first, last = v[0], v[-1]
        p0, p1 = first[1], last[1]
        if p0 <= 0:
            continue
        pct = 100.0 * (p1 - p0) / p0
        changes.append((pct, k, last[2], p0, p1, first[0], last[0], len(v), last[3]))

    stable = sum(1 for c in changes if abs(c[0]) <= 2.0)
    up = sum(1 for c in changes if c[0] > 2.0)
    down = sum(1 for c in changes if c[0] < -2.0)
    print("estables(+/-2%%): %s | subieron(>2%%): %s | bajaron(<-2%%): %s" % (stable, up, down))

    changes.sort(reverse=True)
    def _gap(p1, raw):
        return (100.0 * (p1 - raw) / raw) if raw > 0 else 0.0
    def _show(title, items):
        print("\n%s" % title)
        for pct, k, name, p0, p1, d0, d1, nn, raw in items:
            print("  %-10s %-30s %+7.1f%%  equiv %7.0f->%7.0f  raw=%7.0f  gapU=%+6.1f%%  (%sx)"
                  % (k, name[:30], pct, p0, p1, raw, _gap(p1, raw), nn))
    _show("TOP 12 SUBIDAS (equiv raw):", changes[:12])
    _show("TOP 12 BAJADAS (equiv raw):", list(reversed(changes[-12:])) if len(changes) >= 12 else [])

    # raw mas desalineado HOY: |gap ultimo equiv vs raw| mayor (raw a corregir)
    by_gap = sorted([c for c in changes if c[8] > 0], key=lambda c: -abs(_gap(c[4], c[8])))
    print("\nTOP 12 RAW MAS DESALINEADO (ultimo equiv vs raw):")
    for pct, k, name, p0, p1, d0, d1, nn, raw in by_gap[:12]:
        print("  %-10s %-30s equiv_ult %7.0f  raw %7.0f  gap %+6.1f%%  (%sx)"
              % (k, name[:30], p1, raw, _gap(p1, raw), nn))

    # ---- CSV es-CL ----
    try:
        import os
        os.makedirs(os.path.dirname(OUT_CSV), exist_ok=True)
        lines = ["codigo;producto;n_compras;fecha_min;fecha_max;equiv_raw_primero;equiv_raw_ultimo;pct_cambio;raw_actual;gap_ultimo_vs_raw_pct"]
        for pct, k, name, p0, p1, d0, d1, nn, raw in changes:
            gap = (100.0 * (p1 - raw) / raw) if raw > 0 else 0.0
            lines.append("%s;%s;%s;%s;%s;%s;%s;%s;%s;%s" % (
                k, name.replace(';', ','), nn, d0, d1,
                ("%.0f" % p0).replace('.', ','), ("%.0f" % p1).replace('.', ','),
                ("%.1f" % pct).replace('.', ','), ("%.0f" % raw).replace('.', ','),
                ("%.1f" % gap).replace('.', ',')))
        with open(OUT_CSV, 'w', encoding='utf-8-sig') as fh:
            fh.write("\n".join(lines))
        print("\nCSV evolucion: %s (%s codigos)" % (OUT_CSV, len(changes)))
    except Exception as e:
        print("\n(no se pudo escribir CSV: %s)" % e)


if __name__ == '__main__':
    main()
