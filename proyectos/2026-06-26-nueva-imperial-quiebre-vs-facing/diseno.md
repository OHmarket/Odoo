# Piso de exhibición (presentation stock) en el cálculo de stock

**Fecha:** 2026-06-26
**Estado:** Diseño cerrado, pendiente de implementación.
**Disparador:** Heladeras de Nueva Imperial con caras vacías. Diagnóstico
mostró que el motor dimensiona el target **al ras** de `demanda·H + safety`;
SKUs de baja rotación quedan en cero y la góndola se ve vacía aunque no haya
quiebre real de abastecimiento.

## 1. Problema y decisión

- **Problema:** el target operativo no reserva un piso de presentación. Un SKU
  con demanda casi nula obtiene target ~0 → cara vacía.
- **Decisión que se toma con el resultado:** cuánto stock mínimo enviar a cada
  sala para que la cara de góndola/heladera no quede en cero, sin inflar capital.
- **Si el modelo se equivoca:** sobreestima → stock muerto en salas chicas;
  subestima → cara vacía (estado actual). Se mitiga con corte AX + floor.

## 2. Cómo lo resuelven los ERP grandes (canon)

- **Oracle Retail (Shelf Replenishment):** *Presentation Stock = "the minimum
  amount of stock required to fill a facing in the store."* Es capacidad física
  de cara, no % de demanda. Modos: capacity-based (llenar la cara) y sales-based
  (cara intacta cada mañana, repone lo vendido).
  <https://docs.oracle.com/cd/E12454_01/sim/pdf/160/html/store_user_guide/shelf_replenishment.htm>
- **SAP S/4HANA Retail (Replenishment Planning):** target dinámico =
  `demanda_diaria · rango_cobertura`. **Minimum Target Stock** = límite inferior
  (un FLOOR) del target; `stock_mínimo = demanda_diaria · rango_mínimo_cobertura`.
  El mínimo es **piso, nunca sumando**.
  <https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/9905622a5c1f49ba84e9076fc83a9c2c/449fc7536e8e2a4be10000000a174cb4.html>

**Reglas canónicas adoptadas:**
1. El piso entra como **FLOOR (`max`), no aditivo**. SAP minimum target stock es
   límite inferior; en autoservicio no hay cara intocable que justifique sumar.
2. Piso ideal = capacidad de facing (planograma). **Proxy aceptado sin
   planograma = días de cobertura** (`demanda · N días`). Marcado PROXY.
3. El piso por días solo no cubre los lentos (piso → 0). Se combina con un
   **mínimo físico por formato** (1 pack).

## 3. Modelo elegido

```
target_final = max( demanda·H + safety ,            # lo operativo (motor actual)
                    stock_minimo )                   # piso de exhibición (FLOOR)

stock_minimo = max( DIAS/7 · demanda_semanal ,       # proxy días (SAP)
                    PISO_FORMATO[formato] )           # mínimo físico (Oracle "fill a facing")
```

**Parámetros (cerrados con evidencia):**
- `DIAS = 2`. Medido: con la demanda de OH (mediana 0,5 u/día por SKU×sala) los
  días casi no mueven la aguja — en 80-95% de los SKU manda el piso de formato.
  Los 2 días solo importan para los ~10-20% de alto volumen (Coca Cola, Quilmes).
- `PISO_FORMATO = {lata: 6, vidrio: 4, pet: 3, sin_formato: 3}`. Es el p25 del
  stock sostenido por las salas sanas ≈ 1 pack por formato. PROXY (no es
  capacidad real de góndola).
- **Gate: `abcxyz == 'AX'`** (por sala, de `x_analisis_de_stock`), **bebidas
  frías** (categ child_of [1621 cervezas, 1614 gaseosas]). Corte inicial.
- **Solo salas.** Excluye CD (team 26) y Web (team 2): no exhiben.
- **Packs (6X/12X): piso aparte** (1-2 packs), no el de unidad. Pendiente de
  cerrar valor.

**Decisiones explícitas de qué NO se hace:**
- No aditivo (medido: +$2,74M vs +$155K del floor, misma cara llena).
- No relevar planograma físico (proxy días + formato lo evita).
- No aplicar a tabaco/licores (no van en frío; eran 73% del costo falso).
- No tocar AY de alto volumen (Stella 660, RG lata, Budweiser): su demanda ya
  les da target alto, el floor no los muerde.

## 4. Persistencia

Campo nuevo en `x_analisis_de_stock`: **`x_studio_stock_minimo`** (Float).
- Lo escribe el script de stock por SKU×sala.
- Auditable y editable por Operaciones (override manual posible).
- El cálculo de envío lo lee y aplica el `max`.

## 5. Costo medido (corte AX bebidas, unidades sueltas)

| | Monto |
|---|---|
| Incremental real (lo que el floor agrega sobre el motor) | **+$154.530** total / +$11.964 NI |
| El floor muerde en | 137/730 = 19% de los AX bebidas |

PROXY: `target_op ≈ reorder_target_weeks · demanda` (sin MOQ ni redondeos);
costo = `standard_price`. El exacto sale corriendo el motor con el floor adentro.

## 6. Casos canónicos de validación

- **Lento vacío** (Cristal 0.0 Radler lata, NI: demanda 0, target 0): el floor
  debe levantarlo a 6. ✓ esperado.
- **Rotador sano** (Kunstmann Torobayo, NI: demanda 6, target 6): el floor NO
  debe agregar nada (+0). ✓ esperado.
- **Alto volumen** (Coca Cola 1.5L, demanda 5/día): días manda → piso ~10, pero
  target operativo ya es mayor → floor no muerde.
- **CD/Web:** stock_minimo = 0 (excluidos).
- **No-bebida AX** (cigarro/pisco): fuera del corte, stock_minimo = 0.
