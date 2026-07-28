"""helpers v0.8 — funciones PURAS (sin env) del SA OH Cuadre Fiscal DTE.

Se testean local con `python test_helpers.py` (sin Odoo) y se copian
literalmente dentro del Server Action safe_eval. Fuente de verdad testeada.

Restricciones safe_eval respetadas (ver skill odoo-server-action-safe-eval):
  - sin `import` y sin `re`: el parseo es por `str.find` (igual que v0.6/1585)
  - sin `frozenset` (NO esta en los builtins permitidos): se usan tuplas
  - loops planos, sin genexp/lambda dentro de un `def` (riesgo MAKE_CELL)
  - sin `getattr`/`obj.attr = x`

Novedades respecto de los helpers de v0.6:
  dte_totales()  los 3 montos del DTE, no solo MntTotal
  cuadra_3()     gate de neto / impuesto / total por separado
  exige_sku()    la regla de SKU acotada a mercaderia
  motivo()       clasificacion con ILA-origen ANTES del gate de montos

Novedades respecto de v0.7 (helpers v0.8):
  recargo_embebido()  detecta el flete DENTRO del MontoItem (Peumo) via
                      identidad prc*qty-desc+rec==monto; todo-o-nada
  price_fixes()       resta el recargo embebido de la base ANTES de
                      comparar contra price_subtotal (si no, el fix de
                      precio pisado infla el neto con el flete incluido)
"""

# --- parseo basico (identico a v0.6, se repite para que el archivo sea autonomo) ---


def _seg(s, o, c):
    a = s.find(o)
    if a == -1:
        return ''
    a += len(o)
    b = s.find(c, a)
    return s[a:b].strip() if b != -1 else ''


def _num(t):
    try:
        return float(t)
    except Exception:
        return 0.0


# --- 1. totales del DTE ------------------------------------------------------

def dte_totales(xml):
    """Los montos del DTE -> {neto, exe, iva, otros, total}.

    `otros` suma TODOS los <ImptoReten> (ILA, IABA, etc): Odoo los acumula en
    amount_tax junto al IVA, el DTE los lleva aparte. Verificado en
    FAC 104357157: IVA 9.480 + ImptoReten 2.044 = 11.524 = amount_tax.

    En una factura exenta (FNA) <MntNeto> viene vacio y el monto va en
    <MntExe>: por eso el neto comparable es neto + exe (FAC 5166219).
    """
    tot = _seg(xml, '<Totales>', '</Totales>')
    otros = 0.0
    i = 0
    while True:
        a = xml.find('<ImptoReten>', i)
        if a == -1:
            break
        b = xml.find('</ImptoReten>', a)
        if b == -1:
            break
        otros += _num(_seg(xml[a:b], '<MontoImp>', '</MontoImp>'))
        i = b
    return {'neto': _num(_seg(tot, '<MntNeto>', '</MntNeto>')),
            'exe': _num(_seg(tot, '<MntExe>', '</MntExe>')),
            'iva': _num(_seg(tot, '<IVA>', '</IVA>')),
            'otros': otros,
            'total': _num(_seg(tot, '<MntTotal>', '</MntTotal>'))}


def parse_items(xml):
    """DTE -> lista de items EN ORDEN: nombre/codigo/ean/qty/monto/prc/desc/rec.

    prc/desc/rec (v0.8) permiten reconstruir la identidad de la linea y detectar
    el recargo embebido: prc*qty - desc + rec == monto. Ver recargo_embebido().
    """
    items = []
    i = 0
    while True:
        a = xml.find('<Detalle>', i)
        if a == -1:
            break
        b = xml.find('</Detalle>', a)
        if b == -1:
            break
        blk = xml[a:b]
        cod = ''
        ean = ''
        j = 0
        while True:
            ca = blk.find('<CdgItem>', j)
            if ca == -1:
                break
            cb = blk.find('</CdgItem>', ca)
            cblk = blk[ca:cb]
            tpo = _seg(cblk, '<TpoCodigo>', '</TpoCodigo>')
            vlr = _seg(cblk, '<VlrCodigo>', '</VlrCodigo>')
            if vlr:
                if 'EAN' in tpo.upper():
                    ean = vlr
                elif not cod:
                    cod = vlr
            j = cb
        items.append({'nombre': _seg(blk, '<NmbItem>', '</NmbItem>'),
                      'codigo': cod, 'ean': ean,
                      'qty': _num(_seg(blk, '<QtyItem>', '</QtyItem>')),
                      'monto': _num(_seg(blk, '<MontoItem>', '</MontoItem>')),
                      'prc': _num(_seg(blk, '<PrcItem>', '</PrcItem>')),
                      'desc': _num(_seg(blk, '<DescuentoMonto>', '</DescuentoMonto>')),
                      'rec': _num(_seg(blk, '<RecargoMonto>', '</RecargoMonto>'))})
        i = b
    return items


def recargo_embebido(items):
    """Total del RecargoMonto cuando viene DENTRO del MontoItem (0 si no).

    Algunos emisores (Comercial Peumo) suman el flete al MontoItem de cada
    linea. Ese recargo es afecto a IVA pero NO integra la base del ILA, asi que
    cobrarlo dentro del precio del producto infla el impuesto. Medido en
    FAC 7471135: 515.736 de flete -> 105.726 de ILA de mas.

    Otros (Embonor) lo mandan aparte y su MontoItem ya viene limpio: ahi no hay
    nada que restar. La diferencia se decide por la identidad de la linea, NO
    por una lista de proveedores (ver [[feedback-evitar-casuisticas]]):

        prc * qty - desc + rec == monto   -> el recargo esta DENTRO

    Todo-o-nada: si alguna linea no trae recargo o no cierra la identidad,
    devuelve 0 y la factura cae al hold de siempre. Falla cerrado.
    """
    if not items:
        return 0.0
    tot = 0.0
    for it in items:
        if not it['rec']:
            return 0.0
        if abs(it['prc'] * it['qty'] - it['desc'] + it['rec'] - it['monto']) > 1.0:
            return 0.0
        tot += it['rec']
    return tot


# --- 2. gate de cuadre de 3 componentes -------------------------------------

def cuadra_3(untaxed, tax, total, tot, tol):
    """(ok, dn, di, dt): cada d* True = ESE componente NO cuadra.

        amount_untaxed == MntNeto + MntExe
        amount_tax     == IVA + sum(ImptoReten.MontoImp)
        amount_total   == MntTotal

    Comparar solo el total deja pasar errores que se compensan entre neto e
    impuesto; por eso se exigen los tres.
    """
    dn = abs(untaxed - (tot['neto'] + tot['exe'])) > tol
    di = abs(tax - (tot['iva'] + tot['otros'])) > tol
    dt = abs(total - tot['total']) > tol
    return ((not dn) and (not di) and (not dt), dn, di, dt)


# --- 3. regla de SKU: solo mercaderia ---------------------------------------

# Palabras que marcan una linea como flete/cargo (no producto, sin SKU legitimo).
# 'envio' agregado 2026-07-27 (ENVIO CHILEXPRESS en FAC 003666). OJO: 'recargo'
# NO matchea 'RECARGAS' (recargas telefonicas = mercaderia que se vende), y esta
# bien que asi sea.
FLETE = ('flete', 'transport', 'despacho', 'reparto', 'acarreo', 'delivery',
         'recargo', 'cargo por', 'envio')

TIPO_MERCADERIA = 'Mercaderia'


def _es_flete(n):
    nl = (n or '').lower()
    for t in FLETE:
        if t in nl:
            return True
    return False


def exige_sku(name, tipo_prov):
    """True si ESTA linea debe tener product_id para poder postear.

    Decide SOLO por el tipo de proveedor. NO se mira la cuenta contable: la
    cuenta de inventario (210230) sale de la categoria DEL PRODUCTO, asi que
    una linea sin producto nunca puede estar ahi — cae al gasto (410235/6 CMV).
    Condicionar la regla a la cuenta era circular: testeaba una consecuencia de
    tener producto.

    Lo destapo la corrida real del 2026-07-27: action_update_fpos_values
    actualiza impuestos Y CUENTAS, y al recomputarlas las lineas sin producto
    migraron de 210230 a CMV, apagando la regla. Medido: 13 de 59 lineas de
    mercaderia sin vincular estaban en CMV y se escapaban del bloqueo.
    """
    if _es_flete(name):
        return False
    return tipo_prov == TIPO_MERCADERIA


def lineas_sin_sku(lineas, tipo_prov):
    """Lineas que bloquean el posteo por falta de producto.
    lineas: dicts {'name','has_product'}. Loop plano a proposito."""
    out = []
    for l in lineas:
        if l['has_product']:
            continue
        if exige_sku(l['name'], tipo_prov):
            out.append(l)
    return out


# --- 3.b alineacion lineas Odoo <-> items del DTE ---------------------------

def alinear(odoo_lines, items):
    """Empareja lineas de Odoo con items del <Detalle> -> [(linea, item), ...].

    Las lineas de flete/recargo NO tienen item: el DTE las lleva como
    <DscRcgGlobal> (recargo global), no como <Detalle>. Por eso se descuentan
    antes de comparar los largos.

    Verificado en FAC 10142151: 13 lineas Odoo vs 12 <Detalle>, y el
    <DscRcgGlobal> de 77.520 es exactamente la linea RECARGO
    (MntNeto 2.000.646 = suma MontoItem 1.923.126 + 77.520).

    Antes se comparaba `len(odoo_lines) != len(items)` y se abortaba: cualquier
    factura con recargo global quedaba SIN fix de precio, aunque sus lineas
    fueran reparables.

    Dos intentos, en orden — el flete NO siempre es un recargo global:
      1. tal cual, si los largos ya calzan. En FAC 000891 la linea DESPACHO SI
         es un <Detalle> (qty 1, monto 145.908) y son 7 vs 7: sacarla a ciegas
         rompia una factura que alineaba perfecto.
      2. descontando flete/recargo, para el caso <DscRcgGlobal> (FAC 10142151).

    Devuelve [] si ninguno calza: no se adivina el emparejamiento.
    """
    if not items:
        return []
    if len(odoo_lines) == len(items):
        return list(zip(odoo_lines, items))
    prod = []
    for l in odoo_lines:
        if not _es_flete(l['name']):
            prod.append(l)
    if len(prod) != len(items):
        return []
    return list(zip(prod, items))


def price_fixes(odoo_lines, items):
    """[(line_id, pu_target)] de las lineas con el precio pisado.

    Excluye a proposito la fraccion de pack (qty != QtyItem): ahi el
    price_unit YA es el correcto del DTE y desviarlo contaminaria costo/WAC
    (trampa UoM).

    v0.8: si el DTE trae el flete DENTRO del MontoItem (ver recargo_embebido),
    la base de la linea es monto - rec. Cobrar el flete dentro del precio del
    producto lo mete en la base del ILA e infla el impuesto. El SA compensa
    creando una linea de flete aparte por el total.
    """
    rec_emb = recargo_embebido(items)
    out = []
    for (l, it) in alinear(odoo_lines, items):
        qty = l['quantity']
        if qty == 0:
            continue
        if abs(qty - it['qty']) > 0.001:
            continue
        monto = it['monto']
        if rec_emb:
            monto = monto - it['rec']
        if abs(l['price_subtotal'] - monto) <= 1.0:
            continue
        out.append((l['id'], round((monto / qty) * l['factor'], 2)))
    return out


# --- 3.c gate de unidades (UoM) ---------------------------------------------

def unidad_ok(qty, uom_f, it, retail, std):
    """True / False / None (None = no se puede verificar, no bloquea).

    El problema: una linea puede cuadrar en PLATA y aun asi entregar al stock
    una cantidad equivocada, porque la UoM de la linea es un pack. Ej medido
    (FAC 10142151): qty=12 con UoM "x 12 Unidades" -> 144 botellas al inventario
    cuando el DTE dice 12, a 1/12 del costo. El gate de 3 montos es ciego a eso.

    Lo dificil es que `QtyItem` NO siempre viene en unidades de stock: medido
    sobre 2.212 lineas, el 63% de los DTE factura POR CAJA (y ahi Odoo con UoM
    de caja esta BIEN). Comparar `qty * factor == QtyItem` a secas daba 63% de
    falsos positivos.

    El arbitro es el PRECIO DE VENTA, no el costo: `standard_price` se deriva de
    estas mismas compras (si el historico entro mal, el costo esta contaminado y
    el arbitro se contamina con el). `list_price` no viene de las compras.
    Base economica: el costo por unidad no puede superar el precio de venta por
    unidad. Si `MontoItem/QtyItem` > retail, ese precio es de CAJA.

    PROXY: lo correcto seria costo < retail * (1 - margen) usando el margen por
    categoria; se usa el retail pelado por simplicidad. Con eso marca 5,3% de
    las lineas (117 de 2.212) y la cobertura de verificacion fue del 100%.
    """
    if uom_f == 1 or not it['qty']:
        return True
    if abs(qty * uom_f - it['qty']) <= 0.01:
        return True
    pu = it['monto'] / it['qty']
    if retail:
        return pu > retail
    if std:
        return abs(pu / uom_f - std) < abs(pu - std)
    return None


def uom_mal(pares):
    """True si alguna linea aporta al stock una cantidad distinta a la del DTE.
    `pares` = salida de alinear(). Lo no verificable NO bloquea (loop plano)."""
    for (l, it) in pares:
        if unidad_ok(l['quantity'], l['uom_f'], it, l['retail'], l['std']) is False:
            return True
    return False


# --- 4. clasificacion del motivo --------------------------------------------

# Impuestos ORIGEN "Compra (OC)" de la posicion fiscal 12. Si una linea aun los
# carga, action_update_fpos_values todavia no corrio sobre ella.
SRC_OC = (26, 28, 31, 33, 34)


def tiene_ila_origen(tax_ids):
    """True si la linea todavia carga un impuesto ORIGEN sin mapear."""
    for t in tax_ids:
        if t in SRC_OC:
            return True
    return False


def motivo(falta_sku, ila_origen, unidades_mal, dn, di, dt):
    """Motivo por el que la factura NO se postea ('' si esta OK).

    El orden importa:

    - El impuesto ORIGEN se evalua ANTES del gate de montos. Medido 2026-07-27:
      de 163 facturas que el gate marcaba como estructura, 155 tenian ILA
      origen. Como el impuesto origen es price_include, mueve neto E impuesto a
      la vez y disfraza el diagnostico.
    - Las UNIDADES se evaluan antes que los montos y, sobre todo, antes de
      devolver '': una factura puede cuadrar perfecto en plata y aun asi
      entregar al stock 12x las unidades (ver unidad_ok). Si se chequeara
      despues del gate de montos nunca se alcanzaria en el caso que importa.

    Devuelve valores de la seleccion ya existente en x_error_dte.
    """
    if falta_sku:
        return 'codigo_no_vinculado'
    if ila_origen:
        return 'impuesto_mal_clasificado'
    if unidades_mal:
        return 'uom_no_cuadra'
    if dn and di:
        return 'linea_descuadrada'
    if dn:
        return 'precio'
    if di:
        return 'diferencia_impuesto'
    if dt:
        return 'linea_descuadrada'
    return ''
