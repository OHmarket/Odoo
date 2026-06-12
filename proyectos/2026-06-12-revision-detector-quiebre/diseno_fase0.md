# Fase 0 — Diseño: detector de quiebres por evidencia (reemplaza STOCKOUT_v2_0)

Diagnóstico que motiva este rediseño: ver [diseno.md](diseno.md).
Resumen del problema: el método actual reconstruye un balance hacia atrás 400
días anclado en el quant de hoy; el drift hace que el 59,5% de los días marcados
"quiebre" tengan balance negativo (imposible) y el 44,6% hayan tenido venta ese
día (no puede ser quiebre total). Mayoría de la salida es basura.

---

## 1. Qué problema se quiere resolver

Identificar, por (sala, SKU, día), si hubo **falta de disponibilidad** que
censuró la demanda, distinguiendo:
- **quiebre total:** el SKU activo no tuvo stock en todo el día.
- **quiebre parcial intradía:** tenía stock, se vendió y quedó en cero parte del día.
- **no-quiebre:** disponible / o SKU deslistado (no aplica).

Sin depender de un balance reconstruido frágil.

## 2. Qué decisión se toma con el resultado

Censurar demanda en el backtest de forecast (separar "error de modelo" de "no
había stock"). Granularidad de decisión = **semana** (el forecast es semanal).
Secundario: ranking de quiebres por proveedor / ABCXYZ para reposición.

## 3. Qué pasa si el modelo se equivoca

- **Falso quiebre** (marca quiebre donde había stock) → censura demanda real →
  el backtest sub-cuenta venta → el motor sub-forecastea → faltante de stock.
  Es el error que comete HOY el método actual (44,6% falsos). Costo alto.
- **Falso no-quiebre** (no marca un quiebre real) → cuenta venta censurada como
  demanda → sobre-estima levemente. Costo menor (ya tenemos sesgo over como lever
  de caja, ver memoria). **Asimetría: preferimos errar a no-quiebre.**

## 4. Cómo lo resuelve la industria (canon)

- **Period-end inventory snapshot** (SAP, Oracle Retail): se guarda/usa el stock
  real de cierre como verdad de cada período, no se re-deriva un libro mayor
  largo. Reconstrucción de un solo día desde verdad = sin drift acumulado.
- **OOS / lost-sales detection** (Oracle Retail Demand Forecasting, Nielsen/IRI):
  día OOS = *surtido activo* (vendió en su cadencia reciente) **AND**
  disponibilidad cero. La **venta es prueba de disponibilidad** (no puedes vender
  lo que no tienes) → se usa como ground-truth, no el on-hand contable.
- **On-hand nunca < 0:** el negativo es error de dato; se pisa en 0.
- **Lost-sales sizing** (opcional, fase 2): pérdida = tasa de venta × fracción
  del día sin stock, usando timestamps de venta. PROXY estándar de la industria.

## 5. Enfoques evaluados

| # | Enfoque | Costo | Robustez | Veredicto |
|---|---|---|---|---|
| A | Parchar v2.0: piso 0 + gate sobre el balance reconstruido | bajo | baja (sigue anclado al balance drifteado) | descartado |
| B | Snapshot diario completo de todos los pares (period-end real) | **alto** (~4,4M filas/año) | alta | descartado por costo |
| C | **Reconstrucción de 1 día desde quant real + detección por evidencia** | bajo (= o < que hoy) | alta | **ELEGIDO** |
| D | Inferencia pura por gaps de venta (zero-inflation) sin stock | bajo | media (más falsos) | como respaldo, no base |

## 6. Enfoque elegido y qué NO se hace

**Elegido: C.** Detección por evidencia sobre reconstrucción de un solo día.

Lógica núcleo (por sala, SKU, día D). **El stock al correr va PRIMERO; el gate
de actividad solo arbitra los días en cero:**
```
end_D   = stock.quant real (cierre)               # verdad
start_D = end_D - in_D + out_D                    # 1 día atrás, sin drift
end_D   = max(0, end_D); start_D = max(0, start_D)  # piso fisico

disponible_D  = end_D > 0  OR  out_D > 0          # tiene stock O vendió = prueba de stock
activo        = vendio (out>0) en ventana movil de N=45 días   # surtido vivo

# si disponible_D -> NO quiebre (no importa actividad)
quiebre_total_D   = NOT disponible_D AND start_D <= 0 AND activo
quiebre_parcial_D = start_D > 0 AND end_D <= 0 AND out_D > 0    # vendió y quedó en 0
# inactivo AND sin stock -> NO marcar (ambiguo: deslistado o quiebre largo)
```

**Validación del orden (T1b / diag7):** de los 708 pares hoy en quiebre perpetuo
(≥30 días), **64,3% tienen stock real AHORA** → los rescata gratis el chequeo de
stock-al-correr (`end_D>0`), sin gate ni cálculo. El 35,7% restante (cero stock
hoy) lo arbitra el gate de actividad N=45. La idea de Marco: el quant del momento
de ejecución es verdad del día y resuelve la mayor parte de la perpetuación solo.

Censura semanal: una (sala, SKU, semana) se censura si tiene ≥1 día de quiebre
total; los parciales censuran parcialmente (se conserva la venta del día).

**Qué se decide NO hacer (en v1):**
- No almacenar snapshots diarios de todos los pares (enfoque B).
- No re-derivar balance largo hacia atrás como fuente de verdad. El backfill
  histórico usa la **misma detección por evidencia** (robusta al drift porque
  no confía en el signo del balance); los parciales en historia profunda quedan
  best-effort, los totales son confiables vía venta=0 + activo.
- No dimensionar venta perdida intradía (fase 2 opcional, timestamps POS).
- No tocar el modelo destino salvo agregar, si hace falta, un flag de confianza.

**Ventana de surtido activo N:** default **45 días** (PROXY). Se calibra en
implementación con la distribución de gaps entre ventas por SKU (diag dedicado)
antes de fijar. Documentar como PROXY en el header.

## 7. Casos canónicos de validación

| Caso | Hoy (v2.0) | Esperado (nuevo) |
|---|---|---|
| AUSTRAL CALAFATE MEHEX (quant real +17) | quiebre −6 perpetuo | NO quiebre |
| Día con venta>0 (44,6% de la tabla) | marcado quiebre | NO quiebre total (vendió) |
| Balance negativo (59,5%) | quiebre | pisado a 0, sin perpetuar |
| SKU sin venta 60+ días (deslistado) | quiebre perpetuo 400d | NO quiebre (no activo) |
| Vende 3, queda en 0 a media mañana | parcial (start drifteado) | quiebre **parcial** (start real) |
| SKU activo, 0 venta, 0 stock | quiebre | quiebre **total** (correcto) |

Métrica de aceptación: tras el rediseño, % de días-quiebre con venta ese día
debe caer de 44,6% a ~0; % con balance negativo a 0. Conteo total de
días-quiebre debe bajar fuerte (se va el tail perpetuo), conservando los
parciales reales (~41%).
