# OH Cuadre Fiscal DTE v0.17  (ir.actions.server / account.move / safe_eval)
#
# Diferencias con v0.16:
#   1. PASO 1.6: especifico diesel NO recuperable (combustible, CodImpAdic 28,
#      Ley 18.502). Copec/G&G ('Petroleo') netean el Impuesto Especifico Diesel
#      del total a pagar -> el DTE trae neto+IVA > MntTotal y el <ImptoReten>
#      cod 28 viene buggeado en $1; el gap real (Odoo_total - MntTotal) ES el
#      especifico (medido FAC 31908071: 2.468; 256280: 10.287; 370012: 810). OH lo
#      CONSUME para mover la logistica (vehiculos en via publica) y NO lo recupera
#      (no aplica art.7 Ley 18.502 -uso no vehicular- ni tramo Ley 19.764
#      -transporte de carga-) -> el especifico es COSTO. En el MISMO savepoint
#      (todo-o-nada) se hace: (a) el fix de precio del PASO 1.5 -el diesel viene
#      con QtyItem de 3 decimales (ej 14.663) que la UoM capa a 14.66 y deja el
#      neto corto por unos pesos; sin este fix PASO 1.5 lo revierte solo porque el
#      total aun no cuadra por el especifico (deadlock)- y (b) una linea de ajuste
#      -esp SIN impuesto a la cuenta de gasto del combustible, dejando el IVA
#      credito (19% del neto) intacto. El neto esperado baja en esp (el especifico
#      reduce el gasto): el gate cuadra neto-esp / IVA / MntTotal. Idempotente
#      (marca NOMBRE_ESPECIFICO). Espejo del PASO 1.7 (tabaco) con el signo del gap
#      invertido (alli el ImptoReten SUMA al total, aca RESTA). Helper puro nuevo:
#      tiene_especifico_diesel(xml).
#
# Diferencias con v0.15:
#   1. PASO 1.9: cuadre fino del IVA al DTE, DENTRO del savepoint del margen
#      (PASO 1.7). El IVA 19% que Odoo suma por linea difiere del <IVA> del DTE
#      por unos pesos de redondeo en facturas de muchas lineas; ese residuo hacia
#      que cuadra_3 fallara TRAS ajustar el margen y el savepoint revirtiera el
#      ajuste de margen CORRECTO -> la factura de BAT quedaba en hold eterno
#      (medido FAC 17197644: +3 de IVA, total 13.961.426 vs DTE 13.961.423). Ahora
#      se lleva la linea de IVA a tot['iva'] (solo amount_currency, Odoo re-balancea)
#      si el residuo es <= TOL_IVA (redondeo); un descuadre grande de IVA NO se toca.
#
# Automatiza el ciclo manual, por factura:
#     APLICAR posicion fiscal -> REVISAR -> GUARDAR -> siguiente
#
#   PASO 0   selecciona las draft con DTE desde la MAS ANTIGUA hasta fin del mes
#            en curso, SIN hold vigente en x_error_dte,
#            ordenadas por id DESC (mas recientes primero). Cap MAX_MOVES.
#   PASO 1   aplica la posicion fiscal SIEMPRE (action_update_fpos_values),
#            no solo si ya descuadra.
#   PASO 1.5 cuadra el precio: lineas con el pu PISADO (qty == QtyItem) y las de
#            FRACCION DE PACK (qty == round(QtyItem, 2), la UoM capa la fraccion;
#            v0.13). Todo-o-nada via SAVEPOINT: solo persiste si tras el fix la
#            factura entera cuadra. La diferencia REAL de cantidad se excluye.
#   PASO 2   REVISA: (a) lineas de MERCADERIA sin producto  (b) neto
#            (c) impuesto  (d) total  — los tres montos contra el DTE.
#   PASO 3   GUARDA (action_post) las limpias; a las demas les registra un hold
#            en x_error_dte con el motivo y sigue con la proxima.
#
# Diferencias con v0.6 (7 cambios, ver proyectos/2026-07-27-cuadre-dte-automatico/):
#   1. orden id DESC + excluye holds vigentes  (v0.6 ordenaba ASC -> arrancaba
#      por las mas viejas, que son las pegadas: 0 posteadas en 2 semanas)
#   2. BATCH -> MAX_MOVES (cap de COSTO, no de cola)
#   3. fpos SIEMPRE, no solo si delta > TOL (168 facturas nunca la recibian)
#   4. gate de 3 montos, no solo MntTotal (errores compensados pasaban)
#   5. motivo con ILA-origen ANTES del gate de montos (medido: 155 de 163
#      "estructura" eran en realidad ILA sin mapear; price_include mueve
#      neto E impuesto a la vez y disfraza el diagnostico)
#   6. sku_ok acotado a lineas de MERCADERIA (tipo_proveedor + cuenta 210230):
#      las de gasto son servicios legitimos sin SKU
#   7. registra el hold en x_error_dte (reusa el modelo del detector 1585)
#
# Diferencias con v0.7:
#   1. recargo EMBEBIDO en el MontoItem (Peumo): el flete sale del precio del
#      producto y va a una linea propia (cuenta 410237, solo IVA). Sin esto el
#      flete entra en la base del ILA e infla el impuesto (medido: 105.726 en
#      FAC 7471135). Deteccion aritmetica: prc*qty - desc + rec == monto.
#   2. POST_RECARGO=False: esas facturas quedan en draft para revision manual.
#
# Diferencias con v0.8:
#   1. APRENDER_MAPEOS: al postear una factura limpia graba en product.supplierinfo
#      el mapeo (proveedor, NmbItem del DTE) -> producto, solo de las lineas que el
#      DTE mando SIN CdgItem. El nombre sale del XML: al vincular, el onchange pisa
#      el `name` de la linea.
#   2. VINCULAR_MAPEOS: PASO 1.2, usa esos mapeos para vincular las lineas huerfanas
#      re-asertando precio y cantidad en el MISMO write.
#
# Diferencias con v0.9:
#   1. EXCLUIR_TABACO=False: BAT vuelve al universo. El descuadre NO era el IVA de
#      margen sino que sus lineas cargaban TRES IVA del 19% (2 + 28-origen + 17)
#      por no recibir NUNCA la posicion fiscal. El maestro esta bien (solo el 17).
#      Con la fpos aplicada el neto cuadra exacto y el residuo es el margen (~1%).
#      Las facturas de BAT sin cigarrillos ya cuadraban en +0 y se excluian igual.
#
# Diferencias con v0.10:
#   1. VENTANA. Hasta v0.10 el PASO 0 filtraba por el MES EN CURSO
#      (DESDE = dia 1 del mes de hoy). Efecto medido 2026-08-09: de 160 draft
#      con DTE, 101 ($26.871.932, todas de julio) quedaron FUERA del universo
#      el 1 de agosto y ninguna corrida las volvia a mirar. La factura que no
#      se cerraba dentro de su propio mes calendario no se cerraba nunca:
#      v0.7 arreglo el ORDEN de la cola, no su ALCANCE.
#      Ahora DESDE = invoice_date de la draft con DTE mas ANTIGUA, con piso en
#      PISO_DESDE. HASTA no se toca (fin del mes en curso): recortarlo a "hoy"
#      dejaria afuera las facturas con fecha futura, que hoy SI entran (medido:
#      4 con invoice_date 2026-08-10).
#      La ventana ARRASTRA: cada corrida recalcula DESDE, asi que a medida que
#      se cierran las viejas el universo se encoge solo. MAX_MOVES=40 sigue
#      siendo el cap de costo: 160 facturas son ~4 corridas.
#      Nota contable: al 2026-08-09 la compania no tiene fiscalyear_lock_date ni
#      period_lock_date, asi que Odoo NO frena el posteo de julio en agosto. El
#      efecto sobre el F29 de julio ya declarado es una decision de negocio, no
#      un limite tecnico.
#
# Diferencias con v0.12:
#   1. FRACCION DE PACK en el fix de precio (PASO 1.5). Coca-Cola Embonor (y
#      cualquier emisor que facture por caja) manda QtyItem fraccionada
#      (0.166666 = 1/6). La UoM guarda 2 decimales (0.17) y qty*pu deja de dar
#      el MontoItem -> la factura descuadraba y caia a hold 'diferencia_impuesto'.
#      Hasta v0.12 price_fixes las EXCLUIA (para no desviar el pu correcto y
#      contaminar WAC). El fix estructural (subir decimal.precision de la UoM) se
#      descarto: re-renderiza registros historicos (posteados, stock moves, POS).
#      Ahora price_fixes las cuadra (pu = monto/qty_odoo) cuando qty ==
#      round(QtyItem, 2) (helper _es_fraccion_pack, redondeo HALF-UP como Odoo,
#      no el banker's de Python). El gate de unidades (unidad_ok) tambien las deja
#      pasar: es la MISMA cantidad redondeada, no un error de pack 12x. El error
#      real de cantidad sigue bloqueando. Todo-o-nada via el SAVEPOINT de siempre:
#      solo persiste si tras el fix la factura entera cuadra. El WAC se desvia
#      levemente pero estas compras son fraccionarias (peso bajo en el ponderado).
#      Universal, no por proveedor (motor generico). Medido 2026-08-09: 14 de 32
#      draft de Embonor con lineas fraccionadas, todas cuadran al neto del DTE.
#      helpers v0.10, test_helpers 100/100 (+9: redondeo half-up, fraccion de
#      pack cuadra, diferencia real excluida, gate de unidades la deja pasar).
#
# Diferencias con v0.11:
#   1. PASO 1.7: ajuste del IVA de margen de tabaco (cod 14) al DTE. Hasta v0.11
#      las facturas de BAT con cigarrillos cuadraban el neto pero quedaban ~1%
#      cortas en el impuesto/total (el margen presunto es un monto fijo por SKU
#      que el DTE trae SOLO en <ImptoReten>; Odoo lo calcula al 1,22% plano via
#      tax 44) -> `di`/`dt` fallaban y nunca posteaban. Ahora, si el neto ya
#      cuadra y no hay ILA-origen, se lleva la linea de margen (tax 44) a `otros`
#      (= suma de ImptoReten) escribiendo SOLO amount_currency; Odoo re-balancea
#      el termino de pago. Todo-o-nada via SAVEPOINT: solo persiste si tras el
#      ajuste la factura entera cuadra. Prereq (una vez): tax 44 en
#      supplier_taxes_id de los templates de cigarrillo (aplicado 2026-08-09).
#      Medido: de 82 draft de BAT, 77 exactas tras el ajuste, 0 descuadradas.
#
# Diferencias con v0.13:
#   1. PASO 1.8: auto-fix INEQUIVOCO de UoM de pack (todo-o-nada via savepoint).
#      El importador aplica UoM de pack (Pares x2 / x6) a lineas cuyo DTE factura
#      POR UNIDAD (no trae <UnmdItem>; UoM sale de un heuristico de nombre "Xnn"
#      o de uom_po_id mal seteado, medido 2026-08-10). Efecto: qty=N pero N*factor
#      al stock -> inventario inflado x2/x6. El gate de 3 montos es ciego (la plata
#      cuadra) y el gate de unidades solo BLOQUEABA. Ahora, cuando qty ya ==
#      QtyItem y el arbitro (retail) dice que el stock esta mal, uom_fixes migra la
#      linea a la unidad de referencia del producto (factor 1) re-asertando pu =
#      MontoItem/qty en el MISMO write (cambiar product_uom_id re-dispara el compute
#      que pisa el precio). La plata NO cambia; solo se corrige el stock. El caso
#      AMBIGUO (qty != QtyItem: error real de pack 12x) NO se toca y sigue en HOLD.
#      Medido 2026-08-10: 14 draft de Embonor en HOLD uom_no_cuadra, 14/14 con
#      qty == QtyItem (BENEDICTINO 6.5L Pares x11, Coca 250 x6, Pisco GR x6).
#   2. estado_texto: stamp legible al CHATTER de cada factura procesada (OK
#      validado / OK tras auto-fix / HOLD con la descripcion del motivo). Fecha
#      automatica; idempotente (no re-postea el mismo texto en el cron diario).
#      Solo al chatter (no escribe x_error_dte, que sigue como esta).
#      helpers v0.11, test_helpers +12 (uom_fixes 7, estado_texto 5).
#
# Diferencias con v0.14:
#   1. NOTAS DE CREDITO. El universo ahora incluye `in_refund` ademas de
#      `in_invoice` (PASO 0 y ventana). Antes el motor las ignoraba y las 96 NC
#      del periodo quedaban en draft (medido 2026-08-10: 27 ya cuadraban y 69
#      descuadraban por los MISMOS patrones que las facturas: fpos sin re-mapear,
#      precio pisado, fraccion de pack). Toda la logica aplica sin cambios porque
#      el gate usa amount_untaxed/tax/total (POSITIVOS en in_refund, verificado
#      N/C 4609248 y 000227) y price_unit (positivo); NO usa balance (que si es
#      negativo). El DTE de NC (TipoDTE 61) tiene la misma estructura Totales/
#      Detalle. Dos guardas: (a) el chequeo de duplicado usa m.move_type (no
#      hardcodea in_invoice), (b) APRENDER_MAPEOS solo corre en in_invoice — el
#      precio de supplierinfo debe salir de la compra, no de una devolucion.
#      Helpers SIN cambios (mismos amount_* positivos).
#
# Baseline medido 2026-07-27 (diag_cuadre.py, read-only): de 314 draft,
#   117 cuadran hoy | 156 con ILA origen | 26 falta SKU real | 4 precio/impuesto
# Helpers validados offline: test_helpers.py, 100/100.
#
# safe_eval: sin import (b64decode inyectado), sin re, sin frozenset,
# loops planos (sin genexp dentro de def), .write() no obj.attr=,
# x_name required en el create de x_error_dte, retorno en action.

DRY_RUN = True          # v0.8 primera corrida: lee el log y recien despues False
DO_POST = True
MAX_MOVES = 40         # facturas evaluadas por corrida (cap de costo)
PISO_DESDE = '2026-07-01'  # v0.11: piso duro de la ventana. DESDE se calcula de
                       # la draft mas antigua, y sin piso una sola factura vieja
                       # cargada por error (2023) abriria todo el historico y el
                       # motor postearia en un periodo ya declarado. Subirlo a
                       # medida que se cierran los meses; nunca dejarlo en None.
MAX_POST = 20          # tope de posteos por corrida
TOL = 2.0              # tolerancia $ en CADA uno de los 3 montos
TOL_IVA = 30.0         # v0.16: umbral del residuo de IVA que el PASO 1.9 corrige
                       # como redondeo (Odoo suma el 19% por linea; en facturas de
                       # muchas lineas el total difiere del <IVA> del DTE por unos
                       # pesos). Sobre TOL_IVA NO se toca: es error real, no redondeo.
PROV_TABACO = {'885029000'}   # BAT 88502900-0 (IVA de margen cod 14: no esta en el XML)
LOCK_KEY = 99123055
FP_DEFAULT = 12        # posicion fiscal "Facturas de Compra"
POST_RECARGO = False   # v0.8: las facturas cuadradas por la rama de recargo
                       # embebido quedan en DRAFT para revision manual. Pasar a
                       # True recien despues de mirar casos reales cuadrados.
APRENDER_MAPEOS = True   # v0.9: al postear una factura limpia, graba en
                         # product.supplierinfo el mapeo (proveedor, nombre del
                         # DTE) -> producto de las lineas que el DTE mando SIN
                         # codigo. Es lo que despues permite vincularlas solas.
VINCULAR_MAPEOS = True   # v0.9: usa los mapeos aprendidos para vincular las
                         # lineas cuyo DTE no trae CdgItem. Re-asierta precio y
                         # cantidad en el MISMO write: sin eso el onchange los pisa.
CUENTA_FLETE = '410237'   # Costo de Mercaderias Vendidas - Transporte
TAX_IVA_COMPRA = 2        # IVA 19% Compra (2024)
TAX_MARGEN = 44           # IVA Margen Comercializacion Tabaco (1,22% plano, sii 14,
                          # no recup 210230). El monto real es por SKU y solo viene
                          # en <ImptoReten> del DTE; el PASO 1.7 lo fija a `otros`.
NOMBRE_FLETE = 'RECARGO (flete)'   # marca del flete separado por el motor:
                                   # persiste en la factura y bloquea el posteo
                                   # mientras POST_RECARGO sea False
NOMBRE_ESPECIFICO = 'Ajuste Impuesto Especifico Diesel (no recuperable)'  # v0.17:
                                   # marca de la linea de ajuste del especifico
                                   # diesel (PASO 1.6). Idempotente: si ya existe
                                   # en la factura, no se re-agrega.
MARCA_HOLD = 'cuadre v0.7:'   # firma de los holds propios (ver PASO 0) — NO TOCAR: v0.8 sigue usando esta firma


# ============================================================================
# helpers puros — copiados de helpers.py (testeados, 53/53). No editar aqui:
# editar helpers.py, correr test_helpers.py y volver a pegar.
# ============================================================================

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
    # Nombre de item comparable: sin mayusculas ni ruido de espacios.
    # str.split() sin argumento parte por CUALQUIER whitespace, asi que colapsa
    # tambien los \xa0 (nbsp) que traen algunos DTE (verificado en los nombres de
    # Santa Ema de LA VINOTECA).
    # A proposito NO resuelve abreviaciones ('Hielo 2 k') ni typos ('recragas'):
    # esos se mapean a mano una vez y quedan aprendidos como registros aparte. Un
    # match difuso resolveria esos dos casos a cambio de poder vincular el producto
    # equivocado en silencio, y ese error contamina stock, WAC y margen a la vez.
    return ' '.join((s or '').split()).lower()


def dte_totales(xml):
    # {neto, exe, iva, otros, total}. `otros` suma TODOS los <ImptoReten>:
    # Odoo los acumula en amount_tax junto al IVA, el DTE los lleva aparte.
    # En una exenta (FNA) <MntNeto> viene vacio y el monto va en <MntExe>.
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


def tiene_especifico_diesel(xml):
    # True si alguna linea del DTE declara el Impuesto Especifico Diesel
    # (CodImpAdic 28, Ley 18.502). Es la senal del PASO 1.6: Copec/G&G netean el
    # especifico del total a pagar, el DTE trae neto+IVA > MntTotal y el
    # <ImptoReten> cod 28 viene buggeado en $1 (medido FAC 31908071 y 256280), asi
    # que el gap real (Odoo_total - MntTotal) es el especifico, no un error del XML.
    # Parseo por str.find (safe_eval: sin re). Gasolina lleva otro codigo, no 28.
    i = 0
    while True:
        a = xml.find('<CodImpAdic>', i)
        if a == -1:
            return False
        b = xml.find('</CodImpAdic>', a)
        if b == -1:
            return False
        if xml[a + len('<CodImpAdic>'):b].strip() == '28':
            return True
        i = b


def cuadra_3(untaxed, tax, total, tot, tol):
    # (ok, dn, di, dt): cada d* True = ESE componente no cuadra.
    dn = abs(untaxed - (tot['neto'] + tot['exe'])) > tol
    di = abs(tax - (tot['iva'] + tot['otros'])) > tol
    dt = abs(total - tot['total']) > tol
    return ((not dn) and (not di) and (not dt), dn, di, dt)


# 'envio' agregado 2026-07-27 (ENVIO CHILEXPRESS). OJO: 'recargo' NO matchea
# 'RECARGAS' (recargas telefonicas = mercaderia que se vende), y esta bien asi.
FLETE = ('flete', 'transport', 'despacho', 'reparto', 'acarreo', 'delivery',
         'recargo', 'cargo por', 'envio')
TIPO_MERCADERIA = 'Mercaderia'
SRC_OC = (26, 28, 31, 33, 34)


def _es_flete(n):
    nl = (n or '').lower()
    for t in FLETE:
        if t in nl:
            return True
    return False


def exige_sku(name, tipo_prov):
    # Decide SOLO por tipo de proveedor. NO se mira la cuenta: la cuenta de
    # inventario (210230) sale de la categoria DEL PRODUCTO, asi que una linea
    # sin producto nunca puede estar ahi — cae al gasto (CMV). Condicionarla a
    # la cuenta era circular. Lo destapo la corrida real 2026-07-27:
    # action_update_fpos_values recomputa impuestos Y CUENTAS, las lineas sin
    # producto migraron a CMV y la regla se apagaba justo cuando hace falta
    # (13 de 59 lineas de mercaderia sin vincular se escapaban del bloqueo).
    if _es_flete(name):
        return False
    return tipo_prov == TIPO_MERCADERIA


def lineas_sin_sku(lineas, tipo_prov):
    out = []
    for l in lineas:
        if l['has_product']:
            continue
        if exige_sku(l['name'], tipo_prov):
            out.append(l)
    return out


def tiene_ila_origen(tax_ids):
    for t in tax_ids:
        if t in SRC_OC:
            return True
    return False


def unidad_ok(qty, uom_f, it, retail, std):
    # True / False / None (None = no verificable, no bloquea).
    # Una linea puede cuadrar en PLATA y aun asi entregar al stock la cantidad
    # equivocada, porque la UoM es un pack (FAC 10142151: 144 botellas donde el
    # DTE dice 12, a 1/12 del costo). El gate de 3 montos es ciego a eso.
    # Pero QtyItem NO siempre viene en unidades de stock: medido sobre 2.212
    # lineas, 63% de los DTE factura POR CAJA (y ahi Odoo esta BIEN). Comparar
    # qty*factor == QtyItem a secas daba 63% de falsos positivos.
    # Arbitro = PRECIO DE VENTA, no el costo: standard_price se deriva de estas
    # mismas compras (contaminado si el historico entro mal). Base economica:
    # el costo por unidad no puede superar el retail por unidad.
    # PROXY: lo correcto seria costo < retail*(1-margen) por categoria.
    if uom_f == 1 or not it['qty']:
        return True
    # fraccion de pack capada por la UoM (qty == round(QtyItem, 2)): misma
    # cantidad redondeada, no error de pack 12x. Diferencia en stock sub-unitaria
    # (0.17*6 = 1.02 vs 1 botella). Simetrico con price_fixes: la cuadra en plata
    # y aca no la bloquea por unidades.
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
    # True si alguna linea aporta al stock una cantidad distinta a la del DTE.
    # `pares` = salida de alinear(). Lo no verificable NO bloquea.
    for (l, it) in pares:
        if unidad_ok(l['quantity'], l['uom_f'], it, l['retail'], l['std']) is False:
            return True
    return False


def motivo(falta_sku, ila_origen, unidades_mal, dn, di, dt):
    # '' si esta OK. Orden: el ILA-origen ANTES del gate de montos (price_include
    # mueve neto E impuesto y disfraza el diagnostico), y las UNIDADES antes de
    # devolver '' (una factura puede cuadrar en plata y tener el stock 12x mal).
    # Valores de la seleccion ya existente en x_error_dte.
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


# descripcion corta por codigo de motivo (para el stamp del chatter, v0.14)
MOTIVO_DESC = {
    'codigo_no_vinculado': 'codigo(s) sin vincular',
    'impuesto_mal_clasificado': 'impuesto (ILA) sin re-mapear',
    'uom_no_cuadra': 'UoM no calza (cantidad al stock erronea)',
    'linea_descuadrada': 'neto e impuesto descuadran vs XML',
    'precio': 'precio (neto) descuadra vs XML',
    'diferencia_impuesto': 'impuesto descuadra vs XML',
}


def estado_texto(motivo_code, n_uom_fix):
    # stamp legible para el chatter: OK sin fix / OK tras auto-fix UoM / HOLD con
    # la descripcion del motivo. La fecha la pone el chatter; la idempotencia la
    # maneja _post_estado (no re-postear el mismo texto en el cron diario).
    if motivo_code:
        desc = MOTIVO_DESC.get(motivo_code, motivo_code)
        return 'Cuadre DTE HOLD - ' + desc
    if n_uom_fix:
        return ('Cuadre DTE OK - validado vs XML + UoM auto-corregida '
                '(pack->unidad, %d linea/s)' % n_uom_fix)
    return 'Cuadre DTE OK - validado vs XML + UoM validado'


def _solo_digitos(s):
    r = ''
    for ch in (s or ''):
        if ch.isdigit():
            r += ch
    return r


def es_tabaco(vat, prov_set):
    return _solo_digitos(vat) in prov_set


def parse_items(xml):
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
    # Total del RecargoMonto cuando viene DENTRO del MontoItem (0 si no).
    # Algunos emisores (Comercial Peumo) suman el flete al MontoItem de cada
    # linea. Ese recargo es afecto a IVA pero NO integra la base del ILA, asi
    # que cobrarlo dentro del precio del producto infla el impuesto. Medido en
    # FAC 7471135: 515.736 de flete -> 105.726 de ILA de mas.
    # Otros (Embonor) lo mandan aparte y su MontoItem ya viene limpio. La
    # diferencia se decide por la identidad de la linea, NO por una lista de
    # proveedores:
    #     prc * qty - desc + rec == monto   -> el recargo esta DENTRO
    # Todo-o-nada: si alguna linea no trae recargo o no cierra la identidad,
    # devuelve 0 y la factura cae al hold de siempre. Falla cerrado.
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


def _factor(tax_ids, tax_by_id):
    f = 1.0
    for t in tax_ids:
        tt = tax_by_id.get(t)
        if tt and tt.get('price_include'):
            f += (tt.get('amount') or 0) / 100.0
    return f


def alinear(odoo_lines, items):
    # Empareja lineas de Odoo con items del <Detalle>. Las lineas de
    # flete/recargo NO tienen item: el DTE las lleva como <DscRcgGlobal>, no
    # como <Detalle>. Por eso se descuentan ANTES de comparar los largos.
    # Verificado en FAC 10142151: 13 lineas vs 12 <Detalle>, y el DscRcgGlobal
    # de 77.520 es la linea RECARGO (MntNeto 2.000.646 = 1.923.126 + 77.520).
    # Antes se comparaba len(odoo_lines) != len(items) y se abortaba: toda
    # factura con recargo global quedaba sin fix de precio aunque fuera
    # reparable.
    # Dos intentos, en orden — el flete NO siempre es recargo global:
    #   1. tal cual, si los largos calzan. En FAC 000891 la linea DESPACHO SI
    #      es un <Detalle> (qty 1, monto 145.908) y son 7 vs 7: sacarla a
    #      ciegas rompia una factura que alineaba perfecto.
    #   2. descontando flete/recargo, para el caso <DscRcgGlobal> (FAC 10142151).
    # Devuelve [] si ninguno calza (no se adivina).
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
    # [(line_id, product_id, nombre)] a grabar como mapeo proveedor->producto.
    # Solo de lineas que YA tienen producto (alguien las vinculo a mano) y cuyo item
    # del DTE vino SIN codigo. El filtro por codigo mantiene el alcance en el caso A
    # y evita llenar product.supplierinfo con miles de registros que no hacen falta.
    # El nombre NO sale de la linea de Odoo: al vincular, el onchange pisa el `name`
    # con el del producto (verificado en FAC 7471136). El nombre del proveedor solo
    # sobrevive en el <NmbItem> del XML, que `alinear()` empareja por posicion.
    # `conocidos` es un set de nombres YA normalizados. Se devuelve el nombre sin
    # normalizar para que quede legible en el catalogo de compras.
    # Se devuelve tambien `line_id`: sin el, el llamador tiene que adivinar de que
    # linea sacar el precio buscando por product_id, y eso rompe cuando el mismo
    # producto aparece dos veces en la misma factura.
    # Cuatro guardas antes de aprender un par, todas fallan cerrado:
    #  1. cantidad: fraccion de pack, igual que price_fixes.
    #  2. montos duplicados EN LA FACTURA: si el mismo MontoItem aparece en dos
    #     <Detalle>, un cruce posicional entre esas dos lineas pasaria la guarda
    #     de plata igual (los montos calzan de cualquiera de los dos lados).
    #  3. plata: price_subtotal == monto. La comparacion es directa porque el ILA
    #     viaja en el nodo <ImptoReten> del DTE y NO integra el MontoItem:
    #     verificado sobre 22 lineas con ILA de 4 facturas reales, ratio
    #     price_subtotal/monto = 1.0000 exacto.
    #  4. conflicto de NOMBRE en la misma factura: si el mismo nombre normalizado
    #     aparece dos veces apuntando a product_id DISTINTOS, no se aprende
    #     NINGUNO de los dos (mismo centinela que mapeo_por_nombre). Antes
    #     ganaba el primer escritor y quedaba un solo registro grabado, y la
    #     guarda de ambiguedad de mapeo_por_nombre (que exige DOS registros en
    #     conflicto) nunca se enteraba.
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
    # [(line_id, product_id)] de lineas SIN producto que matchean UN solo mapeo.
    # `mapeos`: [{'nombre', 'product_id'}] del proveedor de la factura.
    # Ante ambiguedad NO se vincula: dos mapeos con el mismo nombre normalizado
    # apuntando a productos distintos anulan esa entrada. Vincular el producto
    # equivocado imputa stock y costo a un SKU que no se compro, y eso contamina
    # inventario, WAC y margen a la vez.
    # Guarda de alineacion: igual que en mapeos_a_aprender, alinear() empareja
    # por POSICION. Aca no hay monto para corroborar (la linea no tiene producto
    # aun), pero el `name` de una linea huerfana TODAVIA es el NmbItem del DTE
    # (el onchange que lo pisa recien corre al asignar product_id). Por eso se
    # exige normalizar(l['name']) == normalizar(it['nombre']) antes de vincular:
    # si un emisor manda el <Detalle> en otro orden, el pareo cruzado no calza
    # en nombre y se descarta, en vez de imputar stock/costo al SKU equivocado.
    # Guarda de codigo: simetrica a la de mapeos_a_aprender. Si el DTE trae
    # CdgItem, esa es la llave FUERTE y resolverla es otro proyecto (caso B,
    # fuera de alcance): vincular por nombre cuando hay codigo disponible
    # imputaria el SKU equivocado si el proveedor reusa un nombre entre dos
    # codigos (dato real: HDOSO ya empezo a mandar codigo en algunas facturas).
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
            # Corrobora el pareo POSICIONAL de alinear(): en una linea huerfana el
            # name de Odoo sigue siendo el NmbItem del DTE (el onchange todavia no
            # lo piso), asi que si no coinciden, el <Detalle> vino en otro orden y
            # no se vincula. Sin esto, un orden distinto asignaria el producto de
            # OTRA linea y el gate de 3 montos no lo veria (precio y cantidad se
            # re-asiertan igual).
            if normalizar(l['name']) != k:
                continue
            out.append((l['id'], pid))
    return out


def _redondeo_2dec(x):
    # redondeo HALF-UP a 2 decimales, igual que la UoM de Odoo/Postgres. NO usar
    # round() de Python: es banker's (round(0.125,2)=0.12) y Odoo guarda 0.13
    # (medido FAC 104246127). x siempre positivo (una QtyItem).
    return int(x * 100 + 0.5) / 100.0


def _es_fraccion_pack(qty, qty_dte):
    # True si qty es el redondeo a 2 dec de QtyItem (fraccion de pack capada por
    # la UoM) y NO ya iguales (eso es 'pisado'). Distingue el redondeo benigno
    # (0.166666 -> 0.17) del error real de cantidad (pack 12x), que el gate de
    # unidades sigue bloqueando.
    if abs(qty - qty_dte) <= 0.001:
        return False
    return abs(qty - _redondeo_2dec(qty_dte)) < 0.005


def price_fixes(odoo_lines, items):
    # [(line_id, pu_target)] a cuadrar, pu = monto/qty. Dos casos:
    #  (a) precio PISADO: qty == QtyItem (el maestro piso el price_unit).
    #  (b) fraccion de PACK: qty == round(QtyItem, 2). La UoM capa QtyItem a 2
    #      dec (0.166666 -> 0.17) y qty*pu deja de dar MontoItem. Estructural
    #      (subir decimal.precision) rompe la historia, asi que se cuadra el
    #      precio; desvia levemente pu/WAC pero la qty es chica (peso bajo).
    #      Decision de negocio 2026-08-09 (v0.13; antes se excluia por trampa UoM).
    # Se RECHAZA el resto (diferencia real de cantidad: error de pack, etc.).
    # v0.8: si el DTE trae el flete DENTRO del MontoItem (ver recargo_embebido),
    # la base de la linea es monto - rec. Cobrar el flete dentro del precio del
    # producto lo mete en la base del ILA e infla el impuesto. El SA compensa
    # creando una linea de flete aparte por el total.
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


def uom_fixes(odoo_lines, items):
    # [(line_id, uom_ref_id, pu_target)] de lineas con UoM de pack a auto-corregir.
    # Auto-fix INEQUIVOCO (v0.14): solo cuando migrar de pack a unidad hace que el
    # stock sea EXACTAMENTE el QtyItem del DTE. Tres condiciones, fallan cerrado:
    #  1. unidad_ok(...) is False — el arbitro (retail) dice que el stock esta mal.
    #  2. abs(qty - QtyItem) <= 0.001 — el numero ya calza; solo sobra el pack. Si
    #     qty != QtyItem el error es real y AMBIGUO (pack 12x): queda en HOLD.
    #  3. uom_ref_factor == 1 — hay una unidad de referencia segura a la que migrar.
    # pu_target = MontoItem/qty * factor: la plata NO cambia (qty*pu == MontoItem);
    # el SA re-asienta price_unit en el mismo write que cambia product_uom_id
    # (cambiar la UoM re-dispara el compute que pisa el precio).
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


# --- helper NO puro (usa env / recordset): exclusivo del SA, no vive en
# helpers.py ni se testea offline.

def _tiene_flete_motor(move):
    # True si el motor ya le separo el flete a esta factura. Se mira la LINEA
    # (persiste entre corridas), no una variable de memoria: en la corrida
    # siguiente la factura ya cuadra, no entra al PASO 1.5 y sin esta marca
    # se postearia sin revision.
    for l in move.invoice_line_ids:
        if l.display_type not in ('product', False):
            continue
        if (l.name or '') == NOMBRE_FLETE:
            return True
    return False


def _post_estado(move, texto):
    # stamp de estado al chatter (nota interna, no notifica seguidores).
    # Idempotente: no re-postea si el ultimo mensaje 'Cuadre DTE' de la factura ya
    # dice lo mismo (el cron corre a diario y no debe spamear los HOLD).
    prev = env['mail.message'].search(
        [('model', '=', 'account.move'), ('res_id', '=', move.id),
         ('body', 'like', 'Cuadre DTE')], order='id desc', limit=1)
    if prev and texto in (prev.body or ''):
        return False
    move.message_post(body=texto, subtype_xmlid='mail.mt_note')
    return True


# ============================================================================
# motor
# ============================================================================

env.cr.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_KEY,))
if not env.cr.fetchone()[0]:
    log('cuadre-fiscal v0.17: lock ocupado, salgo')
    action = {'type': 'ir.actions.act_window_close'}
else:
    HOY = datetime.date.today()
    if HOY.month == 12:
        _fin = datetime.date(HOY.year + 1, 1, 1)
    else:
        _fin = datetime.date(HOY.year, HOY.month + 1, 1)
    HASTA = (_fin - datetime.timedelta(days=1)).isoformat()

    # v0.11: la ventana arranca en la draft con DTE mas ANTIGUA (con piso en
    # PISO_DESDE), no el dia 1 del mes en curso. Se recalcula en cada corrida:
    # al cerrarse las viejas, DESDE avanza solo. Si no queda ninguna draft, cae
    # al dia 1 del mes en curso y el universo queda vacio, que es lo correcto.
    DESDE = HOY.replace(day=1).isoformat()
    _vieja = env['account.move'].search(
        [('move_type', 'in', ['in_invoice', 'in_refund']), ('state', '=', 'draft'),
         ('l10n_cl_dte_file', '!=', False),
         ('invoice_date', '>=', PISO_DESDE),
         ('invoice_date', '<=', HASTA)],
        order='invoice_date asc', limit=1)
    if _vieja and _vieja.invoice_date:
        DESDE = _vieja.invoice_date.isoformat()

    # --- holds vigentes: la factura sale de la cola hasta que alguien la toque.
    # Solo bloquean los holds que dejo ESTE motor (marca MARCA_HOLD en la
    # sugerencia). Los del detector 1585 son informativos y NO deben bloquear:
    # 245 de ellos son 'impuesto_mal_clasificado', que es justo lo que este SA
    # resuelve al aplicar la fpos — respetarlos seria auto-bloquearse.
    # 'draft' tampoco bloquea (solo significa "pendiente de postear").
    holds = {}
    for h in env['x_error_dte'].search([('x_studio_estado', '=', 'pendiente'),
                                        ('x_studio_tipo_error', '!=', 'draft'),
                                        ('x_studio_sugerencia', 'like', MARCA_HOLD)]):
        if not h.x_studio_factura:
            continue
        mid = h.x_studio_factura.id
        f = h.x_studio_fecha_check
        if f and (mid not in holds or f > holds[mid]):
            holds[mid] = f

    # --- catalogo de impuestos de compra (factor price_include del fix de precio)
    tax_by_id = {}
    for t in env['account.tax'].search([('type_tax_use', '=', 'purchase')]):
        tax_by_id[t.id] = {'price_include': t.price_include, 'amount': t.amount}

    # --- tabaco: hasta v0.9 se excluia del UNIVERSO (y ademas se salteaba dentro
    # del lote). El motivo declarado era que el IVA de margen (cod 14) lo calcula
    # Odoo y el gate de 3 montos no podia validarlo.
    #
    # v0.10 lo reabre (EXCLUIR_TABACO=False). Medido 2026-07-29 sobre 10 draft:
    #   - las facturas SIN cigarrillos (papel OCB) cuadran en +0: se excluian por
    #     el proveedor, no por su contenido.
    #   - en las de cigarrillos el descuadre NO era el IVA de margen: las lineas
    #     cargaban TRES IVA del 19% a la vez (2 + 28-origen + 17), porque BAT nunca
    #     recibia la posicion fiscal. El maestro esta bien: supplier_taxes_id es
    #     solo [17 IVA No Recup.], y map_tax deja exactamente eso.
    #     FAC 17111246: hoy neto -62.891 / imp +108.999; con la fpos aplicada el
    #     neto cuadra EXACTO y queda -4.833, que si es el IVA de margen (1%).
    #   - el clog que motivo excluirlas ya no aplica: desde v0.7 la que no cuadra
    #     recibe hold y sale de la cola, no re-consume cupo en cada corrida.
    # Volver a True revierte el comportamiento sin tocar nada mas.
    EXCLUIR_TABACO = False

    tabaco_ids = []
    for p in env['res.partner'].search([('supplier_rank', '>', 0)]):
        if es_tabaco(p.vat, PROV_TABACO):
            tabaco_ids.append(p.id)

    dom_base = [('move_type', 'in', ['in_invoice', 'in_refund']), ('state', '=', 'draft'),
                ('invoice_date', '>=', DESDE), ('invoice_date', '<=', HASTA),
                ('l10n_cl_dte_file', '!=', False)]
    n_tabaco = env['account.move'].search_count(
        dom_base + [('partner_id', 'in', tabaco_ids)])

    # --- PASO 0: universo, mas RECIENTES primero
    dom_univ = dom_base
    if EXCLUIR_TABACO:
        dom_univ = dom_base + [('partner_id', 'not in', tabaco_ids)]
    universo = env['account.move'].search(dom_univ, order='id desc')

    lote = []
    en_hold = 0
    for m in universo:
        if len(lote) >= MAX_MOVES:
            break
        if not m.l10n_cl_dte_file.datas:
            continue
        # re-entrada: si el move o alguna linea cambio despues del hold, vuelve.
        fh = holds.get(m.id)
        if fh:
            ult = m.write_date
            for l in m.invoice_line_ids:
                if l.write_date and l.write_date > ult:
                    ult = l.write_date
            if ult <= fh:
                en_hold += 1
                continue
        lote.append(m)

    msgs = ['=== OH Cuadre Fiscal DTE v0.17 (dry=%s post=%s) ventana=%s..%s ==='
            % (DRY_RUN, DO_POST, DESDE, HASTA),
            'universo=%d  en_hold=%d  lote=%d  (de los cuales tabaco=%d)'
            % (len(universo), en_hold, len(lote), n_tabaco)]
    posteadas = 0
    por_motivo = {}

    for m in lote:
        tipo_prov = m.partner_id.x_studio_tipo_proveedor or ''
        xml = b64decode(m.l10n_cl_dte_file.datas).decode('latin-1', 'ignore')
        tot = dte_totales(xml)

        if EXCLUIR_TABACO and es_tabaco(m.partner_id.vat, PROV_TABACO):
            msgs.append('  %-16s SKIP tabaco' % m.name)
            por_motivo['tabaco'] = por_motivo.get('tabaco', 0) + 1
            continue

        # --- PASO 1: aplicar posicion fiscal SIEMPRE
        ms = 0.0
        if not DRY_RUN:
            t0 = datetime.datetime.now()
            m.action_update_fpos_values()
            ms = (datetime.datetime.now() - t0).total_seconds() * 1000

        prod_lines = m.invoice_line_ids.filtered(
            lambda x: x.display_type == 'product').sorted(lambda x: (x.sequence, x.id))
        lineas = []
        ila = False
        for l in prod_lines:
            # OJO: 'factor' es el del price_include (fix de precio) y 'uom_f' el
            # de la unidad de medida (gate de unidades). No confundirlos.
            lineas.append({'id': l.id, 'name': l.name or '',
                           'has_product': bool(l.product_id),
                           'product_id': l.product_id.id or 0,
                           'quantity': l.quantity,
                           'price_subtotal': l.price_subtotal,
                           'factor': _factor(l.tax_ids.ids, tax_by_id),
                           'uom_f': l.product_uom_id.factor_inv or 1.0,
                           'retail': l.product_id.list_price or 0.0,
                           'std': l.product_id.standard_price or 0.0,
                           # v0.14: unidad de referencia del producto (factor 1),
                           # destino del auto-fix de UoM. 0/1.0 si no hay producto.
                           'uom_ref_id': l.product_id.uom_id.id or 0,
                           'uom_ref_factor': l.product_id.uom_id.factor_inv or 1.0})
            if tiene_ila_origen(l.tax_ids.ids):
                ila = True

        items = parse_items(xml)

        # --- PASO 1.2: vincular por mapeo aprendido (todo-o-nada via savepoint)
        # NO puede reusar el savepoint del PASO 1.5: aquel vive dentro de
        # `if not ok and not ila:` y estas facturas suelen YA cuadrar (delta 0),
        # asi que nunca entrarian ahi.
        if VINCULAR_MAPEOS:
            faltan_prod = []
            for ln in lineas:
                if not ln['has_product']:
                    faltan_prod.append(ln)
            if faltan_prod:
                mapeos = []
                sis = env['product.supplierinfo'].search(
                    [('partner_id', '=', m.partner_id.id),
                     ('product_name', '!=', False)])
                for si in sis:
                    pid = si.product_id.id
                    if not pid and si.product_tmpl_id:
                        variantes = si.product_tmpl_id.product_variant_ids
                        # solo si la variante es UNICA: un template con varias es ambiguo
                        if len(variantes) == 1:
                            pid = variantes.id
                    if pid:
                        mapeos.append({'nombre': si.product_name, 'product_id': pid})
                vincs = mapeo_por_nombre(lineas, items, mapeos)
                if vincs:
                    by_id = {}
                    for l in prod_lines:
                        by_id[l.id] = l
                    try:
                        env.flush_all()
                        env.cr.execute("SAVEPOINT cuadre_vinc")
                        for par in vincs:
                            ln = by_id[par[0]]
                            # log ANTES del write: ln.name todavia es el nombre del
                            # proveedor, el onchange recien lo pisa con el del producto.
                            # Sin esto la primera corrida real no es auditable: el
                            # mensaje solo decia cuantas lineas se vincularon, no que->que.
                            msgs.append('  %-16s   vincula "%s" -> %s'
                                        % (m.name, (ln.name or '')[:30],
                                           env['product.product'].browse(par[1]).display_name[:34]))
                            # RE-ASERTAR precio y cantidad en el MISMO write: asignar
                            # product_id dispara el onchange que pisa price_unit con el
                            # del maestro (medido: HIELO 1 KG 462 -> 454,48). El valor
                            # explicito en la misma escritura gana.
                            ln.write({'product_id': par[1],
                                      'price_unit': ln.price_unit,
                                      'quantity': ln.quantity,
                                      'discount': 0.0})
                        env.flush_all()
                        okv, dnv, div, dtv = cuadra_3(m.amount_untaxed, m.amount_tax,
                                                      m.amount_total, tot, TOL)
                        if okv and not DRY_RUN:
                            env.cr.execute("RELEASE SAVEPOINT cuadre_vinc")
                            msgs.append('  %-16s VINCULA %d linea(s) por mapeo aprendido'
                                        % (m.name, len(vincs)))
                            # `lineas` quedo desactualizada: sin esto el PASO 2 sigue
                            # viendo has_product=False y bloquea la factura recien arreglada.
                            nuevas = []
                            for ln in lineas:
                                vinculada = False
                                for par in vincs:
                                    if par[0] == ln['id']:
                                        vinculada = True
                                if vinculada:
                                    rec = by_id[ln['id']]
                                    ln2 = dict(ln)
                                    # OJO: no alcanza con pisar has_product. uom_f/retail/std
                                    # se capturaron cuando la linea NO tenia producto (uom_f=1.0),
                                    # y unidad_ok() cortocircuita con `if uom_f == 1: return True`.
                                    # Sin refrescarlos, el gate de unidades queda apagado justo
                                    # en las lineas recien vinculadas.
                                    ln2['has_product'] = True
                                    ln2['product_id'] = rec.product_id.id or 0
                                    ln2['uom_f'] = rec.product_uom_id.factor_inv or 1.0
                                    ln2['retail'] = rec.product_id.list_price or 0.0
                                    ln2['std'] = rec.product_id.standard_price or 0.0
                                    ln2['factor'] = _factor(rec.tax_ids.ids, tax_by_id)
                                    ln2['price_subtotal'] = rec.price_subtotal
                                    # v0.14: la unidad de referencia recien queda
                                    # definida al asignar el producto (antes no habia).
                                    ln2['uom_ref_id'] = rec.product_id.uom_id.id or 0
                                    ln2['uom_ref_factor'] = rec.product_id.uom_id.factor_inv or 1.0
                                    # I2: la linea recien vinculada puede traer un impuesto
                                    # ILA-origen sin mapear (la fpos corrio antes de que
                                    # existiera el producto). Sin recomputar esto aca,
                                    # motivo() no ve el ILA origen y la factura se
                                    # postearia con la cuenta equivocada.
                                    if tiene_ila_origen(rec.tax_ids.ids):
                                        ila = True
                                    nuevas.append(ln2)
                                else:
                                    nuevas.append(ln)
                            lineas = nuevas
                        else:
                            env.cr.execute("ROLLBACK TO SAVEPOINT cuadre_vinc")
                            env.invalidate_all(flush=False)
                            msgs.append('  %-16s VINCULARIA %d linea(s) -> %s%s'
                                        % (m.name, len(vincs),
                                           'cuadra' if okv else 'NO cuadra (rollback)',
                                           ' [DRY]' if DRY_RUN else ''))
                    except Exception:
                        # Simetrico con el PASO 3: ln.write() dispara recomputes de
                        # impuestos/cuenta/UoM (mas propenso a fallar que el create()
                        # de supplierinfo). Si revienta sin este aislamiento, el SA
                        # aborta ANTES del pg_advisory_unlock; como el lock es de
                        # SESION el rollback no lo libera y las corridas siguientes
                        # salen calladas por "lock ocupado".
                        try:
                            env.cr.execute("ROLLBACK TO SAVEPOINT cuadre_vinc")
                        except Exception:
                            pass
                        env.invalidate_all(flush=False)
                        msgs.append('  %-16s vinculado FALLO, sigue sin vincular' % m.name)

        # --- PASO 1.5: fix de precio pisado (todo-o-nada via savepoint)
        ok, dn, di, dt = cuadra_3(m.amount_untaxed, m.amount_tax, m.amount_total, tot, TOL)
        if not ok and not ila:
            fixes = price_fixes(lineas, items)
            if fixes:
                by_id = {}
                for l in prod_lines:
                    by_id[l.id] = l
                env.flush_all()                          # persiste la fpos ANTES del savepoint
                env.cr.execute("SAVEPOINT cuadre_fix")   # el ROLLBACK revierte solo el precio
                for (lid, pu) in fixes:
                    by_id[lid].write({'price_unit': pu, 'discount': 0.0})
                rec_emb = recargo_embebido(items)
                if rec_emb:
                    tiene_flete = False
                    for l in m.invoice_line_ids:
                        if l.display_type not in ('product', False):
                            continue
                        if _es_flete(l.name or ''):
                            tiene_flete = True
                    cta = env['account.account'].search(
                        [('code', '=', CUENTA_FLETE)], limit=1)
                    if tiene_flete:
                        msgs.append('  %-16s recargo embebido %d pero YA hay linea de flete'
                                    % (m.name, rec_emb))
                    elif not cta:
                        msgs.append('  %-16s ABORTA: no existe la cuenta %s'
                                    % (m.name, CUENTA_FLETE))
                    else:
                        m.write({'invoice_line_ids': [(0, 0, {
                            'name': NOMBRE_FLETE,
                            'quantity': 1.0,
                            'price_unit': rec_emb,
                            # re-verificar esta cuenta tras la primera corrida real: con
                            # F2 ya se registra hold y no vuelve al PASO 1, pero
                            # action_update_fpos_values recomputa cuentas de lineas sin
                            # producto y podria migrarla en facturas que aun no tengan hold.
                            'account_id': cta.id,
                            'tax_ids': [(6, 0, [TAX_IVA_COMPRA])]})]})
                        # el camino feliz tiene que dejar rastro: es la escritura mas
                        # riesgosa del v0.8 y sin esta linea el log no dice cuanto flete
                        # se separo ni a que cuenta fue (habria que ir factura por factura).
                        msgs.append('  %-16s flete embebido %d -> linea propia, cuenta %s (solo IVA)'
                                    % (m.name, rec_emb, CUENTA_FLETE))
                env.flush_all()
                ok2, dn2, di2, dt2 = cuadra_3(m.amount_untaxed, m.amount_tax,
                                              m.amount_total, tot, TOL)
                if ok2 and not DRY_RUN:
                    env.cr.execute("RELEASE SAVEPOINT cuadre_fix")
                    # v0.6 dejaba la arreglada en draft para postearla en la
                    # corrida siguiente. Aca se postea en la MISMA pasada: el
                    # savepoint ya re-verifico los 3 montos antes de persistir,
                    # asi que diferirla solo agrega una vuelta.
                    ok, dn, di, dt = ok2, dn2, di2, dt2
                    msgs.append('  %-16s FIX precio %d linea(s) -> cuadra'
                                % (m.name, len(fixes)))
                    # `lineas` se construyo ANTES del fix, asi que sus price_subtotal
                    # son los PISADOS. El PASO 3 los usa para corroborar el pareo con
                    # el DTE antes de aprender un mapeo, y con los viejos la guarda
                    # rechaza todo. Medido en FAC 007378: se posteo cuadrada pero
                    # aprendio 0 mapeos.
                    # No hace falta refrescar 'factor': el fix solo escribe
                    # price_unit/discount, no tax_ids, asi que _factor() (que
                    # depende de price_include/amount del impuesto) no cambia.
                    fixed_ids = []
                    for (lid, pu) in fixes:
                        fixed_ids.append(lid)
                    nuevas = []
                    for ln in lineas:
                        if ln['id'] in fixed_ids:
                            rec = by_id[ln['id']]
                            ln2 = dict(ln)
                            ln2['price_subtotal'] = rec.price_subtotal
                            nuevas.append(ln2)
                        else:
                            nuevas.append(ln)
                    lineas = nuevas
                else:
                    env.cr.execute("ROLLBACK TO SAVEPOINT cuadre_fix")
                    # NO usar m.invalidate_recordset() ni env.invalidate_all() a secas: ambos tienen
                    # flush=True por defecto y re-persistirian la cola de escritura DESPUES del rollback,
                    # rompiendo el todo-o-nada. Y m.invalidate_recordset() ademas solo invalida los campos
                    # del move, no los de las account.move.line a las que se les escribio price_unit.
                    env.invalidate_all(flush=False)
                    msgs.append('  %-16s FIX %d linea(s) -> %s%s'
                                % (m.name, len(fixes),
                                   'cuadraria' if ok2 else 'NO cuadra',
                                   ' [DRY]' if DRY_RUN else ''))

        # --- PASO 1.6: especifico diesel NO recuperable (combustible)
        # Copec/G&G ('Petroleo') netean el Impuesto Especifico Diesel (CodImpAdic
        # 28, Ley 18.502) del total a pagar: el DTE trae neto+IVA > MntTotal y el
        # <ImptoReten> cod 28 viene buggeado en $1, asi que el gap real
        # (Odoo_total - MntTotal) ES el especifico (medido FAC 31908071: 2.468;
        # 256280: 10.287; 370012: 810). OH lo CONSUME para logistica (via publica)
        # y NO lo recupera -> el especifico es COSTO. En el MISMO savepoint (todo-o-
        # nada) se hace: (1) el fix de precio del PASO 1.5 -el diesel viene con
        # QtyItem de 3 decimales (14.663) que la UoM capa a 14.66 y deja el neto
        # corto por unos pesos; sin este fix el neto no calza y PASO 1.5 lo revierte
        # solo porque el total aun no cuadra por el especifico (deadlock); y (2) una
        # linea de ajuste -esp SIN impuesto a la cuenta de gasto del combustible,
        # dejando el IVA credito (19% del neto) intacto. El neto esperado baja en
        # esp (el especifico reduce el gasto): el gate cuadra neto-esp / IVA /
        # MntTotal. Idempotente por la marca NOMBRE_ESPECIFICO. Distinto del PASO
        # 1.7 (tabaco): alli el ImptoReten SUMA al total, aca RESTA (signo opuesto).
        if not ok and not di and dt and tiene_especifico_diesel(xml):
            ya = False
            for l in m.invoice_line_ids:
                if (l.name or '') == NOMBRE_ESPECIFICO:
                    ya = True
            cta_esp = 0
            mejor = -1.0
            for l in prod_lines:
                if abs(l.price_subtotal) > mejor:
                    mejor = abs(l.price_subtotal)
                    cta_esp = l.account_id.id
            if not ya and cta_esp:
                by_id = {}
                for l in prod_lines:
                    by_id[l.id] = l
                env.flush_all()
                env.cr.execute("SAVEPOINT cuadre_esp")
                # (1) cuadrar el neto: redondeo de qty capada por la UoM (mismo
                # price_fixes del PASO 1.5, que aca se auto-revirtio por el total).
                for (lid, pu) in price_fixes(lineas, items):
                    by_id[lid].write({'price_unit': pu, 'discount': 0.0})
                env.flush_all()
                # (2) el especifico = lo que resta para llegar al MntTotal del DTE.
                esp = round(m.amount_total - tot['total'], 2)
                oke = False
                if esp > TOL:
                    m.write({'invoice_line_ids': [(0, 0, {
                        'name': NOMBRE_ESPECIFICO,
                        'quantity': 1.0,
                        'price_unit': -esp,
                        'account_id': cta_esp,
                        'tax_ids': [(6, 0, [])]})]})
                    env.flush_all()
                    tot_e = dict(tot)
                    tot_e['neto'] = tot['neto'] - esp
                    oke, dne, die, dte2 = cuadra_3(m.amount_untaxed, m.amount_tax,
                                                   m.amount_total, tot_e, TOL)
                if oke and not DRY_RUN:
                    env.cr.execute("RELEASE SAVEPOINT cuadre_esp")
                    ok, dn, di, dt = oke, dne, die, dte2
                    msgs.append('  %-16s AJUSTE especifico diesel -%d (no recup) -> cuadra'
                                % (m.name, int(round(esp))))
                else:
                    env.cr.execute("ROLLBACK TO SAVEPOINT cuadre_esp")
                    # ver PASO 1.5: invalidate_all(flush=False) para NO re-persistir lo revertido.
                    env.invalidate_all(flush=False)
                    if esp <= TOL:
                        msgs.append('  %-16s especifico diesel: gap<=TOL tras cuadrar neto (no ajusta)'
                                    % m.name)
                    else:
                        msgs.append('  %-16s ajuste especifico -%d -> %s%s'
                                    % (m.name, int(round(esp)),
                                       'cuadraria' if oke else 'NO cuadra',
                                       ' [DRY]' if DRY_RUN else ''))
            elif not cta_esp:
                msgs.append('  %-16s especifico diesel: sin cuenta de gasto en la linea (no ajusta)'
                            % m.name)

        # --- PASO 1.7: ajuste del IVA de margen de tabaco (cod 14) al DTE.
        # BAT factura el IVA de margen presunto (ImptoReten cod 14) como un monto
        # fijo por SKU que el DTE trae SOLO en <ImptoReten>; Odoo lo calcula al
        # 1,22% plano (tax 44) y queda ~1% corto -> `di`/`dt` fallan y la factura
        # queda en hold. Aca se lleva la linea de margen a `otros` (= suma de
        # ImptoReten) para que impuesto y total cuadren exacto. Precondiciones:
        # neto ya cuadra (not dn) y no hay ILA-origen sin mapear (not ila) -> el
        # unico faltante es el margen; si el neto o el IVA estuvieran mal, el
        # re-check de cuadra_3 no pasa y el savepoint revierte (todo-o-nada).
        # Mecanismo (validado 2026-08-09): escribir SOLO amount_currency de la
        # linea de impuesto -> en CLP balance==amount_currency y balance es
        # computado con inverse, tocar ambos aplica el delta DOBLE. Odoo re-balancea
        # la linea de termino de pago sola; tocarla = descuadre por doble conteo.
        if not ok and not dn and not ila and tot['otros'] > TOL and (di or dt):
            l44 = m.line_ids.filtered(
                lambda l: l.tax_line_id and l.tax_line_id.id == TAX_MARGEN)
            if l44:
                l44 = l44[0]
                delta = round(tot['otros'] - l44.balance, 2)
                if abs(delta) > TOL:
                    env.flush_all()
                    env.cr.execute("SAVEPOINT cuadre_margen")
                    l44.write({'amount_currency': round(l44.amount_currency + delta, 2)})
                    env.flush_all()
                    # PASO 1.9: cuadre fino del IVA al DTE (dentro del MISMO savepoint).
                    # Odoo calcula el IVA 19% por linea y lo redondea; en facturas
                    # grandes (muchas lineas) la suma difiere del <IVA> del DTE por unos
                    # pocos pesos de redondeo. Ese residuo hacia que cuadra_3 fallara
                    # DESPUES de ajustar el margen (TOL=2 no lo absorbe) -> el savepoint
                    # revertia el ajuste de margen CORRECTO y la factura quedaba en hold
                    # eterno (medido FAC 17197644: +3 de IVA, total 13.961.426 vs DTE
                    # 13.961.423). El DTE es el documento fiscal autoritativo, asi que se
                    # lleva la linea de IVA a tot['iva'] escribiendo SOLO amount_currency
                    # (mismo mecanismo que el margen; Odoo re-balancea el termino de pago).
                    # Guarda: solo si el residuo del IVA es <= TOL_IVA (redondeo, no error
                    # real); un descuadre grande de IVA NO se toca y sigue en hold.
                    liva = m.line_ids.filtered(
                        lambda l: l.tax_line_id and l.tax_line_id.id != TAX_MARGEN
                        and l.balance)
                    if liva:
                        liva = liva.sorted(key=lambda l: abs(l.balance))[-1]
                        d_iva = round(tot['iva'] - liva.balance, 2)
                        if abs(d_iva) > TOL and abs(d_iva) <= TOL_IVA:
                            liva.write({'amount_currency':
                                        round(liva.amount_currency + d_iva, 2)})
                            env.flush_all()
                    ok3, dn3, di3, dt3 = cuadra_3(m.amount_untaxed, m.amount_tax,
                                                  m.amount_total, tot, TOL)
                    if ok3 and not DRY_RUN:
                        env.cr.execute("RELEASE SAVEPOINT cuadre_margen")
                        ok, dn, di, dt = ok3, dn3, di3, dt3
                        msgs.append('  %-16s AJUSTE margen cod14 -> %d (cuadra)'
                                    % (m.name, int(round(tot['otros']))))
                    else:
                        env.cr.execute("ROLLBACK TO SAVEPOINT cuadre_margen")
                        # ver PASO 1.5: invalidate_all(flush=False) para NO re-persistir
                        # la escritura revertida (invalidate_recordset trae flush=True).
                        env.invalidate_all(flush=False)
                        msgs.append('  %-16s ajuste margen -> %s%s'
                                    % (m.name, 'cuadraria' if ok3 else 'NO cuadra',
                                       ' [DRY]' if DRY_RUN else ''))

        # --- PASO 1.8: auto-fix de UoM de pack INEQUIVOCO (todo-o-nada, savepoint)
        # Lineas donde la UoM es un pack (Pares/x6) pero qty ya == QtyItem: el
        # arbitro (retail) dice que el stock esta mal (unidad_ok False). Migrar a la
        # unidad de referencia del producto (factor 1) hace el stock EXACTO al DTE,
        # sin tocar la plata (pu = MontoItem/qty, re-asertado en el MISMO write
        # porque cambiar product_uom_id re-dispara el compute que pisa el precio).
        # Independiente de `ok`: estas facturas suelen cuadrar en plata y fallar
        # SOLO en unidades. El caso AMBIGUO (qty != QtyItem) NO entra (uom_fixes lo
        # excluye) y sigue en HOLD. Persiste solo si tras el fix las unidades quedan
        # OK y la plata NO cambio (todo-o-nada; el ROLLBACK usa invalidate_all(
        # flush=False), igual que PASO 1.5, para no re-persistir lo revertido).
        n_uom_fix = 0
        ufixes = uom_fixes(lineas, items)
        if ufixes:
            by_id = {}
            for l in prod_lines:
                by_id[l.id] = l
            au0, at0, atot0 = m.amount_untaxed, m.amount_tax, m.amount_total
            env.flush_all()
            env.cr.execute("SAVEPOINT cuadre_uom")
            fixed_ids = []
            for (lid, uom_ref, pu) in ufixes:
                by_id[lid].write({'product_uom_id': uom_ref,
                                  'price_unit': pu, 'discount': 0.0})
                fixed_ids.append(lid)
            env.flush_all()
            nuevas = []
            for ln in lineas:
                if ln['id'] in fixed_ids:
                    rec = by_id[ln['id']]
                    ln2 = dict(ln)
                    ln2['uom_f'] = rec.product_uom_id.factor_inv or 1.0
                    ln2['price_subtotal'] = rec.price_subtotal
                    nuevas.append(ln2)
                else:
                    nuevas.append(ln)
            umal_post = uom_mal(alinear(nuevas, items))
            plata_ok = (abs(m.amount_untaxed - au0) <= 0.01 and
                        abs(m.amount_tax - at0) <= 0.01 and
                        abs(m.amount_total - atot0) <= 0.01)
            if (not umal_post) and plata_ok and not DRY_RUN:
                env.cr.execute("RELEASE SAVEPOINT cuadre_uom")
                lineas = nuevas
                n_uom_fix = len(ufixes)
                msgs.append('  %-16s FIX UoM %d linea(s) pack->unidad (plata intacta)'
                            % (m.name, n_uom_fix))
            else:
                env.cr.execute("ROLLBACK TO SAVEPOINT cuadre_uom")
                env.invalidate_all(flush=False)
                motivo_fix = 'unidades OK' if not umal_post else 'unidades NO resueltas'
                if not plata_ok:
                    motivo_fix = 'plata cambio (no deberia)'
                msgs.append('  %-16s FIX UoM %d linea(s) -> %s%s'
                            % (m.name, len(ufixes), motivo_fix,
                               ' [DRY]' if DRY_RUN else ''))

        # --- PASO 2: REVISAR (SKU / unidades / los 3 montos)
        faltan = lineas_sin_sku(lineas, tipo_prov)
        pares = alinear(lineas, items)
        umal = uom_mal(pares)
        if not pares:
            # sin alineacion el gate de unidades no puede opinar y NO bloquea.
            # Se deja visible: silenciarlo haria pasar por "verificado" algo que
            # no se verifico (medido: ~3% de las facturas).
            msgs.append('  %-16s (unidades no verificables: no alinea con el DTE)' % m.name)
        mt = motivo(len(faltan) > 0, ila, umal, dn, di, dt)

        # --- PASO 3: GUARDAR o apartar
        if not mt:
            dup = env['account.move'].search_count([
                ('move_type', '=', m.move_type), ('partner_id', '=', m.partner_id.id),
                ('name', '=', m.name), ('state', 'in', ['draft', 'posted']),
                ('id', '!=', m.id)])
            if dup:
                mt = 'duplicado'
            elif posteadas >= MAX_POST:
                msgs.append('  %-16s LISTA (tope %d)' % (m.name, MAX_POST))
                continue
            elif not POST_RECARGO and _tiene_flete_motor(m):
                # NO se hace `continue`: se cae al registro de hold de mas abajo.
                # Sin hold la factura queda draft Y cuadrada, o sea vuelve al universo
                # en cada corrida, consume cupo de MAX_MOVES y re-aplica la fpos a
                # diario (lo que ademas puede migrar la cuenta de la linea de flete).
                mt = 'flete_descuadrado'
            elif not DRY_RUN and DO_POST:
                # v0.15: NO se aprende el mapeo proveedor->producto desde una NOTA
                # DE CREDITO. El price de supplierinfo debe salir de la compra
                # (in_invoice), no de una devolucion; ademas el precio de una NC
                # puede venir de otra logica. Vincular (VINCULAR_MAPEOS) si aplica
                # a la NC; aprender no.
                if APRENDER_MAPEOS and m.move_type == 'in_invoice':
                    # Todo el aprendizaje va en savepoint propio: si el create()
                    # de supplierinfo revienta (constraint, record rule del
                    # usuario del cron), NO se puede perder la corrida entera.
                    # Sin este aislamiento una excepcion aca aborta el SA antes
                    # del pg_advisory_unlock: el lock es de SESION, el rollback
                    # no lo libera, y las corridas siguientes salen calladas
                    # por "lock ocupado".
                    env.flush_all()
                    env.cr.execute("SAVEPOINT cuadre_aprende")
                    try:
                        conocidos = {}
                        sis = env['product.supplierinfo'].search(
                            [('partner_id', '=', m.partner_id.id),
                             ('product_name', '!=', False)])
                        for si in sis:
                            conocidos[normalizar(si.product_name)] = True
                        nuevos = mapeos_a_aprender(lineas, items, conocidos)
                        by_id_ap = {}
                        for pl in prod_lines:
                            by_id_ap[pl.id] = pl
                        for par in nuevos:
                            prod = env['product.product'].browse(par[1])
                            if not prod.exists():
                                continue
                            ln = by_id_ap.get(par[0])
                            # El price de supplierinfo se interpreta en uom_po_id del
                            # producto. Si la linea viene en UoM de pack, price_unit es
                            # POR CAJA y la OC propondria 12x (la trampa UoM que el resto
                            # del motor evita). Y price_unit es ANTES del descuento.
                            # Ante cualquiera de las dos, se graba 0: el mapeo de nombre
                            # sirve igual y el precio queda como estaba.
                            pu = 0.0
                            if ln is not None:
                                if ln.product_uom_id.id == prod.uom_po_id.id and not ln.discount:
                                    pu = ln.price_unit
                            env['product.supplierinfo'].create({
                                'partner_id': m.partner_id.id,
                                'product_tmpl_id': prod.product_tmpl_id.id,
                                'product_id': prod.id,
                                'product_name': par[2],
                                'price': pu})
                            msgs.append('  %-16s aprende mapeo: "%s" -> %s (precio %s)'
                                        % (m.name, par[2][:28], prod.display_name[:34], pu))
                        env.flush_all()
                        env.cr.execute("RELEASE SAVEPOINT cuadre_aprende")
                    except Exception:
                        env.cr.execute("ROLLBACK TO SAVEPOINT cuadre_aprende")
                        # flush=False: el default es True y re-persistiria lo
                        # revertido despues del ROLLBACK (mismo gotcha del PASO 1.5).
                        env.invalidate_all(flush=False)
                        msgs.append('  %-16s aprendizaje FALLO, se postea igual' % m.name)
                m.action_post()
                posteadas += 1
                _post_estado(m, estado_texto('', n_uom_fix))
                msgs.append('  %-16s POSTEADA (fpos %.0f ms)' % (m.name, ms))
                continue
            else:
                posteadas += 1
                msgs.append('  %-16s postearia%s'
                            % (m.name, ' [DRY]' if DRY_RUN else ' [DO_POST=False]'))
                continue

        por_motivo[mt] = por_motivo.get(mt, 0) + 1
        det = '%s%s%s' % ('N' if dn else '.', 'I' if di else '.', 'T' if dt else '.')
        msgs.append('  %-16s %-26s %s  delta=%+d'
                    % (m.name, mt, det, round(m.amount_total - tot['total'])))
        # detalle accionable de las lineas sin vincular (codigo del DTE por posicion)
        for l in faltan:
            cod = ''
            for k, ln in enumerate(lineas):
                if ln['id'] == l['id'] and k < len(items):
                    cod = items[k]['codigo']
            # cod vacio = el DTE de ese proveedor no manda <CdgItem> (verificado
            # en FAC 003666 y FAC 000087: Detalle=5/1 con CdgItem=0)
            msgs.append('      - sin vincular: %-34s cod_DTE=%s'
                        % (l['name'][:34], cod or '(el DTE no trae codigo)'))

        # --- hold en x_error_dte (dedup por factura+tipo)
        if not DRY_RUN:
            # El sello va DESPUES de procesar esta factura, con flush previo.
            # Si se sella al inicio del loop, la escritura de la propia fpos
            # (PASO 1) deja write_date > fecha_check y la regla de re-entrada
            # lee eso como "alguien la toco": el motor invalida su propio hold
            # y la factura vuelve a la cola en cada corrida. Diagnosticado
            # 2026-07-27 (dos corridas reales seguidas con en_hold=0).
            env.flush_all()
            ahora = datetime.datetime.now()
            lid = faltan[0]['id'] if faltan else False
            key = '%s:%s:%s' % (m.name, mt, lid or '')
            prev = env['x_error_dte'].search([('x_studio_factura', '=', m.id),
                                              ('x_studio_tipo_error', '=', mt),
                                              ('x_studio_estado', '=', 'pendiente')], limit=1)
            vals = {'x_name': key,
                    'x_studio_factura': m.id,
                    'x_studio_proveedor': m.partner_id.id,
                    'x_studio_tipo_error': mt,
                    'x_studio_estado': 'pendiente',
                    'x_studio_fecha_check': ahora,
                    'x_studio_monto_riesgo': abs(m.amount_total - tot['total']),
                    'x_studio_sugerencia': '%s %s (%s)' % (MARCA_HOLD, mt, det)}
            if lid:
                vals['x_studio_line_id'] = lid
            if prev:
                prev.write(vals)
            else:
                env['x_error_dte'].create(vals)
            # v0.14: stamp legible del HOLD al chatter de la factura (idempotente).
            _post_estado(m, estado_texto(mt, n_uom_fix))

    resumen = []
    for k in sorted(por_motivo):
        resumen.append('%s=%d' % (k, por_motivo[k]))
    msgs.append('RESUMEN lote=%d posteadas=%d | %s'
                % (len(lote), posteadas, ' '.join(resumen) or 'sin apartadas'))
    texto = '\n'.join(msgs)
    log(texto)
    env.cr.execute("SELECT pg_advisory_unlock(%s)", (LOCK_KEY,))
    action = {
        'type': 'ir.actions.client', 'tag': 'display_notification',
        'params': {'title': 'Cuadre Fiscal DTE v0.17 (%s)' % ('DRY_RUN' if DRY_RUN else 'APLICADO'),
                   'message': texto, 'sticky': True},
    }
