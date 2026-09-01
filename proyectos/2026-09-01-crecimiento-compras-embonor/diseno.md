# Crecimiento de compras a Coca-Cola Embonor — semana del 18 de septiembre 2026

Fecha: 2026-09-01
Estado: DISENO + DIAG (Fase 1, read-only). Sin numero medido todavia.

## 1. Que problema se quiere resolver

Estimar cuanto crecen las COMPRAS (sell-in) a Coca-Cola Embonor en la semana
que contiene el 18 de septiembre de 2026.

Semana OH (lunes-domingo, estandar del repo):
`2026-09-14 (lun) -> 2026-09-20 (dom)`, ISO week 38. El 18 cae VIERNES y el 19
(Glorias del Ejercito) SABADO, o sea el fin de semana largo queda completo
DENTRO de la semana 38. No se parte entre dos semanas OH.

Analogos historicos (misma regla lunes-domingo):

| Ano | 18-sep  | week_start | ISO |
|-----|---------|------------|-----|
| 2023| lunes   | 2023-09-18 | 38  |
| 2024| miercoles| 2024-09-16| 38  |
| 2025| jueves  | 2025-09-15 | 38  |
| 2026| viernes | 2026-09-14 | 38  |

Ojo con 2021-2022: el 18 cayo sabado/domingo y la semana del evento es la 37.
El script resuelve la semana por fecha, no por numero ISO fijo.

## 2. Que decision se toma con el resultado

Dos decisiones, distintas entre si:

1. **Caja**: cuanto plata reservar para pagar a Embonor (proveedor de mayor
   monto del portafolio; ~$57M/mes segun snapshot de mayo 2026, CHANGELOG
   v9.1.84). Termino de pago 45d, o sea la compra de septiembre se paga en
   noviembre: el peak afecta el flujo con desfase.
2. **Reabastecimiento**: si hay que ADELANTAR compra (semana 37) para no
   quebrar en la 38. `OH Analisis de Stock.py` calcula base-stock con demanda
   media reciente; sin un factor de evento, subestima la semana 38.

## 3. Que pasa si el modelo se equivoca

- **Sobre-estimar**: capital inmovilizado en bebidas. Riesgo bajo de merma
  (bebida gaseosa, vencimiento largo), riesgo real de caja: Embonor a 45d es
  el pago mas grande del mes.
- **Sub-estimar**: quiebre en la semana de mayor demanda del ano en bebidas.
  Costo = venta perdida + el quiebre contamina el forecast siguiente
  (censura de demanda; ver `OH Quiebre de Stock.py`).

Asimetria: sub-estimar cuesta mas que sobre-estimar en esta categoria.

## 4. Como lo resuelve la teoria / los ERP grandes

El problema es un **evento de calendario recurrente con fecha movil dentro de
la semana** (holiday / causal event uplift). Canon:

- **Ratio-to-moving-average (RMA)**, el estimador clasico de indice estacional
  de la descomposicion multiplicativa (Census I / X-11). Es exactamente lo que
  SAP APO/IBP llama *seasonal profile* y lo que en promociones se mide como
  *lift factor*: `indice = valor_del_evento / baseline_centrado`.
- **Oracle Demantra / SAP IBP "causal factors"**: el evento se modela como
  multiplicador sobre el nivel base deseasonalizado, no como un nivel absoluto.
  Asi el indice se puede aplicar a un nivel base que crecio (salas nuevas,
  inflacion).
- **Holt-Winters** seria el canon si tuvieramos >=3 anos limpios de historia
  semanal por proveedor. NO los tenemos (`x_pos_week_sku_sale` arranca
  2025-01-01), y con 1-2 ciclos HW no puede separar estacionalidad de nivel.
  Por eso se usa RMA sobre ventana simetrica, que es el caso degenerado
  correcto con pocos ciclos.

PROXY documentado: con n=1 o n=2 eventos observados, el indice NO tiene
intervalo de confianza estadistico real. Lo que reporta el script es
dispersion (MAD del baseline y spread entre fuentes), no una CI frecuentista.
Se reporta como ESTIMACION con rango, nunca como monto duro.

## 5. Enfoques posibles

**A. Sell-in directo (facturas de compra Embonor por semana).**
Mide lo que se pregunta, sin traduccion. Contra: la serie es grumosa (ciclo de
pedido, MOQ, camiones), y la compra del evento se ADELANTA — parte del peak
cae en la semana 37, no en la 38. Historia: la que haya en `account.move`.

**B. Sell-out (POS) -> sell-in.**
Usa `x_pos_week_sku_sale` (grano semana x sala x SKU, con combos prorrateados
y feriados marcados). Serie mucho mas estable y con control same-store. Contra:
la compra no es igual a la venta en la misma semana; hay llenado de pipeline
antes y devolucion (payback) despues.

**C. Blend (elegido).** Indice de evento medido en AMBAS series:
- sell-in da el timing real de la compra (semanas 37+38 juntas),
- sell-out da la magnitud limpia de la demanda,
y se reportan los dos con su rango. Si divergen mucho, el diagnostico es el
resultado (significa que el pedido se adelanto/atraso, no que el modelo falle).

**D. Descartado**: pedirle el numero al forecast productivo
(`OH Forecast Base.py`, SES/SMA6). Ese motor NO tiene factor de evento de
calendario: por construccion aplana el 18. Usarlo aca seria medir el sesgo del
motor, no la estacionalidad.

## 6. Enfoque elegido y que NO se hace

Elegido: **C**, con estas reglas:

- Semana OH lunes-domingo; semana de evento resuelta por la fecha del 18-sep
  de cada ano (no por ISO fijo).
- Baseline = **mediana** de las semanas `[evento-8, evento-3]` y
  `[evento+3, evento+8]` (ventana simetrica: la simetria cancela la tendencia
  de primer orden). Mediana y no media: robusta a una semana con camion doble.
- `indice_evento = valor(semana_evento) / baseline`.
  Se reportan tambien `indice(evento-1)` (pre-compra) e
  `indice(evento+1)`, `indice(evento+2)` (payback), porque en compras el peak
  se reparte y no hay que contarlo dos veces.
- Estimacion 2026 = `nivel_base_2026 * indice`, donde `nivel_base_2026` es la
  mediana de las 6 semanas limpias previas a la ventana del evento.
- Crecimiento reportado en DOS lecturas, que no son lo mismo:
  1. **uplift**: semana 38 vs semana normal de 2026 (lo que preguntan).
  2. **YoY**: semana 38-2026 vs semana 38-2025, same-store, para separar
     estacionalidad de crecimiento de la empresa.
- Same-store: en sell-out se restringe a los `team_id` presentes en ambos
  periodos. En sell-in (facturas) NO hay team; la contaminacion por apertura de
  salas queda marcada como advertencia en el output.

NO se hace (fuera de alcance de esta version):
- No se toca `OH Analisis de Stock.py` ni el plan de compra. Esto es medicion.
- No se estima por SKU ni por sala (solo agregado proveedor); el desglose es un
  paso posterior si el agregado resulta creible.
- No se modela precio/inflacion aparte: el sell-in va en CLP netos, o sea el
  indice mezcla volumen y precio. El sell-out se reporta en unidades Y en CLP
  para poder separarlos.

## 7. Casos canonicos de validacion

Math (en `test_uplift_math.py`, corre sin Odoo):
1. Serie plana con evento 1.5x -> indice = 1.50 exacto.
2. Serie con tendencia lineal + evento 1.5x -> la ventana simetrica devuelve
   ~1.50 (la tendencia se cancela); la ventana solo-pre da sesgo conocido.
3. Un outlier x10 en el baseline no mueve la mediana.
4. Calendario: `semana_evento(2026) == 2026-09-14`, `2023 == 2023-09-18`,
   `2021 == 2021-09-13` (ISO 37, caso borde).

Datos (requieren Odoo, el usuario los corre):
5. La semana 38-2025 de sell-out Embonor debe dar indice claramente > 1. Si da
   ~1.0, el filtro de productos del proveedor esta mal armado.
6. Debe existir payback: alguna de las semanas 39/40-2025 con indice < 1. Si no
   aparece, la compra no se esta midiendo bien (o hubo quiebre).
7. Cobertura: el script imprime primera y ultima semana con dato de cada
   fuente. Si sell-in no cubre septiembre 2025, el indice de compras no es
   medible y solo queda el de venta.

## Limite conocido de esta estimacion

Un solo evento observado con data POS confiable (2025). Con n=1 el indice es
una MEDICION de un ano, no una distribucion. Cualquier numero que salga de aca
se reporta como estimacion con rango y con la advertencia de n.
