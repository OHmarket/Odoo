# Des-censura de demanda por quiebre en HM-SI — Diseño

**Fecha:** 2026-05-25
**Estado:** diseño aprobado · pendiente fase de diagnóstico
**Alcance:** UN cambio — corregir el sesgo a la baja del forecast causado por días en stockout.
**Fuera de alcance (otros tracks):** uplift de feriado (capa `x_promo_plan`), horizonte L+R / calendario
de entregas por local, inclusión de facturas en la serie de demanda. Ver sección "Fuera de alcance".

---

## 1. Problema y decisión comercial

**Decisión:** que el forecast de los SKU propensos a quiebre deje de sub-pronosticar, rompiendo el
ciclo **quiebre → venta baja → forecast bajo → pedido bajo → quiebre**.

**Causa raíz (verificada en código):** HM-SI se entrena con `pos_order_line` agregado a buckets
**semanales** (`date_trunc('week')`, `HM SI Forecast.py:1465-1540`). Toda la maquinaria (SMA, SI,
selección de modelo) opera sobre arrays semanales (`base_vals` / `raw_vals`). **HM-SI nunca mira el
día ni el balance de stock**, así que una semana en la que el SKU estuvo quebrado entra como
*demanda baja real*. Hoy **no existe ninguna corrección por quiebre** (confirmado con el dueño).

**Por qué es la brecha de mayor impacto:** es el único sesgo que ni la corrida diaria ni el ejecutivo
de compras pueden compensar — está enterrado y silencioso en `μ_week`. Además ataca el dolor
declarado (quiebre recurrente) en su raíz. Sub-forecast cuesta más que over-forecast (criterio del
negocio).

**Principio de diseño:** es el **mismo patrón** que `OH Presupuesto ventas.py` ya aplica para
feriados — excluir/estimar días contaminados del baseline (`_avg_lastN_same_weekday_ly` con
`hclass=='N'`). Aquí la contaminación es el **stockout** en vez del feriado. No es un patrón nuevo.

---

## 2. El puente diario → semanal

El quiebre se conoce en granularidad **diaria** (`x_stock_balance_daily`); la demanda vive en
granularidad **semanal**. El núcleo del diseño es corregir la cantidad semanal según qué fracción
de la demanda típica de la semana ocurría en los días que el SKU **sí** estuvo disponible.

El atajo "inflar por días" (`qty / (días_en_stock/7)`) **es incorrecto** porque asume demanda plana
en la semana. En un negocio con demanda muy variable por día, si el quiebre cae en el peak (fin de
semana / feriado), sub-corrige fuerte.

**Corrección correcta:** ponderar la disponibilidad por el **perfil de día de la semana**.

> Ejemplo (cerveza quincenal, en stock Lun–Jue ≈ 40% de la demanda semanal típica, quebró Vie–Dom):
> `qty_corr = 10 / 0.40 = 25` ✅   (vs. atajo plano `10/(4/7) = 17.5` ❌)

Al ponderar la disponibilidad por el perfil weekday, **"inflar" y "reconstruir día a día" son la
misma cuenta**. El perfil weekday es el ingrediente clave.

---

## 3. Componentes

### 3.1 Perfil weekday `weekday_share[nivel][día]`
- Definición: fracción de la demanda semanal típica que cae en cada día (Lun…Dom), normalizada a
  suma 1 por nivel.
- Fuente: **POS diario en días limpios** (días sin flag de stockout). Consistente con la serie que
  HM-SI ya usa (POS). Las facturas quedan fuera de este cambio.
- Día limpio = día sin fila de quiebre en `x_stock_balance_daily` para ese (sala, SKU, fecha) dentro
  del período cubierto.
- **Jerarquía: SALA base, refinar.** Se parte del perfil de la **sala** (estable, mucha data, el
  ritmo semanal es propiedad de la sala). Se refina a `(sala, categoría)` y luego `(sala, SKU)`
  **solo si** ese nivel tiene ≥ `MIN_CLEAN_DAYS` días limpios. Misma filosofía multinivel que el SI,
  pero arrancando ancho en vez de angosto.

### 3.2 Disponibilidad ponderada por semana
- Para cada (sala, SKU, semana histórica): `avail = Σ weekday_share[d]` sobre los días `d` que
  estuvieron **en stock** esa semana.
- Días en quiebre: leídos de `x_stock_balance_daily`. Como esa tabla **solo persiste días de
  quiebre**, la ausencia de fila = día en stock (dentro del período cubierto).
- **Quiebre parcial** (`stockout_partial`: empezó con stock, se agotó a mitad del día): para v1 se
  trata como día en quiebre (se excluye del perfil limpio y cuenta como no-disponible). Es
  conservador — ese día capturó algo de venta — pero alinea con la aversión al quiebre. Refinable
  después (ponderar la fracción del día disponible).

### 3.3 Corrección de la cantidad semanal CRUDA
Por cada (sala, SKU, semana):
- **Sin flag stockout esa semana** → no tocar. El cero/bajo es demanda real.
- **Con quiebre y `avail ≥ AVAIL_FLOOR`** → `qty_corr = qty_obs / avail`, topado a
  `qty_corr ≤ qty_obs × CAP`.
- **Con quiebre y `avail < AVAIL_FLOOR`** (semana casi entera quebrada) → **fallback a semanas
  limpias vecinas** del mismo SKU: promedio de las últimas `MIN_CLEAN_WEEKS` semanas limpias
  (estilo `_avg_lastN` del presupuesto). Evita multiplicadores absurdos sobre data delgada.
- Toda semana corregida se **marca como imputada** (para que el backtest la mida aparte).

### 3.4 Integración — modelo intermedio (decisión confirmada)
Mismo patrón que `OH Price Correccion.py` → `x_price_coreccion`: una etapa separada calcula y
**persiste** la corrección; HM-SI solo la **lee y aplica**.

- **Script nuevo:** `02_forecast/OH Descensura Demanda.py`, corre antes de HM-SI (después de ABCXYZ).
- **Modelo nuevo:** `x_demanda_descensura`, una fila por (sala, SKU, semana con quiebre):
  `factor_correccion` (≥1), `qty_obs`, `qty_corr`, `avail`, `nivel_perfil`, `imputada` (bool),
  `metodo` (inflate / fallback).
- **Hook en HM-SI:** tras armar los buckets semanales (~`HM SI Forecast.py:1465-1540`) y **antes** de
  SMA / deflación SI, multiplica `raw_vals[semana] × factor_correccion` para las celdas que matcheen
  (factor default = 1.0 → sin efecto). Read+multiply quirúrgico.

**Por qué intermedio y no inline:** auditable (se ve qué semana se corrigió y cuánto), reversible
(apagar el script → factor 1.0 → HM-SI vuelve solo), bajo riesgo (no toca SMA/SI/modelo/fair share),
y el backtest mide lo `imputada` aparte. Restricción dura: en `safe_eval` los Server Actions **no
pueden importar**, así que no existe el punto medio "función compartida" — la elección era binaria
(inline vs modelo) y se eligió modelo.

El diagnóstico (Fase 1) es el **antecesor read-only** de `OH Descensura Demanda.py`: misma matemática,
sin escribir. En Fase 2 se le agrega la escritura a `x_demanda_descensura`.

---

## 4. Flujo de datos

```
x_stock_balance_daily (días de quiebre por sala/SKU/fecha)
        │
        ├──> días limpios ──┐
POS diario (qty por sala/SKU/fecha) ──> perfil weekday[sala→categ→sku]
        │                   │
        └──> avail semanal ─┘
                  │
POS semanal (query actual HM-SI) ──> qty_obs por (sala,SKU,semana)
                  │
                  ▼
        qty_corr = corrección(qty_obs, avail, fallback vecinas)  [marca imputada]
                  │
                  ▼
        raw_vals corregido ──> SMA / deflación SI / modelo (HM-SI sin cambios)
```

---

## 5. Parámetros (defaults tentativos, a calibrar con el diagnóstico)

| Param | Default | Qué controla |
|-------|---------|--------------|
| `AVAIL_FLOOR` | 0.30 | bajo esta disponibilidad ponderada, no inflar → fallback |
| `CAP` | 2.5× | tope al multiplicador de corrección |
| `MIN_CLEAN_DAYS` | ~20 | días limpios para refinar el perfil weekday de sala → categoría/SKU |
| `MIN_CLEAN_WEEKS` | 4 | semanas limpias para el promedio del fallback vecino |

---

## 6. Limitación honesta (reportar incertidumbre)

- `x_stock_balance_daily` cubre desde **2025-01-01** (`BACKFILL_FLOOR_DEFAULT`). Las semanas
  anteriores **no se pueden corregir** (sin flag de quiebre) → se dejan como están.
- La ventana de demanda de HM-SI (~26 semanas) cae **dentro** de la cobertura. El SI de largo plazo
  (multi-año) solo se corrige parcialmente. Aceptable para v1; documentado.
- La señal de demanda es **POS** (no incluye el ~5% de facturas). Consistente con HM-SI actual.

---

## 7. Casos canónicos de validación

1. **Quincenal quebrado en el peak** → sube apropiado (ponderado), no plano.
2. **SKU que nunca quebró** → corrección = identidad (no cambia nada).
3. **Semana 0 sin quiebre** → intacta (demanda real baja).
4. **SKU crónicamente quebrado** → fallback a semanas limpias vecinas.
5. **Backtest antes/después** → el BIAS de los SKU propensos a quiebre debe subir (menos negativo)
   **sin** disparar over-forecast en los SKU limpios.

---

## 8. Fases (lento pero correcto)

1. **Diagnóstico read-only (primero, no toca nada):** cuántas celdas (sala, SKU, semana) tienen
   quiebre, distribución de `avail`, cuántos SKU son crónicamente quebrados, magnitud esperada de la
   corrección. Esto **dimensiona el impacto y calibra `AVAIL_FLOOR` / `CAP`** con datos reales.
2. **Implementar** la corrección como pre-proceso del input de HM-SI.
3. **Backtest comparativo** (caso #5) antes de promover a productivo.

---

## 9. Fuera de alcance (tracks separados, no mezclar)

- **Uplift de feriado:** sumar demanda de evento hacia adelante reusando `x_holiday_occurrence`
  (capa `x_promo_plan`). Va *encima* del baseline limpio que produce esta des-censura.
- **Horizonte L+R / calendario de entregas por local:** corregir `period_weeks` para que refleje la
  cadencia real por (sala, proveedor). Pendiente conocido del dueño.
- **Facturas en la serie de demanda:** HM-SI usa POS only; el presupuesto suma POS+facturas. Cerrar
  esa inconsistencia es un fix aparte.
