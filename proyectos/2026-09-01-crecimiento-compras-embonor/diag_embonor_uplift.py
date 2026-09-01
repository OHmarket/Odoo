# ============================================================
# DIAG — Crecimiento de compras Coca-Cola Embonor, semana del 18-sep
# ============================================================
#
# READ-ONLY. Corre DESDE FUERA de Odoo (tu PC) via XML-RPC, usando
# shared/odoo_xmlrpc.OdooReader (whitelist de metodos: nada de write).
#
#   cd <raiz del repo>
#   python "proyectos/2026-09-01-crecimiento-compras-embonor/diag_embonor_uplift.py"
#
# Requiere .env en la raiz con ODOO_URL / ODOO_DB / ODOO_USER / ODOO_API_KEY.
#
# Metodo (ver diseno.md): indice de evento por ratio-to-moving-median (RMA,
# canon de descomposicion multiplicativa / seasonal profile SAP IBP):
#
#     indice = valor(semana_evento) / mediana(semanas limpias alrededor)
#
# Baseline en ventana SIMETRICA [-8,-3] U [+3,+8] para cancelar tendencia.
# Se mide en dos series independientes:
#   - sell-in : facturas de compra Embonor (account.move, CLP netos)
#   - sell-out: x_pos_week_sku_sale de los SKU del proveedor (unidades y CLP)
#
# PROXY: con 1-2 eventos observados el indice es una MEDICION, no una
# distribucion. El rango que se imprime es dispersion del baseline (MAD),
# no un intervalo de confianza frecuentista. Reportar siempre como estimacion.
# ============================================================

import sys
import math
import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

OUT_DIR = Path(__file__).resolve().parent / 'resultados'

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SUPPLIER_PATTERN = 'embonor'         # ilike sobre res.partner.name
TARGET_YEAR = 2026                   # ano del evento a estimar
HISTORY_YEARS = [2024, 2025]         # anos con evento observado a medir
DATE_FROM = '2024-01-01'             # piso de historia a traer

SALE_MODEL = 'x_pos_week_sku_sale'
PROV_FIELD = 'x_studio_proveedor_compra'   # char autoritativo (ver Analisis de Stock v9.18.0)

BASE_OFF_MIN = 3                     # baseline: semanas +-3 .. +-8 del evento
BASE_OFF_MAX = 8
MIN_BASE_WEEKS = 4                   # menos que esto -> baseline no confiable
MAX_INVOICE_ROWS = 20000             # guard de costo de query

# ---------------------------------------------------------------------------
# 1) Helpers puros (sin Odoo) — testeados en test_uplift_math.py
# ---------------------------------------------------------------------------


def oh_week_start(d):
    """Lunes de la semana de d (estandar OH: lunes-domingo)."""
    return d - datetime.timedelta(days=d.weekday())


def event_week_start(year):
    """Lunes de la semana que CONTIENE el 18 de septiembre de ese ano.

    Se resuelve por fecha y no por numero ISO fijo: en 2021/2022 el 18 cayo
    fin de semana y la semana del evento es la 37, no la 38.
    """
    return oh_week_start(datetime.date(year, 9, 18))


def week_offset(week_start, k):
    return week_start + datetime.timedelta(weeks=k)


def ly_364(d):
    """Estandar OH de comparable ano anterior: -364 dias (mismo weekday)."""
    return d - datetime.timedelta(days=364)


def median(values):
    vals = sorted(v for v in values if v is not None)
    n = len(vals)
    if n == 0:
        return None
    mid = n // 2
    if n % 2 == 1:
        return float(vals[mid])
    return (float(vals[mid - 1]) + float(vals[mid])) / 2.0


def mad(values):
    """Median absolute deviation (sin escalar)."""
    med = median(values)
    if med is None:
        return None
    return median([abs(float(v) - med) for v in values])


def baseline_weeks(week_event, have_weeks, symmetric=True):
    """Semanas limpias alrededor del evento: [-8,-3] y (si symmetric) [+3,+8].

    have_weeks: set/dict de week_start con dato disponible.
    """
    out = []
    for k in range(BASE_OFF_MIN, BASE_OFF_MAX + 1):
        pre = week_offset(week_event, -k)
        if pre in have_weeks:
            out.append(pre)
        if symmetric:
            post = week_offset(week_event, k)
            if post in have_weeks:
                out.append(post)
    return sorted(out)


def baseline_level(weekly, week_event, symmetric=True):
    """Baseline robusto (mediana) + dispersion relativa.

    Retorna dict con level, n, rel_disp (MAD escalada / mediana) o None si no
    hay suficientes semanas.
    """
    weeks = baseline_weeks(week_event, weekly, symmetric=symmetric)
    if len(weeks) < MIN_BASE_WEEKS:
        return None
    vals = [float(weekly[w]) for w in weeks]
    level = median(vals)
    if not level:
        return None
    scaled_mad = 1.4826 * (mad(vals) or 0.0)
    return {
        'level': level,
        'n': len(vals),
        'weeks': weeks,
        'rel_disp': scaled_mad / level if level else None,
    }


def uplift_index(weekly, week_event, symmetric=True):
    """Indice de evento = valor(semana evento) / baseline robusto.

    Retorna dict con index, value, base, n_base, lo, hi. El rango lo/hi usa el
    error estandar de la mediana del baseline (rel_disp / sqrt(n)); NO es una
    CI del evento (n=1 evento). Ver PROXY en el header.
    """
    if week_event not in weekly:
        return None
    base = baseline_level(weekly, week_event, symmetric=symmetric)
    if base is None:
        return None
    value = float(weekly[week_event])
    index = value / base['level']
    rel = (base['rel_disp'] or 0.0) / math.sqrt(base['n'])
    return {
        'index': index,
        'value': value,
        'base': base['level'],
        'n_base': base['n'],
        'lo': index * (1.0 - rel),
        'hi': index * (1.0 + rel),
    }


def neighbour_indices(weekly, week_event, offsets=(-2, -1, 0, 1, 2)):
    """Indice de cada semana vecina contra el MISMO baseline del evento.

    En compras el peak se reparte entre la semana previa (llenado) y la del
    evento, y despues viene payback. Sin esto se cuenta dos veces.
    """
    base = baseline_level(weekly, week_event)
    if base is None:
        return {}
    out = {}
    for k in offsets:
        w = week_offset(week_event, k)
        if w in weekly:
            out[k] = float(weekly[w]) / base['level']
    return out


def level_recent(weekly, week_target):
    """Nivel base actual: mediana de [-8,-3] respecto de la semana objetivo.

    Ventana solo-pre (el futuro no existe todavia) -> sesgada por tendencia.
    Se reporta junto al mismo calculo solo-pre del ano historico para hacer
    visible ese sesgo.
    """
    return baseline_level(weekly, week_target, symmetric=False)


# ---------------------------------------------------------------------------
# 2) Lectura Odoo (read-only)
# ---------------------------------------------------------------------------


def _parse_group_date(row, gkey):
    """Extrae la fecha de una fila de read_group agrupada por <campo>:day.

    Odoo devuelve el label formateado por lang; lo confiable es __range
    (v14+) y, como fallback, el __domain de la fila.
    """
    rng = row.get('__range') or {}
    entry = rng.get(gkey) or {}
    raw = entry.get('from')
    if raw:
        return datetime.date.fromisoformat(str(raw)[:10])

    field = gkey.split(':')[0]
    for cond in (row.get('__domain') or []):
        if isinstance(cond, (list, tuple)) and len(cond) == 3:
            if cond[0] == field and cond[1] in ('>=', '>'):
                return datetime.date.fromisoformat(str(cond[2])[:10])

    label = row.get(gkey)
    for fmt in ('%Y-%m-%d', '%d %b %Y', '%d %B %Y'):
        try:
            return datetime.datetime.strptime(str(label), fmt).date()
        except (ValueError, TypeError):
            continue
    return None


def _chunks(seq, size=800):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def find_supplier_partners(odoo):
    rows = odoo.search_read(
        'res.partner',
        domain=[('name', 'ilike', SUPPLIER_PATTERN)],
        fields=['id', 'name', 'parent_id'],
        limit=50,
    )
    # Solo raices: las facturas se buscan con child_of, asi entran los contactos hijo.
    roots = [r for r in rows if not r.get('parent_id')]
    return rows, [r['id'] for r in (roots or rows)]


def find_supplier_products(odoo, partner_ids):
    """product.product del proveedor. Fuente autoritativa: campo 'Proveedor
    Compra' del producto (x_studio_proveedor_compra). Se une con supplierinfo
    como respaldo, y se reporta cuanto aporto cada fuente.
    """
    tmpl_fields = odoo.fields_get('product.template', ['string'])
    tmpl_ids = set()
    src = {'proveedor_compra': 0, 'supplierinfo': 0}

    if PROV_FIELD in tmpl_fields:
        rows = odoo.search_read(
            'product.template',
            domain=[(PROV_FIELD, 'ilike', SUPPLIER_PATTERN)],
            fields=['id'],
        )
        src['proveedor_compra'] = len(rows)
        tmpl_ids.update(r['id'] for r in rows)

    si = odoo.search_read(
        'product.supplierinfo',
        domain=[('partner_id', 'child_of', partner_ids)],
        fields=['product_tmpl_id', 'product_id'],
    )
    src['supplierinfo'] = len(si)
    for r in si:
        if r.get('product_tmpl_id'):
            tmpl_ids.add(r['product_tmpl_id'][0])

    pids = []
    for chunk in _chunks(sorted(tmpl_ids)):
        pids.extend(
            r['id'] for r in odoo.search_read(
                'product.product',
                domain=[('product_tmpl_id', 'in', chunk)],
                fields=['id'],
            )
        )
    return sorted(set(pids)), sorted(tmpl_ids), src


def sellin_weekly(odoo, partner_ids, date_from):
    """CLP netos de facturas de compra por semana OH. Notas de credito restan."""
    domain = [
        ('move_type', 'in', ['in_invoice', 'in_refund']),
        ('state', '=', 'posted'),
        ('partner_id', 'child_of', partner_ids),
        ('invoice_date', '>=', date_from),
    ]
    count = odoo.search_count('account.move', domain)
    if count > MAX_INVOICE_ROWS:
        raise RuntimeError(
            'account.move devolveria %s filas (> %s). Subir DATE_FROM o migrar '
            'a read_group antes de correr esto contra produccion.' % (count, MAX_INVOICE_ROWS)
        )

    am_fields = odoo.fields_get('account.move', ['string'])
    signed = 'amount_untaxed_signed' in am_fields
    fields = ['invoice_date', 'move_type']
    fields.append('amount_untaxed_signed' if signed else 'amount_untaxed')

    weekly = {}
    for row in odoo.search_read('account.move', domain=domain, fields=fields):
        raw = row.get('invoice_date')
        if not raw:
            continue
        d = datetime.date.fromisoformat(str(raw)[:10])
        if signed:
            amount = float(row.get('amount_untaxed_signed') or 0.0)
        else:
            amount = float(row.get('amount_untaxed') or 0.0)
            if row.get('move_type') == 'in_refund':
                amount = -amount
        ws = oh_week_start(d)
        weekly[ws] = weekly.get(ws, 0.0) + amount
    return weekly, count


def sellout_weekly(odoo, product_ids, date_from):
    """Venta POS semanal de los SKU del proveedor, por semana y por sala.

    read_group (NO search_read masivo): el grano sala x semana x SKU son
    ~100k filas; agrupado quedan ~1k.
    """
    gkey = '%s:day' % 'x_studio_week_start'
    per_team = {}   # {week_start: {team_id: (qty, clp)}}
    for chunk in _chunks(product_ids):
        rows = odoo.execute(
            SALE_MODEL, 'read_group',
            [('x_studio_product_id', 'in', chunk),
             ('x_studio_week_start', '>=', date_from)],
            ['x_studio_qty_sold', 'x_studio_sales_gross'],
            ['x_studio_week_start:day', 'x_studio_team_id'],
            lazy=False,
        )
        for row in rows:
            ws = _parse_group_date(row, gkey)
            if ws is None:
                continue
            team = row.get('x_studio_team_id')
            team_id = team[0] if isinstance(team, (list, tuple)) else (team or 0)
            qty = float(row.get('x_studio_qty_sold') or 0.0)
            clp = float(row.get('x_studio_sales_gross') or 0.0)
            slot = per_team.setdefault(ws, {}).setdefault(team_id, [0.0, 0.0])
            slot[0] += qty
            slot[1] += clp
    return per_team


def same_store_teams(per_team, windows):
    """Teams con venta > 0 en TODAS las ventanas dadas (control same-store)."""
    sets = []
    for weeks in windows:
        active = set()
        for ws in weeks:
            for team_id, (qty, _clp) in (per_team.get(ws) or {}).items():
                if qty > 0:
                    active.add(team_id)
        sets.append(active)
    if not sets:
        return set(), set()
    keep = set.intersection(*sets)
    dropped = set.union(*sets) - keep
    return keep, dropped


def collapse(per_team, teams=None, idx=0):
    out = {}
    for ws, by_team in per_team.items():
        total = 0.0
        for team_id, vals in by_team.items():
            if teams is not None and team_id not in teams:
                continue
            total += vals[idx]
        out[ws] = total
    return out


# ---------------------------------------------------------------------------
# 3) Reporte
# ---------------------------------------------------------------------------


def fmt_clp(x):
    return '{:>15,.0f}'.format(x).replace(',', '.')


def report_series(lines, title, weekly, week_event, offsets=range(-8, 9)):
    lines.append('')
    lines.append(title)
    lines.append('  semana        valor        vs baseline')
    base = baseline_level(weekly, week_event)
    for k in offsets:
        w = week_offset(week_event, k)
        if w not in weekly:
            continue
        val = weekly[w]
        ratio = (val / base['level']) if base and base['level'] else float('nan')
        mark = '  <== EVENTO' if k == 0 else ''
        lines.append('  %s %s   x%5.2f%s' % (w.isoformat(), fmt_clp(val), ratio, mark))
    if base:
        lines.append('  baseline (mediana de %d semanas limpias): %s' % (base['n'], fmt_clp(base['level'])))


def main():
    from shared.odoo_xmlrpc import OdooReader

    odoo = OdooReader()
    lines = []
    lines.append('=' * 78)
    lines.append('CRECIMIENTO DE COMPRAS — %s — semana del 18-sep-%s' % (SUPPLIER_PATTERN.upper(), TARGET_YEAR))
    lines.append('generado: %s' % datetime.datetime.now().isoformat(timespec='seconds'))
    lines.append('=' * 78)

    ws_target = event_week_start(TARGET_YEAR)
    lines.append('Semana objetivo (OH lun-dom): %s -> %s  (ISO %s)' % (
        ws_target, ws_target + datetime.timedelta(days=6), ws_target.isocalendar()[1]))

    # --- proveedor
    partners, partner_ids = find_supplier_partners(odoo)
    lines.append('')
    lines.append('Partners que matchean "%s": %d' % (SUPPLIER_PATTERN, len(partners)))
    for p in partners[:20]:
        lines.append('  [%s] %s%s' % (p['id'], p['name'], ' (hijo)' if p.get('parent_id') else ''))
    if not partner_ids:
        lines.append('SIN PARTNER: ajustar SUPPLIER_PATTERN.')
        print('\n'.join(lines))
        return

    # --- productos
    product_ids, tmpl_ids, src = find_supplier_products(odoo, partner_ids)
    lines.append('')
    lines.append('SKU del proveedor: %d templates -> %d variantes '
                 '(via %s: %d filas | supplierinfo: %d filas)'
                 % (len(tmpl_ids), len(product_ids), PROV_FIELD,
                    src['proveedor_compra'], src['supplierinfo']))

    # --- sell-in
    lines.append('')
    lines.append('-' * 78)
    lines.append('A) SELL-IN — facturas de compra (CLP netos, notas de credito restan)')
    lines.append('-' * 78)
    si_weekly, n_inv = sellin_weekly(odoo, partner_ids, DATE_FROM)
    if si_weekly:
        lines.append('%d facturas | cobertura %s .. %s' % (
            n_inv, min(si_weekly), max(si_weekly)))
    else:
        lines.append('Sin facturas de compra en el rango.')

    si_indices = {}
    for year in HISTORY_YEARS:
        we = event_week_start(year)
        idx = uplift_index(si_weekly, we)
        if idx:
            si_indices[year] = idx
            report_series(lines, 'Serie sell-in alrededor del evento %d (semana %s):' % (year, we), si_weekly, we)
            nb = neighbour_indices(si_weekly, we)
            lines.append('  indice evento %d: x%.2f  [%.2f - %.2f] sobre %d semanas de baseline'
                         % (year, idx['index'], idx['lo'], idx['hi'], idx['n_base']))
            lines.append('  reparto pre/post: ' + ' | '.join(
                'sem%+d x%.2f' % (k, v) for k, v in sorted(nb.items())))
            pair = None
            if -1 in nb:
                pair = (nb[-1] + nb[0]) / 2.0
                lines.append('  indice combinado semanas 37+38 (llenado + evento): x%.2f' % pair)
        else:
            lines.append('  %d: baseline insuficiente para medir indice de sell-in.' % year)

    # --- sell-out
    lines.append('')
    lines.append('-' * 78)
    lines.append('B) SELL-OUT — venta POS de los SKU del proveedor (%s)' % SALE_MODEL)
    lines.append('-' * 78)
    per_team = sellout_weekly(odoo, product_ids, DATE_FROM) if product_ids else {}

    so_indices = {}
    if per_team:
        lines.append('cobertura %s .. %s | %d semanas con dato' % (
            min(per_team), max(per_team), len(per_team)))
        hist_year = HISTORY_YEARS[-1]
        we_hist = event_week_start(hist_year)
        win_hist = [week_offset(we_hist, k) for k in range(-BASE_OFF_MAX, BASE_OFF_MAX + 1)]
        win_now = [week_offset(ws_target, -k) for k in range(BASE_OFF_MIN, BASE_OFF_MAX + 1)]
        keep, dropped = same_store_teams(per_team, [win_hist, win_now])
        lines.append('same-store: %d salas en ambos periodos%s' % (
            len(keep), (' | excluidas: %s' % sorted(dropped)) if dropped else ''))

        for label, idx_col in (('unidades', 0), ('CLP', 1)):
            weekly = collapse(per_team, teams=keep or None, idx=idx_col)
            for year in HISTORY_YEARS:
                we = event_week_start(year)
                idx = uplift_index(weekly, we)
                if not idx:
                    continue
                so_indices[(year, label)] = idx
                report_series(lines, 'Serie sell-out %s alrededor del evento %d (semana %s):' % (label, year, we), weekly, we)
                nb = neighbour_indices(weekly, we)
                lines.append('  indice evento %d (%s): x%.2f  [%.2f - %.2f]'
                             % (year, label, idx['index'], idx['lo'], idx['hi']))
                lines.append('  reparto pre/post: ' + ' | '.join(
                    'sem%+d x%.2f' % (k, v) for k, v in sorted(nb.items())))
        so_weekly_units = collapse(per_team, teams=keep or None, idx=0)
    else:
        lines.append('Sin filas en %s para estos SKU (revisar filtro de proveedor).' % SALE_MODEL)
        so_weekly_units = {}

    # --- estimacion
    lines.append('')
    lines.append('=' * 78)
    lines.append('C) ESTIMACION SEMANA %s' % ws_target)
    lines.append('=' * 78)

    base_now = level_recent(si_weekly, ws_target)
    if base_now:
        lines.append('Nivel base sell-in %d (mediana de %d semanas previas limpias): %s'
                     % (TARGET_YEAR, base_now['n'], fmt_clp(base_now['level'])))
    else:
        lines.append('Nivel base sell-in %d: NO medible (faltan semanas).' % TARGET_YEAR)

    candidates = []
    for year, idx in si_indices.items():
        candidates.append(('sell-in %d' % year, idx['index'], idx['lo'], idx['hi']))
    for (year, label), idx in so_indices.items():
        candidates.append(('sell-out %s %d' % (label, year), idx['index'], idx['lo'], idx['hi']))

    if candidates and base_now:
        lines.append('')
        lines.append('Indices disponibles:')
        for name, i, lo, hi in candidates:
            lines.append('  %-22s x%.2f  [%.2f - %.2f]  -> %s' % (
                name, i, lo, hi, fmt_clp(base_now['level'] * i)))
        point = median([c[1] for c in candidates])
        lo = min(c[2] for c in candidates)
        hi = max(c[3] for c in candidates)
        lines.append('')
        lines.append('ESTIMACION (mediana de indices): compras semana %s = %s'
                     % (ws_target, fmt_clp(base_now['level'] * point)))
        lines.append('  crecimiento vs semana normal: %+.0f%%  (rango %+.0f%% a %+.0f%%)'
                     % ((point - 1) * 100, (lo - 1) * 100, (hi - 1) * 100))
        lines.append('  rango de monto: %s a %s'
                     % (fmt_clp(base_now['level'] * lo), fmt_clp(base_now['level'] * hi)))

        we_ly = event_week_start(TARGET_YEAR - 1)
        if we_ly in si_weekly and si_weekly[we_ly]:
            yoy = (base_now['level'] * point) / si_weekly[we_ly] - 1.0
            lines.append('  YoY vs misma semana %d (%s = %s): %+.0f%%'
                         % (TARGET_YEAR - 1, we_ly, fmt_clp(si_weekly[we_ly]), yoy * 100))
    else:
        lines.append('No se puede estimar: falta indice o nivel base.')

    lines.append('')
    lines.append('ADVERTENCIAS')
    lines.append('  - n de eventos observados = %d. El rango es dispersion del baseline (MAD),' % len(si_indices))
    lines.append('    NO un intervalo de confianza. Reportar como ESTIMACION.')
    lines.append('  - El nivel base %d usa ventana solo-pre: si el negocio viene creciendo,' % TARGET_YEAR)
    lines.append('    el indice historico (ventana simetrica) queda levemente conservador.')
    lines.append('  - Sell-in mezcla volumen y precio (CLP netos). Comparar con el indice de')
    lines.append('    unidades del sell-out para separar los dos efectos.')
    lines.append('  - Parte del peak de COMPRA cae en la semana previa (llenado). Ver el')
    lines.append('    reparto pre/post antes de sumar plata a la semana 38.')

    text = '\n'.join(lines)
    print(text)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    out = OUT_DIR / ('embonor_uplift_%s.txt' % stamp)
    out.write_text(text, encoding='utf-8')
    print('\n[guardado] %s' % out)


if __name__ == '__main__':
    main()
