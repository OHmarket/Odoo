# Hallazgos — Monitor de registro, junio 2026 (prototipo read-only)

Fecha: 2026-06-17. Fuente: 431 facturas de compra de junio, XML del DTE parseado.

## Resumen por color

| Color | Facturas | $ en riesgo |
|---|---|---|
| 🟢 verde (todo OK) | 26 | 0 |
| 🟡 amarillo | 366 | 136.977.099 |
| 🔴 rojo | 39 | 22.488.457 |

% touchless de junio (verdes / total) = **6%**. Es el punto de partida a subir.

## Errores por categoría

| Categoría | Facturas | Nota |
|---|---|---|
| sin_sku (línea sin código) | 384 (616 líneas) | **el dolor dominante** → limpieza de maestro |
| no_contabilizado (draft) | 77 | $32M sin postear (mes en curso) |
| descuadre_total | 37 | de los cuales **9 son BAT/tabaco** (caso especial conocido) |
| impuesto_mal (ILA mal clasificado) | 6 | total OK, split neto/impuesto difiere → fix en maestro (tax) |
| sin_xml | 2 | sin DTE adjunto, no auditables vs XML |

## Bugs corregidos en el camino (validación)

1. **Tag de impuesto adicional:** el SII pone ILA/retención en `<ImptoReten><MontoImp>`
   (y a veces `<OtrosImp><MntImp>`), no donde se asumió. Sin esto, 294 falsos
   descuadres. Corregido → cuadra al peso con Odoo (`amount_tax` = IVA + adicionales).
2. **Total vs split:** separar "el total no cuadra" (🔴, pagás distinto al DTE) de
   "total OK pero impuesto mal clasificado" (🟡, ILA/tabaco). Antes se mezclaban.

## Pendiente de revisar con Marco

- Los **28 descuadre_total no-BAT** (ej. CCU FAC 178575077: Odoo registró
  $4.478.997 vs DTE $5.470.334, −$991.337). ¿Odoo sub-registró el ILA? Confirmar
  si es error real o config de impuesto.
- **BAT/tabaco (9):** ¿se excluyen del monitor (política "tabaco fuera") o se
  reportan aparte?
- Materialidad del split (`SPLIT_PCT=0.5%`, `SPLIT_ABS=$100`): ¿ok o se ajusta?
