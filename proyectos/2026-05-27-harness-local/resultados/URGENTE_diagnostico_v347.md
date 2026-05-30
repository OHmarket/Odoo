# 🚨 Diagnóstico urgente v3.47 — encontré 2 problemas

**Fecha:** 2026-05-29
**Método:** XMLRPC read-only directo contra producción
**Status:** ⚠️ NO emergencia inmediata pero requiere decisión antes del próximo cron del motor

---

## Lo que encontré

### Hallazgo 1 — El motor v3.47 SÍ está instalado pero NO aplicó factor en este run

- `x_hm_si_forecast`: **20,426 forecasts** del último run (creado 2026-05-29 00:40)
- **0 forecasts (0.0%)** tienen `categ_calib_factor != 1.0`
- Campos `categ_calib_factor`, `categ_calib_meta`, `mu_week_pre_calib` están **poblados pero todos en valor default**

**Root cause:** El motor corrió con `date_to=2026-05-17` (cutoff histórico = backtest), entonces:
- `target_date` del motor = lunes 2026-05-18
- `target_week` de los factores = lunes 2026-05-25 (recién creados hoy)
- Loader busca `target_week <= target_date` → `2026-05-25 <= 2026-05-18` = **False**
- ctx vacío → factor=1.0 para todos

**Por eso el CSV del backtest 28-05 muestra los mismos números que v3.46 puro** — el calib literalmente no se aplicó.

### Hallazgo 2 — El SA Calib v2.0 (idea Marco) confunde ESTACIONALIDAD con shift estructural ⚠️

Los 71 factores activos calculados hoy tienen una distribución preocupante:

| Métrica | Valor |
|---|---:|
| Saturados en **0.80 (recorte −20%)** | **53 de 71 (74%)** |
| Saturados en 1.20 (amplificación +20%) | 2 (3%) |
| Intermedios | 16 (23%) |
| **Promedio factor aplicado** | **0.847** |
| **Promedio raw_factor** | **0.708** |

**Top 10 categorías con MÁXIMO recorte:**

| Categoría | abc | raw | bias% pre |
|---|---|---:|---:|
| Chocolates | b | 0.18 | **−81.8%** |
| Chicles y Mentitas | a | 0.37 | −63.3% |
| Chicles y Mentitas | b | 0.40 | −60.5% |
| Maní | a | 0.40 | −60.3% |
| Bombones | b | 0.40 | −60.1% |
| Galletas | a | 0.41 | −59.3% |
| Helados | b | 0.42 | −57.8% |
| Helados | a | 0.43 | −57.5% |
| Caramelos | b | 0.45 | −54.8% |
| Agua Mineral | a | 0.45 | −54.5% |
| **Cervezas Tradicionales** | a | 0.74 | −26.5% |
| **Cervezas Premium** | a | 0.74 | −26.4% |

**Análisis del problema** — el algoritmo M1b compara:
- WINDOW_RECENT = últimas **10 sem cerradas** (Mar-May 2026, post-verano)
- WINDOW_LONG = últimas **26 sem cerradas** (Nov 2025-May 2026, INCLUYE verano Dic-Feb)

**Verano en Chile = peak temporal** de cervezas, gaseosas, helados, snacks. Las 26 sem incluyen ese peak; las 10 sem reciente NO lo incluyen → recent < long → factor < 1.

**Helados con raw=0.42** = el cluster cayó 58% vs ventana larga. NO es declive estructural, es POST-VERANO.

Si el motor productivo aplicara estos factores normalmente, **recortaría el forecast 20% en cervezas, helados, gaseosas, snacks** justo cuando ya no es verano — empeorando el sub-forecast cuando vuelva la temporada.

---

## Por qué la simulación local NO detectó esto

En la simulación M1b del 28-05:
- Cutoff factor = 2026-03-09 (factor calculado sobre data PRE-target)
- Target window = 2026-03-16 → 2026-05-18 (las 10 sem que evaluamos)

**Las dos ventanas coincidían temporalmente** (post-verano), entonces el factor "recorte verano" se evaluaba sobre datos post-verano que SÍ tenían demanda baja → parecía funcionar bien.

En producción real:
- Cutoff = HOY (28-may)
- Target = próxima semana
- Si los factores son post-verano y se aplican a una semana que el motor YA estimó con su SI (que ya descuenta el verano), entonces over-correct.

**Es exactamente el mismo problema que el patrón circular pero por otra causa.**

---

## Las 3 opciones para Marco al volver

### Opción A — Rollback inmediato (SEGURO, recomendado)

Context override en el cron del motor productivo:
```python
{"apply_categ_calib": False}
```
→ Motor v3.47 ignora la capa categ_calib. Comportamiento idéntico a v3.46.

Tiempo: 1 minuto. Reversible al instante.

### Opción B — Desactivar los factores en Studio

```sql
UPDATE x_categ_calib_factor SET x_studio_active = false;
```
→ Loader del motor encuentra ctx vacío. Factor=1.0 para todos.

Tiempo: 30 segundos. Más quirúrgico.

### Opción C — Fix algorítmico del SA Calib (VALIDADO)

Corrí simulación con cutoff REAL 2026-05-25 sobre 3 alternativas. Resultados:

| Opción | n_act | sat_low (0.80) | sat_high (1.20) | inter | avg |
|---|---:|---:|---:|---:|---:|
| **v2.0 actual (10/26)** | 71 | **54 (76%)** ⚠️ | 2 | 15 | **0.84** ⚠️ |
| **v2.1 LY (10 vs LY-10)** ⭐ | 63 | **21 (33%)** ✅ | 20 | 22 | **1.01** ✅ |
| v2.2 SI-adj | 78 | 0 | 78 (100%) ❌ | 0 | 1.20 (over-amp) |
| v2.3 short (10/13) | 57 | 10 (17%) | 0 | 47 | 0.89 (sesgo bajo) |

**v2.1 LY (canon retail estándar) gana**:
- Distribución balanceada (21 recorte / 20 amplificación)
- Promedio centrado en 1.0
- Controla estacionalidad por construcción

**Cervezas con v2.1 LY**: mix esperado — Premium A=1.20 (amplifica recuperación), Tradicional A=0.80 (caída real), Importadas A=1.20 (amplifica). Mucho más razonable que v2.0 que recortaba todas.

**Helados con v2.1 LY**: 1.18-1.20 (amplifica porque el crecimiento YoY es real, no es solo "salir del verano"). v2.0 los recortaba 0.80 por confundir estacionalidad.

**Mi recomendación de orden**: A (inmediato) → desarrollar v2.1 LY del SA Calib cuando vuelvas.

---

## Lo que NO está roto

- ✅ Motor v3.47 código corre OK (sintáxis safe_eval validada, fix de hasattr/frozenset aplicados)
- ✅ Modelo Studio `x_categ_calib_factor` bien creado
- ✅ Campos auditoría en `x_hm_si_forecast` poblados
- ✅ Loader lee correctamente el modelo
- ✅ Gate régimen funciona (regimes parsed)

**El motor está bien**. Lo problemático es la **lógica del SA Calib v2.0 confunde estacionalidad con declive**.

---

## Hipótesis revisada del CSV backtest 28-05

El backtest mostró BIAS −17pp pero WAPE +13pp vs baseline local. Mi interpretación inicial fue "calib funcionando pero over-correge". Ahora sabemos:

- **El factor NO se aplicó** (0% cobertura en x_hm_si_forecast)
- El backtest historical NO refleja v3.47 con calib
- La discrepancia WAPE/BIAS vs local es **artefacto del universo distinto** (1,975 SKUs prod vs 1,625 local + filtros distintos), no del factor.

---

## Acción inmediata recomendada (sin esperar a Marco)

**NO actué automáticamente** porque cualquier write requiere autorización del usuario (CLAUDE.md). Las opciones A y B requieren tocar el cron o un UPDATE SQL — ambas son acciones que necesitan tu aprobación explícita.

**Si vuelves antes de que el cron diario del motor corra mañana**: aplicar Opción A o B.

**Si el cron corre antes de tu vuelta**: el motor seguirá aplicando factor=1.0 (mismo bug de timing impide aplicar), entonces sin daño. Pero en cuanto los factores tengan target_week <= target_date del motor (semana siguiente), entonces va a aplicar los factores 0.80 a categorías que NO están en caída → sub-forecast en cervezas/helados/gaseosas.

**Si NO actuamos hoy**: el cron diario probablemente corra `apply_categ_calib=True` con target_date=lunes 2026-06-01 que SÍ es ≥ 2026-05-25 → aplicará los factores recorte.

---

## Próximos pasos cuando vuelvas

1. Decidir A o B (rollback)
2. Diseñar fix C.2 o C.3 con cuidado
3. Re-simular en harness local CON cutoff actual (no cutoff retroactivo)
4. Re-promover SA Calib v2.1
