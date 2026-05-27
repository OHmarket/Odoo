"""
Check B retry: SI historica desde POS para top 6 categorias problema.
Usa read_group sobre date_order de pos.order.line (campo directo en Odoo 17).
Si no existe, fallback a batched search_read.
"""
from __future__ import annotations
import sys
import io
import re
from pathlib import Path
from datetime import date
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

OUT_PATH = Path(__file__).parent / "check_si_pos_output.txt"

pd.set_option("display.float_format", lambda x: f"{x:,.3f}")
pd.set_option("display.max_columns", 60)
pd.set_option("display.width", 220)


def main():
    buf = io.StringIO()
    def p(s=""): buf.write(s + "\n")

    odoo = OdooReader()
    p(f"Conectado: {odoo}\n")

    # Diagnostico de campos de fecha en pos.order.line
    fields = odoo.fields_get('pos.order.line', attributes=['type', 'string'])
    date_fields = {fn: info for fn, info in fields.items() if info.get('type') in ('date', 'datetime')}
    p("Campos de fecha en pos.order.line:")
    for fn, info in sorted(date_fields.items()):
        p(f"  {fn}  ({info['type']})  '{info.get('string','')}'")
    p()

    # Probar date_order directo
    test_field = 'date_order' if 'date_order' in fields else ('create_date' if 'create_date' in fields else None)
    if not test_field:
        p("ERROR no se encontro campo de fecha directo en pos.order.line")
        OUT_PATH.write_text(buf.getvalue(), encoding="utf-8")
        return
    p(f"Usando campo: {test_field}")

    # Resolver IDs de categorias problema
    # Estrategia: buscar por complete_name como contiene
    target_categs = [
        "Helados",
        "Cócteles Ice",
        "Aguas Saborizadas",
        "Agua Mineral",
        "Bebidas Individuales",
        "Isotónicas",
        "Energéticas",
        "Bebidas Regulares",
        "Jugos Colación",
        "Espumantes",
    ]
    p(f"\nBuscando categs por nombre (contiene):")
    categ_ids = []
    for name_part in target_categs:
        recs = odoo.search_read(
            'product.category',
            domain=[('complete_name', 'ilike', name_part)],
            fields=['id', 'complete_name', 'name'],
        )
        # filtrar a los que coinciden razonablemente
        for r in recs:
            cn = r.get('complete_name', '') or ''
            # match exacto del nombre final
            if name_part.lower() in cn.lower():
                # excluir matches genericos (queremos categs de hoja, no padres)
                # heuristica: usar el ultimo segmento
                last = cn.split('/')[-1].strip().lower()
                if name_part.lower() in last:
                    categ_ids.append((cn.strip(), r['id']))
                    break
    # dedupe
    seen = set()
    categ_ids_clean = []
    for cn, cid in categ_ids:
        if cid in seen: continue
        seen.add(cid)
        categ_ids_clean.append((cn, cid))
    p(f"Matched {len(categ_ids_clean)} categs:")
    for cn, cid in categ_ids_clean:
        p(f"  id={cid}  {cn}")

    if not categ_ids_clean:
        OUT_PATH.write_text(buf.getvalue(), encoding="utf-8")
        return

    # 36 meses de historia
    today = date.today()
    history_from = date(today.year - 3, today.month, 1).isoformat()
    p(f"\nHistory from: {history_from}")

    # Para cada categ: read_group con date_order:week, sum(qty)
    p("\n" + "=" * 100)
    p("SI historica calculada desde pos.order.line")
    p("=" * 100)

    si_results = []
    for cn, cid in categ_ids_clean:
        domain = [
            ('product_id.product_tmpl_id.categ_id', '=', cid),
            ('order_id.state', 'in', ['paid', 'done', 'invoiced']),
            (test_field, '>=', history_from),
        ]
        try:
            grp = odoo.execute(
                'pos.order.line', 'read_group',
                domain, ['qty:sum'], [f'{test_field}:week'],
                lazy=False,
            )
        except Exception as e:
            p(f"  ERROR query categ {cn[:50]}: {str(e)[:200]}")
            continue

        # Cada grupo: {f'{test_field}:week': 'W22 2024', qty: 1234, ...}
        weekly = {}
        n_pts = 0
        for g in grp:
            wkey = g.get(f'{test_field}:week')
            qty = float(g.get('qty', 0.0) or 0.0)
            if not wkey or qty <= 0: continue
            m = re.search(r'(\d+).*?(\d{4})', str(wkey))
            if not m: continue
            iso_w = int(m.group(1))
            if not (1 <= iso_w <= 52): continue
            weekly.setdefault(iso_w, []).append(qty)
            n_pts += 1

        if not weekly:
            p(f"  {cn[:50]}: sin data")
            continue
        avg_w = {w: sum(v)/len(v) for w, v in weekly.items()}
        global_avg = sum(avg_w.values()) / len(avg_w)
        if global_avg <= 0:
            continue
        si = {w: avg_w[w] / global_avg for w in avg_w}

        si_results.append({
            "categ": cn[:55],
            "n_obs": n_pts,
            "SI_7": round(si.get(7, float('nan')), 3),
            "SI_8": round(si.get(8, float('nan')), 3),
            "SI_9": round(si.get(9, float('nan')), 3),
            "SI_10": round(si.get(10, float('nan')), 3),
            "SI_11": round(si.get(11, float('nan')), 3),
            "SI_12": round(si.get(12, float('nan')), 3),
            "SI_13": round(si.get(13, float('nan')), 3),
            "ratio_12_8": round(si.get(12, 1.0) / max(si.get(8, 1.0), 0.001), 3),
            "ratio_avg_mar_avg_feb": round(
                (si.get(11, 1.0) + si.get(12, 1.0) + si.get(13, 1.0)) /
                max(si.get(7, 1.0) + si.get(8, 1.0) + si.get(9, 1.0), 0.001),
                3,
            ),
        })

    p("")
    if si_results:
        df_si = pd.DataFrame(si_results)
        p("Tabla SI historica (categ-level, 36 meses POS):")
        p(df_si.to_string(index=False))
        p("")
        # Promedio ponderado por n_obs
        df_si['ratio_w'] = df_si['ratio_12_8'] * df_si['n_obs']
        w_avg_ratio = df_si['ratio_w'].sum() / df_si['n_obs'].sum() if df_si['n_obs'].sum() > 0 else float('nan')
        p(f"ratio_12_8 promedio simple:        {df_si['ratio_12_8'].mean():.3f}")
        p(f"ratio_12_8 mediana:                {df_si['ratio_12_8'].median():.3f}")
        p(f"ratio_12_8 ponderado por n_obs:    {w_avg_ratio:.3f}")
        p(f"ratio mar(11-13)/feb(7-9) promedio: {df_si['ratio_avg_mar_avg_feb'].mean():.3f}")
        p("")
        p("Comparacion:")
        p(f"  Motor implicito (fc_mar/fc_feb agregado): 0.480")
        p(f"  Reality (real_mar/real_feb agregado):     0.413")
        p(f"  Historica SI(12)/SI(8) categ-level:        {df_si['ratio_12_8'].mean():.3f}")

    OUT_PATH.write_text(buf.getvalue(), encoding="utf-8")
    print(f"Output saved to: {OUT_PATH}")


if __name__ == "__main__":
    main()
