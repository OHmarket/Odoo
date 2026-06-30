# Task 2: Diagnóstico Read-Only de Impacto — Reporte

## API Correction

**Plan assumption:** Import `from shared.odoo_xmlrpc import get_client`.

**Actual API:** El módulo `shared/odoo_xmlrpc.py` **no expone una función `get_client()`**. 
Exporta únicamente la clase `OdooReader`.

**Lines from shared/odoo_xmlrpc.py confirming the actual export:**
- Line 63: `class OdooReader:` — única clase de cliente público
- Lines 97-115: método `search_read(self, model, domain, fields, limit, offset, order)` 

**Corrección aplicada:** Cambiar import a:
```python
from shared.odoo_xmlrpc import OdooReader
```

Y instanciar directamente:
```python
cli = OdooReader()
rows = cli.search_read('x_analisis_de_stock', domain=[...], fields=[...], limit=20000)
```

**Nota sobre firma `search_read`:** El método real acepta `domain` como parámetro posicional o keyword, 
`fields` como keyword. El plan usaba `domain=[...]` como posicional; se ajustó a `domain=[...], fields=[...]` 
(formato keyword explícito, que es lo que el método espera en las líneas 107-114).

## Script Location

**File created:** `proyectos/2026-06-30-cola-larga-lote-caja/diag_cola_larga_impacto.py`

- Import corregido ✓
- Función `_calc_cola_larga_lote` copiada byte-idénticamente del plan (Task 1) ✓
- Cliente instanciado como `OdooReader()` ✓
- Parámetros `search_read` alineados con firma real ✓

## Compilation Check

```
python -m py_compile proyectos/2026-06-30-cola-larga-lote-caja/diag_cola_larga_impacto.py
```

**Result:** ✓ **PASS** — Syntax OK. No output, exit code 0.

## Notes

- Script NOT executed (conectar a Odoo productivo está deferido).
- Solo `py_compile` realizado (validación sintáctica, no ejecución).
- Los nombres de campo `x_studio_*` se asumen correctos; si el script falla en runtime,
  inspeccionar `ir.model.fields` de `x_analisis_de_stock` según el comentario en el código.

