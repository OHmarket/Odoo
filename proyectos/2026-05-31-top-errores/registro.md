# Top errores del forecast — diagnóstico y conclusión (2026-05-31)

**Objetivo:** los outliers que minan la credibilidad en operación. Backtest server W20-W22 (export 30-05). Datos del server (no cache, que estaba contaminado).

## 1. El patrón: canibalización por precio en cervezas (6/6)

Los 6 peores errores son cervezas con evento de precio. La demanda **migra entre marcas** según precio relativo:

| SKU | su precio | demanda real | detector aplicó | dirección error |
|---|---|---|---|---|
| Budweiser | +8% | −45% | 0.87 | SOBRE |
| Royal Guard | +30% | −92% (3500→190) | 0.844 | SOBRE |
| Quilmes | +10% | bajó | 0.857 | SOBRE |
| Cusqueña | +9% | −83% | 0.79 | SOBRE |
| Cristal | −17% | +1900% (40→800) | 1.421 | absorbió |
| Stella | promo permanente (lift~1) | +100% | — | SUB |

- **El detector capta la dirección pero subestima la magnitud 6–45×** (usa elasticidad propia, no canibalización).
- **Stella:** tiene promo loyalty *permanente* (57 sem, inocua). No es receptor puro — el cuadro es más sucio que "canibalización limpia".

## 2. Mirada global vs top (cervezas, server)

- Global: 208 SKU, WAPE 61.5%, BIAS −16.9% (el global **lava**: 67% del error es SOBRE, 33% SUB).
- Concentración: top 10 SKU = 47% del error; top 20 = 57%.
- **42% del error de cervezas está en SKU con evento de precio** (13/20 top). Atacable en teoría.

## 3. Cinco métodos probados — NINGUNO supera al motor

| Método | Resultado | Por qué |
|---|---|---|
| bias_outlier (v3.48) | descartado | factor global por SKU, solo amplifica, racha reciente; sobre-stock |
| damped trend | descartado | REG-1 es varianza, no tendencia; overfitting al holdout |
| categ_calib v2.0 | roto | confunde estacionalidad (verano) con declive |
| MCI / reparto por elasticidad | subestima | reparte demasiado ancho (105/169); elasticidad teórica corta |
| **share-reciente (media/mediana)** | **no supera al motor** | error share: motor 14.2 vs media 15.4 vs mediana 16.3 |

El share-reciente falló porque el **target estaba mal**: el motor ya predice bien el *share*; el error está en el **NIVEL (unidades)**. Eso llevó al hallazgo (sección 4).

## 4. El ancla — parecía validado en W20-22, pero NO generaliza (ver §6)

El error no era de distribución sino de **nivel**: el motor arrastra el pre-evento. La corrección que **sí gana**:

> Para SKU con evento de precio, **reemplazar** el forecast por la **mediana de las últimas 4 semanas de venta real**. No multiplicar — anclar el nivel.

Validado (backtest server W20-W22, datos verificados == server):

| | GLOBAL | cervezas |
|---|---|---|
| motor (prod, bias_outlier ON) | 44.8% | 32.8% |
| **+ ancla mediana-4** | **40.5%** (−4.3pp) | **26.5%** (−6.3pp) |

- **Mecanismo:** ancla (reemplazar nivel) gana; **factor multiplicativo PIERDE** (44.8%→peor: compone con el nivel arrastrado y explota, ej. Cristal→2760).
- **Calibración:** mediana ≫ media; ventana **N=4** sweet spot. La ventana de **6 que usa el motor hoy es peor que no hacer nada** (arrastra el pre-evento).
- **Genuino:** el ancla gana sobre el motor CON y SIN bias_outlier (no es deshacer bias_outlier).
- **Consistente:** gana las 3 semanas; más fuerte cuando el evento es fresco (W20 cerveza −11pp), menos cuando el motor ya alcanzó (W22 −0.3pp).
- **Causa raíz:** Royal Guard quedó clasificado **REG-1** (régimen regular) → el camino de colapso del motor nunca se dispara. El ancla se gatilla con la **señal externa de precio**, no con la auto-detección.

## 5. Por qué los 5 métodos anteriores fallaron y este no

Todos atacaban el target equivocado o con el mecanismo equivocado:
- factor/elasticidad (detector, MCI) → **mecanismo** multiplicativo, explota en movimientos grandes.
- share-reciente → **target** equivocado (el share ya está bien; el problema es el nivel).
- damped/bias_outlier → corrigen sobre el nivel arrastrado, no lo reemplazan.

El ancla **mide el nivel nuevo directo** (mediana de venta real reciente) y lo reemplaza. Medir > estimar.

## 6. El ancla LAG-ea — NO se porta (test 10 sem, decisivo)

El test de 10 semanas (gate por recencia, motor limpio del harness sin bias_outlier) **dio vuelta la conclusión**:

- Avg dWAPE: **global +0.71pp, cerveza +1.20pp (PEOR)**. Gana solo 3-4/10 semanas.
- Desastre en el **onset**: 2026-04-20 cerveza **+21pp PEOR**. Por qué: la mediana-4 en la semana del evento son semanas **pre-evento** (nivel viejo alto) → ancla alto justo cuando la demanda colapsa. **El ancla no anticipa, lag-ea.**
- Gana solo en el **tail** (05-04→05-18, cuando el colapso ya entró a la ventana) — que es exactamente lo que el server W20-22 midió. **El "−4.3pp" era el tail favorable, no el ciclo completo.**

**Conclusión:** el onset de evento es **intrínsecamente impredecible** (no hay dato post-evento aún). Ni factor, ni share, ni ancla lo resuelven — todos relocalizan el error al onset.

**Recomendación:** NO portar el ancla. Volver al **flag de baja-confianza en el onset** (no predecir lo impredecible), ahora con evidencia dura. Separado: revisar si `bias_outlier` ayuda o estorba (el harness sin él es mejor baseline en la mayoría de semanas).

**Meta-lección:** testear el **ciclo completo**, no la ventana favorable. Medí 3 semanas (el tail bueno) y casi shippeo un cambio net-negativo al script más crítico. Scripts: `valida_ancla.py`, `backtest_ancla_10sem.py`.

## Lección de método (todo el día)

Cada cálculo inline rápido tuvo bugs (WAPE mean vs ponderado; share por fila vs agregado). **Verificar la fórmula antes de concluir.** Y: el cache del harness (27-05) estaba contaminado — para análisis de causa, **datos del server vía API/export fresco**.
