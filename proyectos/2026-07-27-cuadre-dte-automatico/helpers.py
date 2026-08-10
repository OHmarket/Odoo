"""helpers v0.10 — funciones PURAS (sin env) del SA OH Cuadre Fiscal DTE.

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

Fixes de review de rama respecto de v0.8 (helpers v0.9), los 3 primeros
critical — cada uno era un camino real por el que se vinculaba el producto
equivocado:
  mapeos_a_aprender()  ya no aprende primer-escritor-gana cuando un nombre
                       aparece 2 veces con product_id distinto en la MISMA
                       factura (centinela, igual que mapeo_por_nombre); exige
                       ademas que coincida la cantidad y descarta items cuyo
                       monto se repite en la factura (guarda de plata ciega a
                       montos iguales)
  mapeo_por_nombre()   agrega la guarda simetrica de codigo: si el DTE trae
                       CdgItem no vincula por nombre (la llave fuerte es el
                       codigo; caso B, fuera de alcance)

Novedades v0.10 (SA v0.13):
  _redondeo_2dec()    redondeo HALF-UP a 2 dec (como la UoM de Odoo, no el
                      banker's de round())
  _es_fraccion_pack() distingue el redondeo benigno de fraccion de pack
                      (qty == round(QtyItem,2)) del error real de cantidad
  price_fixes()       ahora CUADRA la fraccion de pack (antes la excluia): la
                      UoM capa QtyItem a 2 dec y el estructural rompe la
                      historia; el WAC se desvia poco (qty chica, peso bajo)
  unidad_ok()         deja pasar la fraccion de pack (misma cantidad redondeada,
                      no un error de pack 12x)

Novedades v0.11 (SA v0.14):
  uom_fixes()         auto-fix INEQUIVOCO de UoM de pack: cuando qty ya == QtyItem
                      y el arbitro (retail) dice que el stock esta mal, migra la
                      linea a la unidad de referencia (factor 1) del producto. El
                      caso ambiguo (qty != QtyItem) sigue en HOLD.
  estado_texto()      stamp legible para el chatter de la factura (OK / OK tras
                      auto-fix / HOLD con la descripcion del motivo).
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


def normalizar(s):
    """Nombre de item comparable: sin mayusculas ni ruido de espacios.

    `str.split()` sin argumento parte por CUALQUIER whitespace, asi que colapsa
    tambien los \xa0 (nbsp) que traen algunos DTE (verificado en los nombres de
    Santa Ema de LA VINOTECA).

    A proposito NO resuelve abreviaciones ('Hielo 2 k') ni typos ('recragas'):
    esos se mapean a mano una vez y quedan aprendidos como registros aparte. Un
    match difuso resolveria esos dos casos a cambio de poder vincular el producto
    equivocado en silencio, y ese error contamina stock, WAC y margen a la vez.
    """
    return ' '.join((s or '').split()).lower()


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


def mapeos_a_aprender(lineas, items, conocidos):
    """[(line_id, product_id, nombre)] a grabar como mapeo proveedor->producto.

    Solo de lineas que YA tienen producto (alguien las vinculo a mano) y cuyo item
    del DTE vino SIN codigo. El filtro por codigo mantiene el alcance en el caso A
    y evita llenar product.supplierinfo con miles de registros que no hacen falta.

    El nombre NO sale de la linea de Odoo: al vincular, el onchange pisa el `name`
    con el del producto (verificado en FAC 7471136). El nombre del proveedor solo
    sobrevive en el <NmbItem> del XML, que `alinear()` empareja por posicion.

    `conocidos` es un set de nombres YA normalizados. Se devuelve el nombre sin
    normalizar para que quede legible en el catalogo de compras.

    Se devuelve tambien `line_id`: sin el, el llamador tiene que adivinar de que
    linea sacar el precio buscando por product_id, y eso rompe cuando el mismo
    producto aparece dos veces en la misma factura.

    Cuatro guardas antes de aprender un par, todas fallan cerrado:

      1. cantidad: `abs(l['quantity'] - it['qty']) > 0.001` descarta la fraccion
         de pack, igual que `price_fixes`.
      2. montos duplicados EN LA FACTURA: si el mismo `MontoItem` aparece en dos
         <Detalle>, un cruce posicional entre esas dos lineas pasaria la guarda
         de plata igual (los montos calzan de cualquiera de los dos lados) y
         nada lo notaria despues. Se descarta cualquier item cuyo monto se
         repite, antes de mirar nombre o producto.
      3. plata: `price_subtotal == monto`. `alinear()` empareja por POSICION;
         en `price_fixes` un cruce lo atrapa el gate de 3 montos, pero aca no
         hay nada que lo detecte. La comparacion es directa porque el ILA viaja
         en el nodo `<ImptoReten>` del DTE y NO integra el `MontoItem`: verificado
         sobre 22 lineas con ILA de 4 facturas reales, ratio price_subtotal/monto
         = 1.0000 exacto.
      4. conflicto de NOMBRE en la misma factura: si el mismo nombre
         normalizado aparece dos veces apuntando a `product_id` DISTINTOS, no
         se aprende NINGUNO de los dos (mismo centinela que usa
         `mapeo_por_nombre`). Antes ganaba el primer escritor: quedaba un solo
         registro grabado, y la guarda de ambiguedad de `mapeo_por_nombre`
         (que exige DOS registros en conflicto) nunca se enteraba — ese nombre
         quedaba resolviendo siempre al producto equivocado.
    """
    montos_rep = {}
    for it in items:
        montos_rep[it['monto']] = montos_rep.get(it['monto'], 0) + 1
    vistos = {}
    for k in conocidos:
        vistos[k] = True
    cand = {}
    orden = []
    for par in alinear(lineas, items):
        l = par[0]
        it = par[1]
        if not l['has_product']:
            continue
        if it['codigo']:
            continue
        if abs(l['quantity'] - it['qty']) > 0.001:
            continue
        if montos_rep.get(it['monto'], 0) > 1:
            continue
        # Corrobora la alineacion POSICIONAL antes de grabar el par. Sin esto, un
        # emisor que mande el <Detalle> en otro orden haria aprender pares cruzados,
        # y nada los detectaria: los montos no cambian al vincular. Es el riesgo
        # residual que el diseno marca como el mas serio.
        if abs(l['price_subtotal'] - it['monto']) > 1.0:
            continue
        k = normalizar(it['nombre'])
        if not k:
            continue
        if k in vistos:
            continue
        if k in cand:
            if cand[k][0] != l['product_id']:
                cand[k][0] = 0   # conflicto: dos productos para el mismo nombre, no se aprende ninguno
            continue
        cand[k] = [l['product_id'], l['id'], it['nombre']]
        orden.append(k)
    out = []
    for k in orden:
        pid = cand[k][0]
        if not pid:
            continue
        out.append((cand[k][1], pid, cand[k][2]))
    return out


def mapeo_por_nombre(lineas, items, mapeos):
    """[(line_id, product_id)] de lineas SIN producto que matchean UN solo mapeo.

    `mapeos`: [{'nombre', 'product_id'}] del proveedor de la factura.

    Ante ambiguedad NO se vincula: dos mapeos con el mismo nombre normalizado
    apuntando a productos distintos anulan esa entrada. Vincular el producto
    equivocado imputa stock y costo a un SKU que no se compro, y eso contamina
    inventario, WAC y margen a la vez.

    Guarda de alineacion: igual que en `mapeos_a_aprender`, `alinear()` empareja
    por POSICION. Aca no hay monto para corroborar (la linea no tiene producto
    aun), pero el `name` de una linea huerfana TODAVIA es el `NmbItem` del DTE
    (el onchange que lo pisa recien corre al asignar product_id). Por eso se
    exige `normalizar(l['name']) == normalizar(it['nombre'])` antes de vincular:
    si un emisor manda el <Detalle> en otro orden, el pareo cruzado no calza en
    nombre y se descarta, en vez de imputar stock/costo al SKU equivocado.

    Guarda de codigo: simetrica a la de `mapeos_a_aprender` (`if it['codigo']:
    continue`). Si el DTE trae `CdgItem`, esa es la llave FUERTE y resolverla
    es otro proyecto (caso B, fuera de alcance). Vincular por nombre cuando hay
    codigo disponible imputaria el SKU equivocado si el proveedor reusa un
    nombre entre dos codigos (dato real: HDOSO ya empezo a mandar codigo en
    algunas facturas).
    """
    idx = {}
    for mp in mapeos:
        k = normalizar(mp['nombre'])
        if not k:
            continue
        if k in idx:
            if idx[k] != mp['product_id']:
                idx[k] = 0          # 0 = ambiguo, se ignora al consultar
            continue
        idx[k] = mp['product_id']
    out = []
    for par in alinear(lineas, items):
        l = par[0]
        it = par[1]
        if l['has_product']:
            continue
        # Simetrico con mapeos_a_aprender: si el DTE trae CdgItem, la llave fuerte
        # es el codigo y resolverlo es otro proyecto (caso B). Vincular por nombre
        # cuando hay codigo disponible imputaria el SKU equivocado si el proveedor
        # reusa un nombre entre dos codigos.
        if it['codigo']:
            continue
        k = normalizar(it['nombre'])
        pid = idx.get(k, 0)
        if pid:
            # Corrobora el pareo POSICIONAL de alinear(): en una linea huerfana el name
            # de Odoo sigue siendo el NmbItem del DTE (el onchange todavia no lo piso),
            # asi que si no coinciden, el <Detalle> vino en otro orden y no se vincula.
            # Sin esto, un orden distinto asignaria el producto de OTRA linea y el gate
            # de 3 montos no lo veria (precio y cantidad se re-asiertan igual).
            if normalizar(l['name']) != k:
                continue
            out.append((l['id'], pid))
    return out


def _redondeo_2dec(x):
    """Redondeo HALF-UP a 2 decimales, igual que la UoM de Odoo/Postgres.

    NO se usa round() de Python: usa banker's rounding (round(0.125, 2) = 0.12)
    y Odoo guarda 0.13 (medido FAC 104246127: QtyItem 0.125 -> qty 0.13). x es
    siempre positivo (una QtyItem), asi que int(x*100 + 0.5) basta.
    """
    return int(x * 100 + 0.5) / 100.0


def _es_fraccion_pack(qty, qty_dte):
    """True si qty es el redondeo a 2 dec de QtyItem (fraccion de pack capada
    por la UoM), y NO ya iguales (ese es el caso 'pisado', no redondeo).

    Distingue el redondeo benigno (0.166666 -> 0.17, diferencia sub-unitaria)
    del error real de cantidad (pack 12x: qty 12 donde el DTE dice 1), que el
    gate de unidades sigue bloqueando. La UoM guarda 2 decimales, asi que si qty
    == round(QtyItem, 2) la unica variable ajustable es el precio.
    """
    if abs(qty - qty_dte) <= 0.001:
        return False
    return abs(qty - _redondeo_2dec(qty_dte)) < 0.005


def price_fixes(odoo_lines, items):
    """[(line_id, pu_target)] de las lineas con el precio a cuadrar.

    Dos casos, mismo target pu = monto/qty:
      (a) precio PISADO: qty == QtyItem, el maestro piso el price_unit.
      (b) fraccion de PACK: qty == round(QtyItem, 2). La UoM capa QtyItem a 2
          decimales (0.166666 -> 0.17) y qty*pu deja de dar el MontoItem. El
          estructural (subir decimal.precision) rompe la historia, asi que se
          cuadra el precio. Desvia levemente el pu (y el WAC), pero estas
          compras son fraccionarias -> peso bajo en el promedio ponderado.
          Decision de negocio 2026-08-09 (antes se excluia por la trampa UoM).
    Se RECHAZA el resto (diferencia real de cantidad: error de pack, etc.).

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
        if abs(qty - it['qty']) > 0.001 and not _es_fraccion_pack(qty, it['qty']):
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
    # fraccion de pack capada por la UoM (qty == round(QtyItem, 2)): es la MISMA
    # cantidad redondeada, no un error de pack 12x. La diferencia en stock es
    # sub-unitaria (0.17*6 = 1.02 vs 1 botella), no la del gate. Simetrico con
    # price_fixes: la cuadra en plata y aca no la bloquea por unidades.
    if _es_fraccion_pack(qty, it['qty']):
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


def uom_fixes(odoo_lines, items):
    """[(line_id, uom_ref_id, pu_target)] de lineas con UoM de pack a auto-corregir.

    Auto-fix INEQUIVOCO (v0.14): solo cuando migrar de pack a unidad hace que el
    stock sea EXACTAMENTE el QtyItem del DTE. Tres condiciones, todas fallan
    cerrado:

      1. `unidad_ok(...) is False` — el arbitro (retail) dice que la linea entrega
         al stock una cantidad distinta a la del DTE (UoM de pack mal aplicada).
      2. `abs(qty - QtyItem) <= 0.001` — el numero ya calza; lo unico que sobra es
         el multiplicador del pack (Pares x2 / x6). Si qty != QtyItem el error es
         real y AMBIGUO (pack 12x, etc.): queda en HOLD, no se adivina.
      3. `uom_ref_factor == 1` — la unidad de referencia del producto es una
         unidad segura a la que migrar. Si no la hay, no se toca.

    `pu_target = MontoItem/qty * factor`: la plata NO cambia (qty*pu == MontoItem),
    solo se corrige el stock (deja de inflar x2/x6). El SA re-asienta price_unit en
    el MISMO write que cambia product_uom_id, porque cambiar la UoM re-dispara el
    compute que pisa el precio (ver feedback-vincular-product-id-pisa-precio).

    Acotado a proposito al caso inequivoco: preserva el espiritu del gate de
    unidades (bloquear lo dudoso) y solo automatiza donde el resultado es exacto.
    """
    out = []
    for (l, it) in alinear(odoo_lines, items):
        qty = l['quantity']
        if qty == 0:
            continue
        if unidad_ok(qty, l['uom_f'], it, l['retail'], l['std']) is not False:
            continue
        if abs(qty - it['qty']) > 0.001:
            continue
        if l['uom_ref_factor'] != 1:
            continue
        out.append((l['id'], l['uom_ref_id'], round((it['monto'] / qty) * l['factor'], 2)))
    return out


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


# --- 5. estado legible para el chatter (v0.14) ------------------------------

# Descripcion corta por codigo de motivo (la seleccion de x_error_dte). Sirve
# para que el stamp del chatter sea legible sin abrir el detalle por linea.
MOTIVO_DESC = {
    'codigo_no_vinculado': 'codigo(s) sin vincular',
    'impuesto_mal_clasificado': 'impuesto (ILA) sin re-mapear',
    'uom_no_cuadra': 'UoM no calza (cantidad al stock erronea)',
    'linea_descuadrada': 'neto e impuesto descuadran vs XML',
    'precio': 'precio (neto) descuadra vs XML',
    'diferencia_impuesto': 'impuesto descuadra vs XML',
}


def estado_texto(motivo_code, n_uom_fix):
    """Stamp legible para el chatter de la factura (v0.14).

    Tres estados:
      - OK sin fix           -> 'validado vs XML + UoM validado'
      - OK tras auto-fix UoM -> agrega '(pack->unidad, N linea/s)'
      - HOLD                 -> la descripcion corta del motivo (MOTIVO_DESC)

    La fecha la pone el chatter. La idempotencia (no re-postear el mismo texto en
    cada corrida del cron) la maneja el SA comparando con el ultimo mensaje
    'Cuadre DTE' de la factura.
    """
    if motivo_code:
        desc = MOTIVO_DESC.get(motivo_code, motivo_code)
        return 'Cuadre DTE HOLD - ' + desc
    if n_uom_fix:
        return ('Cuadre DTE OK - validado vs XML + UoM auto-corregida '
                '(pack->unidad, %d linea/s)' % n_uom_fix)
    return 'Cuadre DTE OK - validado vs XML + UoM validado'
