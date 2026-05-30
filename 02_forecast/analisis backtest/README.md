# Análisis Backtest — OH Market

**Ubicación:** Backtests estructurados del motor HM-SI Forecast

---

## Estructura Estándar

Cada carpeta de backtest tiene:

```
YYYY-MM-DD/
├─ diseno.md               ← Qué se probó, por qué, hipótesis
├─ CIERRE.md               ← Informe final (métricas, recomendación)
├─ motor_vX_Y.py          ← Script del motor productivo (si aplica)
└─ resultados/
   ├─ backtest_raw.csv    ← WAPE/BIAS por SKU × regimen (para importar a analytics)
   ├─ regimen_summary.txt ← Tabla de WAPE por regimen vs baseline
   ├─ outliers.csv        ← SKUs problemáticos (quiebre, low-data, descartados)
   └─ comparacion.txt     ← Delta vs baseline (fila por cada métrica)
```

---

## Formato de Archivos

### diseno.md
- **Objetivo:** Qué se probó
- **Hipótesis:** Cambios esperados
- **Período:** W17-W19 (siempre 3 semanas cerradas)
- **Baseline:** Versión anterior

### CIERRE.md (ESTÁNDAR)
**Tabla 1: Resumen Ejecutivo**
```
| Métrica | Baseline | Este Run | Delta | Status |
| WAPE Global | % | % | ±pp | ✅/⚠️ |
| BIAS | % | % | ±pp | ✅/⚠️ |
| REG-1 | % | % | ±pp | CONTROL |
| ... | ... | ... | ... | ... |
```

**Tabla 2: WAPE por Regimen**
```
| Regimen | Baseline | Este Run | Delta |
| REG-1 | % | % | ±pp |
| ... | ... | ... | ... |
```

**Sección: Cambios por Versión**
- v3.44: cambio descripción, impacto estimado, status
- v3.45: (idem)
- v3.46: (idem)

**Sección: Issues**
- SKU/Regimen: síntoma, causa, decisión

**Veredicto:**
- ✅ LISTO PARA PROMOCIÓN
- ⚠️ AJUSTAR Y RE-TESTEAR
- ❌ NO PROMOCIONAR

### backtest_raw.csv
Estructura (para importar a analytics):
```
sku_id,regimen,mu_week_baseline,mu_week_v346,sigma_week,venta_real_w17,venta_real_w18,venta_real_w19,forecast_error,wape_local,bias_local
9001,REG-1,4.2,4.1,1.3,3,5,4,1.2,0.15,-0.08
...
```

### regimen_summary.txt
```
Resumen por Régimen (W17-W19/2026)

REG-1 (Smooth):
  Baseline WAPE: 53.60%
  v3.46 WAPE:   53.50%
  Delta:        -0.10pp ✅
  Count:        245 SKUs
  Notes:        Control intacto

REG-2 (Smooth Variable):
  ...
```

### outliers.csv
```
sku_id,team,category,reason,baseline_wape,vx46_wape,decision,notes
9407,VALP,CIGARRILLOS,quiebre_w16_w17,95%,92%,exclude,quiebre no es error forecast
8001,SJ,BEBIDAS,low_data_12sem,88%,85%,exclude,datos insuficientes
...
```

---

## Convenciones

1. **Período siempre W17-W19** (última semana cerrada - 2)
2. **Baseline:** versión anterior productiva (ver CHANGELOG)
3. **Delta:** Este Run - Baseline (negativo = mejor)
4. **Status:**
   - ✅ OK (métrica es favorable o neutral)
   - ⚠️ CAUTION (métrica empeoró pero dentro de tolerancia)
   - ❌ FAIL (métrica rompió criterio crítico)
5. **Control:** REG-1 no puede empeorar >0.5pp

---

## Comparar Entre Backtests

1. Abrir CIERRE.md de cada backtest
2. Comparar tabla "Resumen Ejecutivo"
3. Leer sección "Cambios por Versión" para contexto
4. Para análisis profundo: `diff resultados/backtest_raw.csv`

---

## Histórico

- **2026-05-26:** v3.44 → v3.46 (lifecycle, mu threshold, rounding)
- **2026-05-25:** v3.42 → v3.43 (trend correction)
- **2026-05-23:** v3.40 → v3.42 (fair share, rounding fixes)
- ... (ver carpetas anteriores)

---

**Última actualización:** 2026-05-30  
**Propietario:** Marco Sanhueza
