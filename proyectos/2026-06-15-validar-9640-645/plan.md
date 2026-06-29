# Plan — sensibilidad cleanse_min_days (9640/645)

## Estado: Fase 1 parcial (read-only, NO promovido)

### GATE de replicación
- σ_sim min_days=1 = 25.0 vs motor 26.2 → **mecanismo de cleansing+DOW VALIDADO** (4.6%).
- μ_sim min_days=1 = 46.8 vs motor 56.4 → **−17%, NO pasa ±5%**.
  Causa: serie usa `create_date` (proxy de `date_order`) y calendario de quiebre
  desde `x_stock_balance_daily` (memoria: fuente poco confiable). Absolutos del sim
  aproximados; **deltas** fiables (la lógica está replicada, lo prueba el σ).

### Resultado (sweep, escalado al baseline real del motor 56.4/26.2)
| config | μ* | σ* | target* | transfer* |
|---|---|---|---|---|
| OFF (sin de-censura) | 39 | 14 | 67 | 54 |
| min_days=1 (ACTUAL) | 56 | 26 | 108 | **95** |
| min_days=2 | 48 | 30 | 106 | 93 |
| min_days=3 | 46 | 10 | 65 | **52** |
| min_days=4 | 46 | 10 | 65 | 52 |

### Hallazgos
1. **min_days=2 no sirve** (transfer 93 ≈ 95): los quiebres de 2 días siguen contando.
2. **min_days=3 es el quiebre**: transfer 95→52 (−45%). Al dejar de levantar las
   semanas de 2 días (sobre todo 05-18, quiebre de fin de semana 58→103) el σ
   colapsa 26→10 y se lleva casi todo el safety.
3. **min_days=3 ≈ OFF** (52 vs 54): a min_days=3 la de-censura queda prácticamente
   apagada para este SKU.
4. El safety está dominado por **UNA semana** (05-18, 2 días weekend, lift 58→103,
   +78%). Lift agresivo para 2 días.

### Fuente de quiebre: CONFIABLE (corrección 2026-06-15)
El caveat de "fuente rota" quedó obsoleto. `x_stock_balance_daily` corre desde
2026-06-12 el detector v3.2 por evidencia (commit 73a54e2), confirmado en prod hoy
(STOCKOUT_v3_2, incremental). Los días de quiebre que usa la de-censura son REALES.
⇒ El debate ya NO es la calidad del input, sino si la FÓRMULA de lift sobre-corrige:
05-18 (2 días de fin de semana, peso DOW 0.437) → 58 sube a 103 (+78%). Defendible
si el SKU sigue el perfil DOW global (coctel = venta weekend-pesada, plausible).
⇒ Con quiebres reales, la de-censura está haciendo su trabajo; el caso para SUBIR
min_days se DEBILITA. El 95u queda mejor soportado de lo que parecía.

### Próximo paso para cerrar absolutos (Marco-ejecutado en Odoo)
Correr el motor REAL con context `fwd_model='x_scratch_forecast'` + `cleanse_min_days`
∈ {1,3} sobre un cohorte, comparar μ/σ/target. NO medir por WAPE (doble conteo
de-censura). Sin tocar x_hm_si_forecast productivo.
