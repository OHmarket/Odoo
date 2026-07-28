"""test_helpers — tests OFFLINE de helpers.py contra XML reales.

No toca Odoo: usa los fixtures que dejo fetch_fixtures.py en resultados/.

    python proyectos/2026-07-27-cuadre-dte-automatico/test_helpers.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from helpers import (alinear, cuadra_3, dte_totales, exige_sku,  # noqa: E402
                     lineas_sin_sku, motivo, parse_items, price_fixes,
                     tiene_ila_origen, unidad_ok, uom_mal)

TOL = 2.0
FX = json.loads((HERE / 'resultados' / 'fixtures.json').read_text(encoding='utf-8'))
fails = []


def check(nombre, got, exp):
    ok = got == exp
    print('  %-4s %-58s got=%s' % ('OK' if ok else 'FAIL', nombre, got))
    if not ok:
        fails.append('%s: esperado %r, obtenido %r' % (nombre, exp, got))


def xml_de(fac):
    return (HERE / 'resultados' / FX[fac]['xml']).read_text(encoding='utf-8')


def totales_y_gate(fac):
    f = FX[fac]
    t = dte_totales(xml_de(fac))
    return t, cuadra_3(f['amount_untaxed'], f['amount_tax'], f['amount_total'], t, TOL)


print('=' * 74)
print('1. dte_totales — la formula del impuesto (IVA + ImptoReten)')
print('=' * 74)
t = dte_totales(xml_de('FAC 104357157'))
print('   FAC 104357157  DTE: neto=%s exe=%s iva=%s otros=%s total=%s'
      % (t['neto'], t['exe'], t['iva'], t['otros'], t['total']))
print('   Odoo: neto=%s imp=%s total=%s' % (FX['FAC 104357157']['amount_untaxed'],
      FX['FAC 104357157']['amount_tax'], FX['FAC 104357157']['amount_total']))
check('IVA 9480 + ImptoReten 2044 == amount_tax 11524',
      t['iva'] + t['otros'], FX['FAC 104357157']['amount_tax'])
check('MntNeto == amount_untaxed', t['neto'] + t['exe'],
      FX['FAC 104357157']['amount_untaxed'])

print()
print('=' * 74)
print('2. EXENTA — riesgo abierto del diseno §8')
print('=' * 74)
t = dte_totales(xml_de('FAC 5166219'))
f = FX['FAC 5166219']
print('   FAC 5166219  DTE: neto=%s exe=%s -> neto+exe=%s | Odoo untaxed=%s'
      % (t['neto'], t['exe'], t['neto'] + t['exe'], f['amount_untaxed']))
check('MntNeto 4320 + MntExe 9 == amount_untaxed 4329',
      t['neto'] + t['exe'], f['amount_untaxed'])
_, dn, di, dt = cuadra_3(f['amount_untaxed'], f['amount_tax'], f['amount_total'], t, TOL)
check('exenta: el NETO cuadra (no rechaza una factura buena)', dn, False)
print('   nota: total Odoo %s vs DTE %s -> dt=%s (delta +2, justo en el borde de TOL)'
      % (f['amount_total'], t['total'], dt))

print()
print('=' * 74)
print('3. exige_sku — servicio vs mercaderia')
print('=' * 74)
check('Google Workspace (prov Sistemas) NO exige SKU',
      exige_sku('26 Google Workspace', 'Sistemas'), False)
check('mercaderia SI exige SKU',
      exige_sku('WHISKY JW RED', 'Mercaderia'), True)
# regresion 2026-07-27: la cuenta NO puede entrar en la regla. Al recomputarla
# action_update_fpos_values, las lineas sin producto migran a CMV y la regla se
# apagaba justo cuando mas hace falta (13 de 59 lineas se escapaban).
check('Mercaderia con linea en CMV IGUAL exige SKU (era el agujero)',
      exige_sku('VINO SANTA EMA CARMENERE', 'Mercaderia'), True)
check('flete nunca exige SKU', exige_sku('RECARGO', 'Mercaderia'), False)
check('ENVIO CHILEXPRESS no exige SKU', exige_sku('ENVIO CHILEXPRESS', 'Mercaderia'), False)
check('RECARGAS (telefonicas) SI exige SKU: es mercaderia, no un recargo',
      exige_sku('RECARGAS', 'Mercaderia'), True)

for fac, tipo, esp in (('FAC 071682', 'Sistemas', 0),
                       ('FAC 104357155', 'Mercaderia', 1)):
    n = len(lineas_sin_sku(FX[fac]['lineas'], FX[fac]['tipo_proveedor']))
    check('%s (%s): lineas que bloquean == %d' % (fac, tipo, esp), n, esp)

print()
print('=' * 74)
print('4. tiene_ila_origen + motivo')
print('=' * 74)
# Sinteticos a proposito: los fixtures son un snapshot MUTABLE. FAC 104357158
# tenia tax 33 (ILA origen) y el motor ya la posteo aplicando la fpos, asi que
# hoy trae 10. Un test anclado a ese fixture se rompe solo cuando el motor
# hace su trabajo.
check('detecta ILA origen 33', tiene_ila_origen([2, 37, 33]), True)
check('detecta ILA origen 26', tiene_ila_origen([26]), True)
check('impuesto ya mapeado (2, 10) no es origen', tiene_ila_origen([2, 10]), False)
check('sin impuestos no es origen', tiene_ila_origen([]), False)

check("ILA origen gana sobre el gate de montos",
      motivo(False, True, False, True, True, True), 'impuesto_mal_clasificado')
check("falta_sku gana sobre todo",
      motivo(True, True, True, True, True, True), 'codigo_no_vinculado')
check("neto solo -> precio", motivo(False, False, False, True, False, True), 'precio')
check("impuesto solo -> diferencia_impuesto",
      motivo(False, False, False, False, True, True), 'diferencia_impuesto')
check("todo OK -> ''", motivo(False, False, False, False, False, False), '')
# el caso que motiva el gate: la PLATA cuadra y las unidades no.
check("montos OK pero unidades mal -> uom_no_cuadra",
      motivo(False, False, True, False, False, False), 'uom_no_cuadra')

print()
print('=' * 74)
print('4.b gate de unidades — arbitrado por el retail (casos reales medidos)')
print('=' * 74)
# CHOCOLATE SAHNE NUSS: f=20, pu_DTE 5.278, retail 700 -> 7,5x el retail = CAJA
check('pu_DTE 7,5x el retail -> es precio de CAJA, Odoo OK',
      unidad_ok(10, 20, {'qty': 10.0, 'monto': 52780}, 700, 261), True)
# AGUA BENEDICTINO: f=2, pu_DTE 2.165, retail 2.490 -> bajo el retail = UNIDAD
check('pu_DTE bajo el retail -> es precio UNITARIO, Odoo MAL',
      unidad_ok(10, 2, {'qty': 10.0, 'monto': 21650}, 2490, 1422), False)
check('UoM sin pack (factor 1) nunca es sospechosa',
      unidad_ok(12, 1, {'qty': 12.0, 'monto': 1000}, 100, 50), True)
check('unidades ya calzan (qty x factor == QtyItem) -> ok',
      unidad_ok(2, 12, {'qty': 24.0, 'monto': 1000}, 10, 5), True)
check('sin retail cae al costo: pu/f mas cerca del std -> CAJA',
      unidad_ok(10, 12, {'qty': 10.0, 'monto': 120000}, 0, 1000), True)
check('sin retail NI costo -> no verificable (None, no bloquea)',
      unidad_ok(10, 12, {'qty': 10.0, 'monto': 120000}, 0, 0), None)
_p = [({'quantity': 10, 'uom_f': 2, 'retail': 2490, 'std': 1422},
       {'qty': 10.0, 'monto': 21650})]
check('uom_mal() detecta la linea bloqueante', uom_mal(_p), True)
check('uom_mal() con lista vacia (no alineo) no bloquea', uom_mal([]), False)

print()
print('=' * 74)
print('5. alinear + price_fixes — recargo GLOBAL (FAC 10142151)')
print('=' * 74)
f = FX['FAC 10142151']
items = parse_items(xml_de('FAC 10142151'))
ol = [{'id': i, 'name': l['name'], 'quantity': l['quantity'],
       'price_subtotal': l['price_subtotal'], 'factor': 1.0}
      for i, l in enumerate(f['lineas'])]
print('   lineas Odoo=%d   items <Detalle>=%d   (difieren por el recargo global)'
      % (len(ol), len(items)))
check('alinear() empareja las 12 de producto', len(alinear(ol, items)), len(items))
fx = price_fixes(ol, items)
print('   price_fixes propone %d correccion(es):' % len(fx))
tot = 0.0
for (lid, pu) in fx:
    print('      %-34s qty=%-5g pu -> %s' % (ol[lid]['name'][:34], ol[lid]['quantity'], pu))
for (l, it) in alinear(ol, items):
    tot += it['monto']
check('una linea de producto de mas -> NO alinea (no se adivina)',
      len(alinear([{'id': 99, 'name': 'X', 'quantity': 1,
                    'price_subtotal': 0, 'factor': 1.0}] + ol, items)), 0)
# regresion FAC 000891: DESPACHO SI es un <Detalle> (qty 1, monto 145.908).
# alinear() debe intentar PRIMERO tal cual; si saca el flete a ciegas rompe
# una factura de 7 vs 7 que alineaba perfecto.
_ol7 = [{'id': i, 'name': n, 'quantity': 1, 'price_subtotal': 0, 'factor': 1.0}
        for i, n in enumerate(['GIN', 'VODKA', 'DESPACHO'])]
check('flete que SI es Detalle: alinea 3 vs 3',
      len(alinear(_ol7, [{'qty': 1, 'monto': 0}] * 3)), 3)
check('flete que NO es Detalle: alinea 2 vs 2 descontandolo',
      len(alinear(_ol7, [{'qty': 1, 'monto': 0}] * 2)), 2)
check('neto reparado == MntNeto del DTE (1.923.126 + recargo 77.520)',
      tot + 77520, dte_totales(xml_de('FAC 10142151'))['neto'])

print()
print('=' * 74)
print('7. parse_items — precio, descuento y recargo por linea')
print('=' * 74)
_it = parse_items(xml_de('FAC 7471136'))[0]
check('lee PrcItem', _it['prc'], 24984.0)
check('lee DescuentoMonto', _it['desc'], 236880.0)
check('lee RecargoMonto', _it['rec'], 50040.0)
check('MontoItem no cambia', _it['monto'], 187920.0)

print()
print('=' * 74)
print('6. Ciclo completo sobre los fixtures')
print('=' * 74)
print('   %-16s %-12s %-26s %s' % ('factura', 'tipo prov', 'motivo', 'n/i/t'))
for fac in sorted(FX):
    f = FX[fac]
    tt, (ok, dn, di, dt) = totales_y_gate(fac)
    falta = len(lineas_sin_sku(f['lineas'], f['tipo_proveedor'])) > 0
    ila = False
    for l in f['lineas']:
        if tiene_ila_origen(l['tax_ids']):
            ila = True
    mt = motivo(falta, ila, False, dn, di, dt)
    print('   %-16s %-12s %-26s %s%s%s' % (fac, f['tipo_proveedor'][:12],
          mt or 'OK -> se postea', 'N' if dn else '.', 'I' if di else '.',
          'T' if dt else '.'))

print()
if fails:
    print('%d TEST(S) FALLARON:' % len(fails))
    for x in fails:
        print('  - %s' % x)
    sys.exit(1)
print('TODOS LOS TESTS PASARON')
