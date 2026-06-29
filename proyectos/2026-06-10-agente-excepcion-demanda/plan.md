# Agente Analista de Excepción de Demanda — Plan de Implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Un agente Claude propose-only que trabaja la lista de excepción del forecast, junta evidencia, diagnostica la causa y propone overrides medidos (FVA-gated) a un modelo Odoo que el humano aprueba.

**Architecture:** Agente = loop de tool-use sobre la Anthropic Messages API (NO Agent SDK; es un agente de dominio con 4 tools custom). El LLM razona y orquesta; las 4 tools son Python determinista que reusa el monitor de impacto-$ y el demand sensing ya validados. El agente solo PROPONE a `x_forecast_override` (estado pendiente); el humano aprueba en Odoo; la capa `OH Demand Sensing` consume solo aprobados.

**Tech Stack:** Python, `anthropic` SDK (Messages API, modelo `claude-sonnet-4-6`), `shared/odoo_xmlrpc` (read), cliente XML-RPC mínimo de escritura para `x_forecast_override`, pandas. Odoo 17.

**Validación:** el repo no usa pytest; cada tool se valida con un probe que corre contra el Odoo LIVE (read-only) y verifica forma/valores en SKU conocidos. La promoción a producción (campos Studio, Server Action, git) la ejecuta Marco tras confirmar — ver `PROMOCION.md`.

**Reusa:** `proyectos/2026-06-09-monitor-error-impacto/monitor_error.py` (impacto-$ + causa), `proyectos/2026-06-01-demand-sensing/validar_layer_pcorr.py` (regla sensing + gate FVA), patch Stock ya en repo.

---

## File Structure

Todo en `proyectos/2026-06-10-agente-excepcion-demanda/`:
- `agent_tools.py` — las 4 tools deterministas (funciones puras): `list_exceptions`, `get_evidence`, `run_sensing_gate`, `propose_override`. Una responsabilidad: lógica de negocio que el agente invoca.
- `odoo_writer.py` — cliente XML-RPC mínimo de ESCRITURA acotado a `x_forecast_override` (create). Separado de `OdooReader` (read-only) a propósito.
- `agent.py` — runner del agente: schema de tools, system prompt (rol analista + proceso canónico + regla propose-only), loop de tool-use, brief final.
- `probes/` — scripts de validación read-only por tool.
- `resultados/` — briefs y logs de corridas.
- Promoción (Marco): modelo Studio `x_forecast_override`; cambio en `02_forecast/OH Demand Sensing.py` (consumo de aprobados).

**Decisión de escritura (abierta en diseño):** opción (a) — cliente de escritura mínimo en `odoo_writer.py`, acotado a `x_forecast_override`, bajo volumen. Se descarta la opción (b) JSON+Server Action por más infra para igual resultado.

---

## Task 1: Tool `list_exceptions` — lista de excepción por impacto-$

**Files:**
- Create: `proyectos/2026-06-10-agente-excepcion-demanda/agent_tools.py`
- Create: `proyectos/2026-06-10-agente-excepcion-demanda/probes/probe_list_exceptions.py`

- [ ] **Step 1: Escribir `list_exceptions` en agent_tools.py**

Mismo cálculo que el monitor (pinball K_UNDER=2 × list_price, causa por orden quiebre→evento→cola→fantasma→smooth_real). Reimplementado self-contained (misma fórmula que `monitor_error.py`; fuente única = `2026-06-09/diseno.md`).

```python
# agent_tools.py
from __future__ import annotations
import sys
from pathlib import Path
from datetime import datetime, timedelta

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from shared.odoo_xmlrpc import OdooReader  # noqa: E402

K_UNDER, K_OVER = 2.0, 1.0
EXCLUDE_TEAM_IDS = {11}            # San Jose (forecast_noise_feedback)
TAIL_TYPES = {'lumpy', 'intermittent', 'no_signal'}
TEAM_NAMES = {5: 'Panguipulli 790', 6: 'Los Lagos', 7: 'Futrono', 8: 'Panguipulli 645',
              9: 'Panguipulli 763', 10: 'Lautaro', 11: 'San Jose', 12: 'Paillaco',
              13: 'Mehuin Express', 16: 'Conaripe', 17: 'Nueva Imperial', 18: 'Malalhue'}


def _m2o(v):
    return v[0] if isinstance(v, (list, tuple)) else v


def _iso_yw(d):
    if isinstance(d, str):
        d = datetime.strptime(d[:10], '%Y-%m-%d').date()
    c = d.isocalendar()
    return (c[0], c[1])


def _recent_weeks(o: OdooReader, n: int):
    g = o.execute('x_forecast_backtest', 'read_group', [],
                  ['x_studio_target_week_start'], ['x_studio_target_week_start:week'], lazy=False)
    weeks = sorted({r['__range']['x_studio_target_week_start:week']['from']
                    for r in g if r.get('__range')})
    return weeks[-n:]


def list_exceptions(weeks: int = 4, top_n: int = 20) -> list:
    """Top excepciones por impacto-$ con causa clasificada. READ-ONLY."""
    o = OdooReader()
    wk = _recent_weeks(o, weeks)
    fields = ['x_studio_product_id', 'x_studio_team_id', 'x_studio_target_week_start',
              'x_studio_real_qty', 'x_studio_forecast_qty', 'x_studio_series_type',
              'x_studio_regimen', 'x_studio_abcxyz', 'x_studio_categ_id']
    rows = []
    for w in wk:
        rows += o.search_read('x_forecast_backtest',
                              [('x_studio_target_week_start', '=', w)], fields=fields)
    # list_price por producto
    pids = sorted({_m2o(r['x_studio_product_id']) for r in rows if r.get('x_studio_product_id')})
    lp = {}
    for i in range(0, len(pids), 300):
        for r in o.search_read('product.product', [('id', 'in', pids[i:i+300])],
                               fields=['id', 'list_price']):
            lp[r['id']] = float(r.get('list_price') or 0.0)
    # cruces de causa
    wdates = [datetime.strptime(w, '%Y-%m-%d').date() for w in wk]
    d0, d1 = min(wdates) - timedelta(days=8), max(wdates) + timedelta(days=8)
    ev = set()
    for r in o.search_read('x_price_coreccion',
                           [('x_studio_target_week_start', '>=', d0.isoformat()),
                            ('x_studio_target_week_start', '<=', d1.isoformat())],
                           fields=['x_studio_product_id', 'x_studio_target_week_start', 'x_studio_var_pct']):
        if abs(float(r.get('x_studio_var_pct') or 0.0)) > 0.001 and r.get('x_studio_product_id'):
            ps = datetime.strptime(r['x_studio_target_week_start'][:10], '%Y-%m-%d').date()
            for off in (-7, 0, 7):
                ev.add((_m2o(r['x_studio_product_id']), _iso_yw(ps + timedelta(days=off))))
    so = set()
    for r in o.search_read('x_stock_balance_daily',
                           ['&', ('x_studio_date', '>=', d0.isoformat()),
                            ('x_studio_date', '<=', d1.isoformat()),
                            '|', ('x_studio_stockout', '=', True),
                            ('x_studio_stockout_partial', '=', True)],
                           fields=['x_studio_product_id', 'x_studio_team_id', 'x_studio_date']):
        if r.get('x_studio_product_id') and r.get('x_studio_team_id'):
            so.add((_m2o(r['x_studio_product_id']), _m2o(r['x_studio_team_id']), _iso_yw(r['x_studio_date'])))

    out = []
    for r in rows:
        tid = _m2o(r.get('x_studio_team_id'))
        if tid in EXCLUDE_TEAM_IDS:
            continue
        pid = _m2o(r.get('x_studio_product_id'))
        real = float(r.get('x_studio_real_qty') or 0.0)
        fcst = float(r.get('x_studio_forecast_qty') or 0.0)
        stype = str(r.get('x_studio_series_type') or '')
        yw = _iso_yw(r['x_studio_target_week_start'])
        pinball = K_UNDER * max(real - fcst, 0.0) + K_OVER * max(fcst - real, 0.0)
        impacto = pinball * lp.get(pid, 0.0)
        if (pid, tid, yw) in so:
            causa = 'quiebre'
        elif (pid, yw) in ev:
            causa = 'evento'
        elif stype in TAIL_TYPES:
            causa = 'cola_intermitente'
        elif real <= 0 and fcst > 0:
            causa = 'fantasma'
        else:
            causa = 'smooth_real'
        out.append({'product_id': pid, 'product_name': r['x_studio_product_id'][1],
                    'team': TEAM_NAMES.get(tid, str(tid)), 'team_id': tid,
                    'week': r['x_studio_target_week_start'], 'causa': causa,
                    'real': round(real, 1), 'fcst': round(fcst, 1),
                    'list_price': lp.get(pid, 0.0), 'series_type': stype,
                    'abcxyz': str(r.get('x_studio_abcxyz') or ''),
                    'categ': (r.get('x_studio_categ_id') or [0, ''])[1],
                    'impacto': round(impacto, 0)}}
    out.sort(key=lambda x: x['impacto'], reverse=True)
    return out[:top_n]
```

- [ ] **Step 2: Escribir el probe**

```python
# probes/probe_list_exceptions.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent_tools import list_exceptions

ex = list_exceptions(weeks=4, top_n=15)
assert isinstance(ex, list) and len(ex) > 0, 'sin excepciones'
assert {'product_id', 'causa', 'impacto'} <= set(ex[0]), 'faltan campos'
assert ex[0]['impacto'] >= ex[-1]['impacto'], 'no esta ordenado por impacto'
print('OK', len(ex), 'excepciones. Top 5:')
for e in ex[:5]:
    print(f"  {e['impacto']:>10.0f}  {e['causa']:<18} {e['product_name'][:40]}")
```

- [ ] **Step 3: Correr el probe y verificar**

Run: `python probes/probe_list_exceptions.py`
Esperado: imprime ≥1 excepción, ordenadas por impacto desc, con causa. Las top deben incluir cervezas/destilados de alto valor (Cristal, JW Red, Stella).

- [ ] **Step 4: Commit**

```bash
git add "proyectos/2026-06-10-agente-excepcion-demanda/agent_tools.py" "proyectos/2026-06-10-agente-excepcion-demanda/probes/probe_list_exceptions.py"
git commit -m "agente excepcion: tool list_exceptions (impacto-\$ + causa)"
```

---

## Task 2: Tool `get_evidence` — el "mira ventas" del analista

**Files:**
- Modify: `proyectos/2026-06-10-agente-excepcion-demanda/agent_tools.py`
- Create: `proyectos/2026-06-10-agente-excepcion-demanda/probes/probe_get_evidence.py`

- [ ] **Step 1: Agregar `get_evidence` a agent_tools.py**

```python
POS_STATES = ['paid', 'done', 'invoiced']


def get_evidence(product_id: int, weeks_back: int = 12) -> dict:
    """Evidencia que un planner miraria para diagnosticar el SKU. READ-ONLY."""
    o = OdooReader()
    import datetime as _dt
    today = _dt.date.today()
    d0 = today - timedelta(days=weeks_back * 7)

    prod = o.search_read('product.product', [('id', '=', product_id)],
                         fields=['name', 'default_code', 'list_price', 'categ_id'])
    info = prod[0] if prod else {}

    # venta diaria agregada (ultimas weeks_back semanas)
    grp_day = o.execute('pos.order.line', 'read_group',
                        [('product_id', '=', product_id),
                         ('order_id.date_order', '>=', d0.isoformat() + ' 00:00:00'),
                         ('order_id.state', 'in', POS_STATES)],
                        ['qty:sum', 'price_subtotal:sum'], ['order_id.date_order:week'], lazy=False)
    semanas = []
    for g in grp_day:
        rng = (g.get('__range') or {}).get('order_id.date_order:week') or {}
        semanas.append({'semana': rng.get('from'), 'qty': round(float(g.get('qty') or 0.0), 1)})
    semanas.sort(key=lambda x: x['semana'] or '')

    # eventos de precio recientes
    eventos = []
    for r in o.search_read('x_price_coreccion',
                           [('x_studio_product_id', '=', product_id),
                            ('x_studio_target_week_start', '>=', d0.isoformat())],
                           fields=['x_studio_target_week_start', 'x_studio_var_pct',
                                   'x_studio_tipo_alerta', 'x_studio_sensing_estado'],
                           order='x_studio_target_week_start desc'):
        if abs(float(r.get('x_studio_var_pct') or 0.0)) > 0.001:
            eventos.append({'semana': r['x_studio_target_week_start'],
                            'var_pct': round(float(r['x_studio_var_pct']) * 100, 1),
                            'tipo': r.get('x_studio_tipo_alerta'),
                            'sensing': r.get('x_studio_sensing_estado')})

    # quiebres recientes (nº dias/salas)
    qb = o.search_read('x_stock_balance_daily',
                       ['&', ('x_studio_product_id', '=', product_id),
                        '&', ('x_studio_date', '>=', d0.isoformat()),
                        '|', ('x_studio_stockout', '=', True),
                        ('x_studio_stockout_partial', '=', True)],
                       fields=['x_studio_date', 'x_studio_team_id'])
    quiebre_dias = len({(r['x_studio_date'], _m2o(r.get('x_studio_team_id'))) for r in qb})

    # forecast vs real reciente (del backtest)
    fr = o.search_read('x_forecast_backtest', [('x_studio_product_id', '=', product_id)],
                       fields=['x_studio_target_week_start', 'x_studio_forecast_qty',
                               'x_studio_real_qty', 'x_studio_series_type'],
                       order='x_studio_target_week_start desc', limit=8 * 12)
    hist = {}
    for r in fr:
        w = r['x_studio_target_week_start']
        a = hist.setdefault(w, [0.0, 0.0])
        a[0] += float(r.get('x_studio_forecast_qty') or 0.0)
        a[1] += float(r.get('x_studio_real_qty') or 0.0)
    fc_vs_real = [{'semana': w, 'fcst': round(v[0], 1), 'real': round(v[1], 1)}
                  for w, v in sorted(hist.items())][-weeks_back:]
    series_type = fr[0]['x_studio_series_type'] if fr else None

    return {'producto': {'id': product_id, 'nombre': info.get('name'),
                         'codigo': info.get('default_code'), 'list_price': info.get('list_price'),
                         'categoria': (info.get('categ_id') or [0, ''])[1], 'series_type': series_type},
            'venta_semanal': semanas, 'eventos_precio': eventos,
            'quiebre_dias_sala': quiebre_dias, 'forecast_vs_real': fc_vs_real}
```

- [ ] **Step 2: Escribir el probe**

```python
# probes/probe_get_evidence.py
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent_tools import list_exceptions, get_evidence

pid = list_exceptions(weeks=4, top_n=1)[0]['product_id']
ev = get_evidence(pid)
assert {'producto', 'venta_semanal', 'eventos_precio', 'forecast_vs_real'} <= set(ev)
assert ev['producto']['nombre'], 'sin nombre'
print(json.dumps(ev, ensure_ascii=False, indent=1, default=str)[:1500])
```

- [ ] **Step 3: Correr y verificar**

Run: `python probes/probe_get_evidence.py`
Esperado: dict con producto, serie semanal de venta, eventos de precio (si los hay), quiebres, y forecast_vs_real. Coherente con el SKU top.

- [ ] **Step 4: Commit**

```bash
git add "proyectos/2026-06-10-agente-excepcion-demanda/agent_tools.py" "proyectos/2026-06-10-agente-excepcion-demanda/probes/probe_get_evidence.py"
git commit -m "agente excepcion: tool get_evidence (venta diaria, eventos, quiebre, fcst-vs-real)"
```

---

## Task 3: Tool `run_sensing_gate` — FVA esperado de la corrección

**Files:**
- Modify: `proyectos/2026-06-10-agente-excepcion-demanda/agent_tools.py`
- Create: `proyectos/2026-06-10-agente-excepcion-demanda/probes/probe_gate.py`

- [ ] **Step 1: Agregar `run_sensing_gate` a agent_tools.py**

Regla validada (`validar_layer_pcorr.py`): nivel_medido = venta de los últimos 7 días antes del cutoff (=MM7×7); ds-activo si días_post-evento≥7 y sin quiebre material. FVA = WAPE_base − WAPE_ds sobre las semanas recientes de ese SKU.

```python
CONF_DAYS = 7
QB_SALAS = 3
FACTOR_MIN, FACTOR_MAX = 0.2, 5.0


def run_sensing_gate(product_id: int, weeks: int = 8) -> dict:
    """Backtest del demand sensing para ESE SKU. Devuelve nivel medido y FVA (pp). READ-ONLY."""
    o = OdooReader()
    wk = _recent_weeks(o, weeks)
    # evento mas reciente
    ev_rows = o.search_read('x_price_coreccion', [('x_studio_product_id', '=', product_id)],
                            fields=['x_studio_target_week_start', 'x_studio_var_pct'])
    ev_dates = [datetime.strptime(r['x_studio_target_week_start'][:10], '%Y-%m-%d').date()
                for r in ev_rows if abs(float(r.get('x_studio_var_pct') or 0.0)) > 0.001]
    if not ev_dates:
        return {'aplica': False, 'motivo': 'sin evento de precio', 'fva_pp': 0.0}
    ev_last = max(ev_dates)

    rows = []
    nivel_actual = None
    for w in wk:
        target = datetime.strptime(w, '%Y-%m-%d').date()
        cutoff = target - timedelta(days=1)
        win_from = cutoff - timedelta(days=6)
        bt = o.search_read('x_forecast_backtest',
                           [('x_studio_target_week_start', '=', w),
                            ('x_studio_product_id', '=', product_id)],
                           fields=['x_studio_forecast_qty', 'x_studio_real_qty'])
        motor = sum(float(r.get('x_studio_forecast_qty') or 0.0) for r in bt)
        real = sum(float(r.get('x_studio_real_qty') or 0.0) for r in bt)
        if motor <= 0 and real <= 0:
            continue
        # quiebre en ventana de medicion
        sb = o.search_read('x_stock_balance_daily',
                           ['&', ('x_studio_product_id', '=', product_id),
                            '&', ('x_studio_date', '>=', win_from.isoformat()),
                            ('x_studio_date', '<=', cutoff.isoformat()),
                            '|', ('x_studio_stockout', '=', True),
                            ('x_studio_stockout_partial', '=', True)],
                           fields=['x_studio_team_id'])
        qb = len({_m2o(r.get('x_studio_team_id')) for r in sb}) >= QB_SALAS
        grp = o.execute('pos.order.line', 'read_group',
                        [('product_id', '=', product_id),
                         ('order_id.date_order', '>=', win_from.isoformat() + ' 00:00:00'),
                         ('order_id.date_order', '<=', cutoff.isoformat() + ' 23:59:59'),
                         ('order_id.state', 'in', POS_STATES)],
                        ['qty:sum'], [], lazy=False)
        lvl = float(grp[0]['qty']) if grp and grp[0].get('qty') else 0.0
        applied = motor
        if (cutoff - ev_last).days >= CONF_DAYS and not qb and motor > 0:
            applied = motor * min(max(lvl / motor, FACTOR_MIN), FACTOR_MAX)
            nivel_actual = lvl
        rows.append({'real': real, 'motor': motor, 'ds': applied, 'qb': qb})

    clean = [r for r in rows if not r['qb']]
    R = sum(r['real'] for r in clean)
    if R <= 0:
        return {'aplica': False, 'motivo': 'sin venta limpia para medir', 'fva_pp': 0.0}
    wape_motor = sum(abs(r['motor'] - r['real']) for r in clean) / R * 100
    wape_ds = sum(abs(r['ds'] - r['real']) for r in clean) / R * 100
    return {'aplica': True, 'nivel_medido': round(nivel_actual, 1) if nivel_actual is not None else None,
            'wape_base': round(wape_motor, 1), 'wape_ds': round(wape_ds, 1),
            'fva_pp': round(wape_motor - wape_ds, 2), 'n_semanas': len(clean)}
```

- [ ] **Step 2: Escribir el probe**

```python
# probes/probe_gate.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent_tools import list_exceptions, run_sensing_gate

# tomar una excepcion de causa 'evento'
ev = [e for e in list_exceptions(weeks=4, top_n=50) if e['causa'] == 'evento']
assert ev, 'no hay excepciones de evento para probar el gate'
g = run_sensing_gate(ev[0]['product_id'])
print(ev[0]['product_name'], '->', g)
assert 'fva_pp' in g
```

- [ ] **Step 3: Correr y verificar**

Run: `python probes/probe_gate.py`
Esperado: para un SKU de evento devuelve `aplica=True`, `nivel_medido`, `wape_base`, `wape_ds`, `fva_pp`. En cervezas de evento el `fva_pp` debe rondar +1 a +3 (consistente con el gate global).

- [ ] **Step 4: Commit**

```bash
git add "proyectos/2026-06-10-agente-excepcion-demanda/agent_tools.py" "proyectos/2026-06-10-agente-excepcion-demanda/probes/probe_gate.py"
git commit -m "agente excepcion: tool run_sensing_gate (FVA esperado por SKU)"
```

---

## Task 4: Modelo `x_forecast_override` + cliente de escritura

**Files:**
- Create: `proyectos/2026-06-10-agente-excepcion-demanda/odoo_writer.py`
- Modify: `proyectos/2026-06-10-agente-excepcion-demanda/agent_tools.py`
- Create: `proyectos/2026-06-10-agente-excepcion-demanda/probes/probe_propose.py`
- Doc: `proyectos/2026-06-10-agente-excepcion-demanda/PROMOCION.md`

- [ ] **Step 1: Documentar el modelo Studio que crea Marco**

Escribir en `PROMOCION.md` la spec del modelo `x_forecast_override` (Marco lo crea en Studio antes de correr Task 4):

```markdown
# Modelo x_forecast_override (Studio — crear antes de correr el agente)
Campos:
- x_name (Char, requerido) — clave logica "pid:tid:week"
- x_studio_product_id (Many2one product.product)
- x_studio_team_id (Many2one crm.team)  — vacio = todas las salas
- x_studio_week_start (Date)
- x_studio_action (Selection: reset_level | cleanse_history | no_action)
- x_studio_value (Float)
- x_studio_reason (Text)
- x_studio_evidence (Text)
- x_studio_expected_fva (Float)
- x_studio_status (Selection: pendiente | aprobado | rechazado, default 'pendiente')
- x_studio_source (Char)
```

- [ ] **Step 2: Escribir `odoo_writer.py` (cliente de escritura mínimo)**

```python
# odoo_writer.py — cliente XML-RPC de ESCRITURA acotado a x_forecast_override.
# Separado de OdooReader (read-only) a proposito: el unico modelo escribible aqui.
from __future__ import annotations
import xmlrpc.client
from pathlib import Path

ALLOWED_WRITE_MODELS = {'x_forecast_override'}


def _env():
    p = Path(__file__).resolve().parents[2] / '.env'
    out = {}
    for line in p.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


class OdooWriter:
    def __init__(self):
        c = _env()
        self.db, self.user, self._key = c['ODOO_DB'], c['ODOO_USER'], c['ODOO_API_KEY']
        common = xmlrpc.client.ServerProxy(f"{c['ODOO_URL']}/xmlrpc/2/common")
        self.uid = common.authenticate(self.db, self.user, self._key, {})
        if not self.uid:
            raise PermissionError('Auth fallida (ODOO_USER/ODOO_API_KEY)')
        self.models = xmlrpc.client.ServerProxy(f"{c['ODOO_URL']}/xmlrpc/2/object")

    def create(self, model: str, vals: dict) -> int:
        if model not in ALLOWED_WRITE_MODELS:
            raise PermissionError(f'Escritura bloqueada para {model!r}')
        return self.models.execute_kw(self.db, self.uid, self._key, model, 'create', [vals])
```

- [ ] **Step 3: Agregar `propose_override` a agent_tools.py**

```python
def propose_override(product_id: int, week_start: str, action: str, value: float,
                     reason: str, evidence: str, expected_fva: float,
                     team_id: int = None, product_name: str = '') -> dict:
    """Crea una propuesta en x_forecast_override (estado pendiente). ESCRIBE."""
    from odoo_writer import OdooWriter
    if action not in ('reset_level', 'cleanse_history', 'no_action'):
        return {'ok': False, 'error': 'action invalida'}
    w = OdooWriter()
    name = '%s:%s:%s' % (product_id, team_id or 'ALL', week_start)
    vals = {'x_name': name, 'x_studio_product_id': product_id,
            'x_studio_week_start': week_start, 'x_studio_action': action,
            'x_studio_value': float(value), 'x_studio_reason': reason[:2000],
            'x_studio_evidence': evidence[:4000], 'x_studio_expected_fva': float(expected_fva),
            'x_studio_status': 'pendiente', 'x_studio_source': 'agent_v1'}
    if team_id:
        vals['x_studio_team_id'] = team_id
    rid = w.create('x_forecast_override', vals)
    return {'ok': True, 'id': rid, 'name': name}
```

- [ ] **Step 4: Probe (crea 1 propuesta de prueba y la deja pendiente)**

```python
# probes/probe_propose.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent_tools import propose_override

r = propose_override(product_id=9407, week_start='2026-06-01', action='no_action',
                     value=0.0, reason='probe de validacion', evidence='n/a',
                     expected_fva=0.0, product_name='STELLA (probe)')
print(r)
assert r['ok'] and r['id'], 'no creo la propuesta'
```

- [ ] **Step 5: Correr (requiere modelo Studio creado) y verificar**

Run: `python probes/probe_propose.py`
Esperado: `{'ok': True, 'id': <int>, ...}`. Verificar en Odoo que la fila quedó en `pendiente`. Borrar la fila de prueba a mano.
(Si el modelo aún no existe en Studio, este task queda bloqueado hasta que Marco lo cree — el resto del agente —Tasks 1-3, 5— no depende de la escritura.)

- [ ] **Step 6: Commit**

```bash
git add "proyectos/2026-06-10-agente-excepcion-demanda/odoo_writer.py" "proyectos/2026-06-10-agente-excepcion-demanda/agent_tools.py" "proyectos/2026-06-10-agente-excepcion-demanda/probes/probe_propose.py" "proyectos/2026-06-10-agente-excepcion-demanda/PROMOCION.md"
git commit -m "agente excepcion: modelo x_forecast_override + tool propose_override + writer"
```

---

## Task 5: `agent.py` — el agente (loop de tool-use)

**Files:**
- Create: `proyectos/2026-06-10-agente-excepcion-demanda/agent.py`

- [ ] **Step 1: Confirmar dependencia y credencial**

Run: `python -c "import anthropic; print(anthropic.__version__)"`
Esperado: imprime versión (si falla: `pip install anthropic`). Agregar `ANTHROPIC_API_KEY=...` al `.env` de la raíz.

- [ ] **Step 2: Escribir el system prompt y el schema de tools**

```python
# agent.py
from __future__ import annotations
import os, json, argparse
from pathlib import Path
from datetime import datetime

import anthropic
import agent_tools as T

ROOT = Path(__file__).resolve().parents[2]
for line in (ROOT / '.env').read_text(encoding='utf-8').splitlines():
    if line.strip().startswith('ANTHROPIC_API_KEY'):
        os.environ['ANTHROPIC_API_KEY'] = line.split('=', 1)[1].strip().strip('"').strip("'")

MODEL = 'claude-sonnet-4-6'

SYSTEM = """Eres un Analista de Demanda por excepción para un retailer (OH Market).
Replicas el rol del planner en el Demand Review (SAP IBP / IBF): trabajas la lista de
excepción, miras la venta, diagnosticas la causa del error y PROPONES una corrección
MEDIDA. NO pronosticas ni inventas numeros: el numero sale del gate de demand sensing.

Reglas duras:
- Eres PROPOSE-ONLY. Nunca aplicas nada; solo creas propuestas en estado pendiente.
- Alcance v1: solo SKU de causa 'evento' (cervezas). Para otras causas, propone 'no_action'
  con la razon (NO corrijas varianza irreducible, cola, fantasma ni quiebre).
- Solo propones 'reset_level' si run_sensing_gate da fva_pp > 0. Si fva_pp <= 0 -> 'no_action'.
- 'cleanse_history' solo si la evidencia muestra un outlier de DATO claro (pico aislado sin
  evento ni explicacion). Si dudas -> 'no_action'.
- Para cada excepcion: get_evidence -> diagnostica -> (si evento) run_sensing_gate ->
  propose_override. Razon y evidencia siempre citando los numeros que miraste.

Proceso por excepcion (en orden): list_exceptions ya te dio la lista. Para cada una decides."""

TOOLS = [
    {'name': 'list_exceptions',
     'description': 'Top excepciones del forecast por impacto-$ con causa clasificada.',
     'input_schema': {'type': 'object', 'properties': {
         'weeks': {'type': 'integer'}, 'top_n': {'type': 'integer'}}, 'required': []}},
    {'name': 'get_evidence',
     'description': 'Evidencia de un SKU: venta semanal, eventos de precio, quiebres, forecast-vs-real.',
     'input_schema': {'type': 'object', 'properties': {
         'product_id': {'type': 'integer'}}, 'required': ['product_id']}},
    {'name': 'run_sensing_gate',
     'description': 'Backtest del demand sensing para un SKU. Devuelve nivel_medido y fva_pp.',
     'input_schema': {'type': 'object', 'properties': {
         'product_id': {'type': 'integer'}}, 'required': ['product_id']}},
    {'name': 'propose_override',
     'description': 'Crea una propuesta de override (pendiente). action: reset_level|cleanse_history|no_action.',
     'input_schema': {'type': 'object', 'properties': {
         'product_id': {'type': 'integer'}, 'week_start': {'type': 'string'},
         'action': {'type': 'string'}, 'value': {'type': 'number'},
         'reason': {'type': 'string'}, 'evidence': {'type': 'string'},
         'expected_fva': {'type': 'number'}, 'team_id': {'type': 'integer'},
         'product_name': {'type': 'string'}},
         'required': ['product_id', 'week_start', 'action', 'value', 'reason', 'evidence', 'expected_fva']}},
]
```

- [ ] **Step 3: Escribir el dispatcher y el loop de tool-use**

```python
def _dispatch(name, args, dry_run):
    if name == 'list_exceptions':
        return T.list_exceptions(weeks=args.get('weeks', 4), top_n=args.get('top_n', 20))
    if name == 'get_evidence':
        return T.get_evidence(args['product_id'])
    if name == 'run_sensing_gate':
        return T.run_sensing_gate(args['product_id'])
    if name == 'propose_override':
        if dry_run:
            return {'ok': True, 'dry_run': True, 'propuesta': args}
        return T.propose_override(**args)
    return {'error': 'tool desconocida'}


def run(top_n=10, dry_run=True):
    client = anthropic.Anthropic()
    msgs = [{'role': 'user', 'content':
             f'Procesa las top {top_n} excepciones. Para cada una: evidencia, diagnostico, '
             f'y propuesta (reset_level con FVA, o no_action con razon). Al final, resume '
             f'que propusiste y por que.'}]
    proposals = []
    while True:
        resp = client.messages.create(model=MODEL, max_tokens=4096, system=SYSTEM,
                                       tools=TOOLS, messages=msgs)
        msgs.append({'role': 'assistant', 'content': resp.content})
        if resp.stop_reason != 'tool_use':
            final = ''.join(b.text for b in resp.content if b.type == 'text')
            return final, proposals
        results = []
        for b in resp.content:
            if b.type == 'tool_use':
                out = _dispatch(b.name, b.input, dry_run)
                if b.name == 'propose_override':
                    proposals.append(out)
                results.append({'type': 'tool_result', 'tool_use_id': b.id,
                                'content': json.dumps(out, ensure_ascii=False, default=str)})
        msgs.append({'role': 'user', 'content': results})


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--top', type=int, default=10)
    ap.add_argument('--apply', action='store_true', help='escribe propuestas (default dry-run)')
    args = ap.parse_args()
    brief, props = run(top_n=args.top, dry_run=not args.apply)
    out = Path(__file__).parent / 'resultados'
    out.mkdir(exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    (out / f'brief_{stamp}.md').write_text(brief, encoding='utf-8')
    print(brief)
    print(f'\n{len(props)} propuestas. brief -> resultados/brief_{stamp}.md')
```

- [ ] **Step 4: Commit**

```bash
git add "proyectos/2026-06-10-agente-excepcion-demanda/agent.py"
git commit -m "agente excepcion: runner con loop de tool-use (Messages API, propose-only)"
```

---

## Task 6: Dry-run end-to-end + validación de criterio

**Files:**
- Create: `proyectos/2026-06-10-agente-excepcion-demanda/resultados/` (output)

- [ ] **Step 1: Correr el agente en dry-run**

Run: `python agent.py --top 8`
Esperado: el agente recorre 8 excepciones, llama get_evidence/run_sensing_gate, y emite un brief. NO escribe a Odoo (dry-run). Imprime las propuestas con `dry_run: True`.

- [ ] **Step 2: Validar el criterio contra casos canónicos**

Revisar el brief y confirmar (criterio de aceptación del diseño §7):
- Un SKU de evento (ej. Stella/Budweiser) → propuesta `reset_level` con `expected_fva > 0` y razón citando el evento de precio.
- Un SKU smooth de alto impacto sin evento (ej. Cristal sin evento esa semana) → `no_action` con razón "varianza irreducible".
- Un SKU con quiebre → `no_action` reconociendo dato censurado.

Si el agente propone corregir varianza/cola/fantasma → ajustar el SYSTEM prompt (reforzar la regla de alcance) y re-correr. Iterar el prompt hasta que el criterio se cumpla.

- [ ] **Step 3: Correr con escritura real (1 vez, top chico)**

Run: `python agent.py --top 5 --apply`
Esperado: crea ≤5 filas en `x_forecast_override` (pendiente). Verificar en Odoo: cada propuesta tiene reason/evidence/expected_fva coherentes. Aprobar 1 a mano para probar el consumo (Task 7).

- [ ] **Step 4: Commit del brief de validación**

```bash
git add "proyectos/2026-06-10-agente-excepcion-demanda/resultados/"
git commit -m "agente excepcion: dry-run validado contra casos canonicos"
```

---

## Task 7: Consumo de aprobados en la capa demand sensing (promoción)

**Files:**
- Modify: `proyectos/2026-06-01-demand-sensing/OH Demand Sensing.py` (Server Action)

- [ ] **Step 1: Agregar lectura de overrides aprobados a OH Demand Sensing.py**

Antes del bloque que computa el factor por evento, leer los overrides aprobados de la semana objetivo y, para esos SKU, usar el `value` aprobado en vez de recalcular. Insertar tras resolver `target_date` (safe_eval: sin getattr/import, `.write()` para escribir):

```python
        # ---- overrides aprobados (del agente analista) tienen prioridad ----
        ov_level = {}   # pid -> nivel aprobado (reset_level)
        if 'x_forecast_override' in env:
            OV = env['x_forecast_override'].sudo()
            for r in OV.search([('x_studio_status', '=', 'aprobado'),
                                ('x_studio_week_start', '=', target_date.isoformat()),
                                ('x_studio_action', '=', 'reset_level')]):
                if r.x_studio_product_id:
                    ov_level[r.x_studio_product_id.id] = float(r.x_studio_value or 0.0)
```

Y en el bloque de escritura por fila, si el pid tiene override aprobado, usar ese nivel total repartido por team (mismo PROXY proporcional que el factor): `factor = ov_level[p] / motor_total[p]` antes de aplicar el clamp y escribir `x_studio_mu_week_adjusted`. Documentar en el header de la SA que el override aprobado manda sobre el sensing automático.

- [ ] **Step 2: Validar offline el consumo**

Run (read-only, simula): `python proyectos/2026-06-01-demand-sensing/validar_layer_pcorr.py`
Esperado: sigue reproduciendo el gate (la lógica de sensing no cambió; el override solo sustituye el nivel para SKU aprobados). Confirmar que no rompió el camino base.

- [ ] **Step 3: Commit**

```bash
git add "proyectos/2026-06-01-demand-sensing/OH Demand Sensing.py"
git commit -m "demand sensing: consume overrides aprobados del agente (prioridad sobre sensing auto)"
```

---

## Pasos de promoción (Marco ejecuta, fuera del plan de código)
1. Crear modelo Studio `x_forecast_override` (spec en PROMOCION.md) — desbloquea Task 4-7.
2. `ANTHROPIC_API_KEY` en el `.env` de la raíz.
3. Correr `agent.py --top N --apply` semanal (manual al inicio; cron/SA después).
4. Aprobar/rechazar propuestas en Odoo.
5. Confirmar que corrió bien → recién ahí los commits suben a git (flujo CLAUDE.md).

## Verificación end-to-end
- Probes 1-4 pasan contra Odoo live (read-only salvo el create de prueba).
- `agent.py --top 8` (dry-run): brief con diagnóstico correcto en casos canónicos.
- 1 override aprobado → `OH Demand Sensing` lo escribe en `mu_week_adjusted` → Stock lo consume (COALESCE).
- Semana siguiente: medir FVA de los aprobados (¿mejoraron?) con el monitor/gate — auto-auditoría del agente.

## Self-review (cobertura del spec)
- §6 arquitectura → Tasks 1-5 (tools + agente) + Task 7 (consumo). ✓
- §6 modelo x_forecast_override → Task 4. ✓
- propose-only + FVA-gate + alcance evento → SYSTEM prompt (Task 5) + validación (Task 6). ✓
- write path (decisión a) → odoo_writer.py (Task 4). ✓
- auto-medición → Verificación end-to-end. ✓
