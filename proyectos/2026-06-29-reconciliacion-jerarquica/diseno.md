# Reconciliación jerárquica: ancla de cadena para compra y distribución

**Fecha:** 2026-06-29
**Estado:** Fase 0 (diseño). Sin código productivo.
**Origen:** diagnóstico de 9640 (COCTEL CAPEL ICE) durante el proyecto
`2026-06-28-envio-periodo-fair-share`.

---

## 1. Qué problema se quiere resolver

El forecast por sucursal (motor `OH Forecast Base`, SES por `series_type`) tiene
dos fallas medidas:

- **Bias sistemático ~−24%**: el motor sub-pronostica en TODA la cadena. WAPE por
  sucursal 50%, bias −24% **uniforme** (todas las salas −19% a −34%). El bias NO
  se cancela al agregar (es sistemático, no ruido). → el CD **subcompra ~24%**.
- **Colapso por sala**: SES no tiene tendencia ni estacionalidad. En series con
  semanas-cero colapsa. Caso 9640/Coñaripe: SES(α=0.7) sobre 3 ceros de invierno
  → μ=0,32 (reproducido al decimal). Dispara `retorno_a_cd` sobre una sala que sí
  vende ~9/sem. Caso 21882: forecast 0, vende 220/sem → compra 0.

**Hallazgo clave (9640):** a nivel **cadena** el SKU vende 250/sem **estable**
(no colapsa); el 0,32 es 100% artefacto de **distribución**. Y la suma de los
forecast por sala (242) ≈ venta real de cadena (265) → para la **compra** los
errores se cancelan; el problema vivo es el **reparto**.

## 2. Qué decisión se toma con el resultado

Cómo se calcula (a) **cuánto compra el CD** y (b) **cómo se reparte a las salas**,
usando una **mirada de cadena** robusta como ancla, sin reemplazar el motor.

## 3. Qué pasa si se equivoca

- Sobre-anclar a venta real en un estacional en bajada → sobre-compra / sobre-stock
  (capital parado; crítico dado el flujo de caja).
- Top-down puro en una sala con patrón idiosincrático → mal reparto a esa sala.
- Mitigación: ventana reciente (no anual), guarda de tendencia, blend bottom-up.

## 4. Cómo lo resuelve la teoría / ERPs

**Reconciliación jerárquica de forecasts** (Hyndman, Athanasopoulos —
*Forecasting: Principles and Practice*, cap. jerárquico):
- **Bottom-up**: suma de las hojas (lo de hoy). Hereda ruido y colapsos por sala.
- **Top-down**: pronosticar el agregado (estable) y repartir por **proporción**
  (share). Robusto al colapso por hoja.
- **MinT / óptima**: blend que minimiza varianza combinando ambos niveles.

En ERPs: **SAP IBP** y **Oracle Demand Mgmt** planifican el nivel agregado
(DC/cadena) y **desagregan** a tienda por participación; el aprovisionamiento del
nodo central usa demanda agregada (pooling). Es exactamente el patrón que hoy falta.

## 5. Enfoques posibles

| # | Enfoque | Qué arregla | Supuestos / límites |
|---|---|---|---|
| A | **Piso de compra del CD** = venta real de cadena (con guarda estacional) | el −24% en la **compra** | no toca distribución; floor, no reemplazo |
| B | **Top-down en distribución**: forecast_sala = ancla_cadena × share_reciente | el **colapso** por sala + el nivel | share debe ser reciente (seasonal); top-down puro |
| C | **Reconciliación blend (MinT-like)** bottom-up ↔ top-down | ambos, óptimo | más complejo; calibrar pesos |
| D | **Arreglar el motor** (Holt/estacional, α robusto, piso al SES) | la raíz del bias/colapso | afecta TODO; alto riesgo; ya se descartó Holt en REG-1 |

## 6. Enfoque elegido y qué NO se hace

**Elegido: A + B, en etapas, como capa de reconciliación SOBRE el motor (no lo
reemplaza).**

- **A (piso de compra)** primero: quirúrgico, bajo riesgo, en la fila CD del stock
  (`max(forecast, ancla_cadena)` con guarda de tendencia). Cierra el −24% de compra.
- **B (top-down share)** después: el forecast por sala se reconcilia contra el
  ancla de cadena × share reciente, para que ninguna sala colapse ni quede bajo su
  participación real. Validado en 9640: team16 0,32 → 9,6; suma 242 → 295 (ancla).

**NO se hace (por ahora):**
- NO reemplazar el motor SES (sigue dando forma/σ; el ancla solo corrige nivel y reparto).
- NO enfoque C (blend óptimo) hasta validar A+B simples.
- NO enfoque D (tocar el motor) — alto riesgo, afecta todo el pipeline.
- NO share anual (rompe estacionales); se usa share **reciente** (trailing ~8 sem).

## 7. Casos canónicos de validación

| Caso | Situación | Resultado esperado |
|---|---|---|
| **9640 / team16** | chain estable 250, sala colapsada (SES 0,32) | top-down → ~9,6 (= real); NO `retorno_a_cd` |
| **21882** | chain forecast 0, vende 220/sem | piso → compra ≈ 220, no 0 |
| **Estacional en bajada** (cóctel post-verano, cadena) | venta reciente > demanda futura | guarda: NO sobre-comprar; floor limitado |
| **Agregado cadena** | bias −24% | tras A+B: bias→~0, sin sobre-stock; WAPE igual o mejor |
| **Sala idiosincrática** | patrón propio ≠ cadena | blend (C) si top-down puro la lastima |

## 8. Datos y arquitectura

- **Fuente:** `x_pos_week_sku_sale` (venta real semanal por sala; ya cacheada).
  Ancla cadena = Σ salas trailing N sem. Share = real_sala / real_cadena.
- **Dónde corre:** un **detector** (cron, como el de precio/quiebre) que escribe
  por SKU: `ancla_cadena`, `share_sala`, `tendencia`. El stock lo lee en la compra
  (piso) y el forecast/stock lo usa en el reparto (top-down).
- **Ventana y umbrales:** trailing 4-8 sem (a calibrar); guarda de tendencia 2v2;
  volumen mínimo; manejo de salas nuevas / share sparse.

## 9. Evidencia (medida en este diagnóstico, read-only)

- forecast cadena = 76% de venta real (−24% subcompra); 295 SKUs subestiman >40%.
- WAPE sucursal 50% / cadena 45%; bias −24% en ambos (sistemático).
- SES(0.7) reproduce μ=0,32 de 9640/team16 sobre 3 ceros.
- 9640: cadena 250/sem estable; top-down team16 0,32→9,6; suma 242→295.
- Scripts/medidas: `proyectos/2026-06-28-envio-periodo-fair-share/` (mismo hilo).
