# Task 1: Helper puro `_calc_cola_larga_lote` + test local — Report

## Edits realizados

### 1. Constantes de cola larga
**Archivo:** `03_stock/OH Analisis de Stock.py`  
**Ubicación:** Después de línea 190 (PRESENTATION_PACK = 6)

Añadidas 4 constantes DEFAULT:
- `COLA_UMBRAL_WEEK_DEFAULT = 3.0`
- `COLA_OBJETIVO_DIAS_DEFAULT = 30.0`
- `COLA_PLAZO_PAGO_DIAS_DEFAULT = 45.0`
- `COLA_PISO_UNIDADES_DEFAULT = 1.0`

### 2. Lecturas de contexto (CTX)
**Archivo:** `03_stock/OH Analisis de Stock.py`  
**Ubicación:** Después de línea 796 (TOP_CASH_SAFETY_FACTOR = ...)

Añadidas 4 lecturas de CTX:
- `COLA_UMBRAL_WEEK = _safe_float(CTX.get('cola_umbral_week', ...), ...)`
- `COLA_OBJETIVO_DIAS = _safe_float(CTX.get('cola_objetivo_dias', ...), ...)`
- `COLA_PLAZO_PAGO_DIAS = _safe_float(CTX.get('cola_plazo_pago_dias', ...), ...)`
- `COLA_PISO_UNIDADES = _safe_float(CTX.get('cola_piso_unidades', ...), ...)`

### 3. Función helper `_calc_cola_larga_lote`
**Archivo:** `03_stock/OH Analisis de Stock.py`  
**Ubicación:** Después de línea 370 (def _calc_target_units) y antes de _cover_label

Función pura que implementa la política (s, S) de lote mínimo:
- Calcula S (order-up-to): caja entera si rinde ≤ plazo_pago; si no, fracción ~30d
- Calcula ROP: mu*lead + presencia mínima
- Input: `mu_week, moq, lead_weeks, objetivo_dias, plazo_pago_dias, piso_units`
- Output: `(S_units: float, rop_units: float)`

### 4. Test standalone
**Archivo:** `proyectos/2026-06-30-cola-larga-lote-caja/test_cola_larga_lote.py`

Creado con 6 casos canónicos:
- Caso A: mu=1/sem → S=6 (caja entera, 42d ≤ 45)
- Caso B: mu=2/sem → S=6 (caja entera, 21d ≤ 45)
- Caso C: mu=0.5/sem → S=2 (fracción, 84d > 45)
- Caso D: mu=0.2/sem → S=1 (fracción con piso, 210d > 45)
- Caso E: mu=0 → S=0, ROP=0 (sin demanda)
- Caso F: mu=2, lead=1 → ROP=3 (demanda en lead + presencia)

## Ejecución del test

**Comando:** `python proyectos/2026-06-30-cola-larga-lote-caja/test_cola_larga_lote.py`

**Resultado:**
```
OK: 6 casos canonicos
```

Todos los 6 casos pasan la validación de aproximación (tol=1e-6).

## Estado

✓ Helper implementado  
✓ Constantes añadidas  
✓ Lecturas de CTX añadidas  
✓ Test creado  
✓ Test ejecutado exitosamente  

El código está listo para Task 2 (diagnóstico read-only) y Task 3 (integración en rama solo_bodega).
