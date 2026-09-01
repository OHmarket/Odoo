# Plan — Crecimiento compras Embonor semana 18-sep-2026

## Estado

| Paso | Estado | Nota |
|------|--------|------|
| Fase 0 — diseno cerrado | HECHO | `diseno.md` |
| Math del indice + tests offline | HECHO | `test_uplift_math.py`, 30/30 OK |
| Plumbing del reporte (Odoo falso) | HECHO | `test_report_smoke.py`, 8/8 OK |
| Correr contra Odoo real | **PENDIENTE (lo corre el usuario)** | requiere `.env` |
| Validar casos canonicos 5-7 del diseno | PENDIENTE | depende del paso anterior |
| Decidir si se lleva a compra/caja | PENDIENTE | fuera de alcance de esta version |

El numero NO existe todavia: este entorno no tiene credenciales de Odoo.

## Como correrlo

```
cd <raiz del repo>          # donde vive .env con ODOO_URL/ODOO_DB/ODOO_USER/ODOO_API_KEY
python "proyectos/2026-09-01-crecimiento-compras-embonor/diag_embonor_uplift.py"
```

Read-only: usa `shared/odoo_xmlrpc.OdooReader`, que bloquea create/write/unlink
antes de tocar el servidor. Deja el reporte en `resultados/embonor_uplift_*.txt`.

Costo de queries (importa: Odoo es productivo, sin staging):
- `res.partner` / `product.template` / `product.supplierinfo`: cientos de filas.
- `account.move`: ~1-3k facturas de Embonor desde 2024. Hay guard: si pasa de
  20.000 filas aborta en vez de castigar la cache del POS.
- `x_pos_week_sku_sale`: **read_group**, no search_read. ~1k filas agrupadas en
  vez de ~100k. Se lee en chunks de 800 SKU.

Tests offline (no tocan Odoo, corren en cualquier parte):

```
python "proyectos/2026-09-01-crecimiento-compras-embonor/test_uplift_math.py"
python "proyectos/2026-09-01-crecimiento-compras-embonor/test_report_smoke.py"
```

## Que mirar en el output, en orden

1. **Partners que matchean "embonor"** — confirmar que son los correctos y que
   no se colo un homonimo. Si el proveedor real esta bajo otro nombre, ajustar
   `SUPPLIER_PATTERN`.
2. **SKU del proveedor** — cuantos salieron por `x_studio_proveedor_compra` vs
   por `supplierinfo`. Si el primero da ~0, el campo no esta poblado para
   Embonor y el sell-out no es confiable (se apoya solo en supplierinfo, que es
   la fuente que v9.18.0 degrado justamente por codigos duplicados).
3. **Cobertura de cada serie** — si el sell-in no llega a septiembre 2025, el
   indice de compras no es medible y queda solo el de venta.
4. **Caso canonico 5**: indice sell-out 2025 claramente > 1. Si da ~1.00, el
   filtro de productos esta mal, no es que el 18 no exista.
5. **Caso canonico 6**: alguna semana +1/+2 con indice < 1 (payback). Si no
   aparece, o hubo quiebre, o la compra se esta midiendo mal.
6. **Reparto pre/post** antes de mandar plata a la semana 38: si el indice de la
   semana -1 es alto, el peak de compra ya se adelanto y sumar ambos como
   incremento seria doble conteo.

## Que NO hace esta version

- No toca `OH Analisis de Stock.py` ni el plan de compra. Es medicion.
- No desglosa por SKU ni por sala (solo agregado proveedor).
- No corrige el motor de forecast, que no tiene factor de evento de calendario.

## Siguiente paso natural (si el numero resulta creible)

Meter el indice de evento como factor de calendario en el forecast semanal,
en vez de parchar la compra a mano una vez al ano. Eso es otro proyecto y otra
discusion de diseno: cambia el motor productivo.
