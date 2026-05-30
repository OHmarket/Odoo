# Diseño: Análisis de Quiebre en Categoría Cigarrillos

**Fecha:** 2026-05-30  
**Objetivo:** Diagnosticar y documentar patrones de quiebre (stock = 0, sin venta) en la categoría de cigarrillos

## Problema

Categoría de cigarrillos presenta quiebres recurrentes que afectan WAPE del backtest. Necesidad: entender **cuándo**, **dónde** y **por qué** ocurren.

**Síntoma observado:** WAPE local alto en ciertos SKUs de cigarrillos, correlacionado con períodos sin venta (quiebre de stock).

## Solución Propuesta

1. **Detectar quiebres:** períodos de `qty_vendida = 0` por >1 semana consecutiva
2. **Mapear:** por SKU, local, período
3. **Correlacionar:** con eventos conocidos (promo, supply chain, cambio de precio)
4. **Documentar:** patrones para filtrado futuro en validación de backtest

## Enfoque

- **diagnosticar_quiebre_cigarrillos.py** — diagnóstico inicial, histogramas de quiebre por local/SKU
- **debug_cigarro_quiebre.py** — drill-down en casos específicos, timeline de eventos
- **Output:** dataset de quiebres mapeados, candidatos para exclusión en backtest

---

**Siguiente:** ver plan.md para tareas.
