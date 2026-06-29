# Plan — reconciliación de fuentes

## Fase 1 — capa + chequeo (HECHO 2026-06-22)
- [x] `definiciones.py` — constantes canónicas (CD=26, Web=2, ventanas, exclusiones)
      + loaders (`stock_salas`, `stock_cd`, `venta_semanal` con fallback cache→vivo).
- [x] `reconciliacion.py` — 5 detectores + tie-out, PASS/WARN/FAIL re-ejecutable.
- [x] Validado: stock parado real en salas = $146.5M, tie-out desc $0.

## Estado de checks (baseline 2026-06-22)
- 4 PASS, 1 WARN (kit phantom $18.1M — bug productivo a corregir aparte).

## Fase 2 — migración de informes (pendiente)
- [ ] Migrar informes de stock/analítica a importar `definiciones.py` (uno a uno).
- [ ] Correr `reconciliacion.py` antes de cada generación; bloquear si hay FAIL.

## Fase 3 — corregir en la raíz (pendiente, proyecto aparte)
- [ ] Kit phantom: no sumar stock del kit cuando el componente ya lo cuenta
      (cambio al Script de Análisis de Stock).
- [ ] Reportar CD como echelon separado en el informe de stock (no como sala).

## Cómo correr
    PYTHONPATH=. python proyectos/2026-06-22-reconciliacion-fuentes/reconciliacion.py
