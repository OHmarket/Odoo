"""error_19.py — READ-ONLY. Distribucion del recargo%neto por linea (mono-codigo
Embonor) para acotar el error de asumir ~19% uniforme. Solo montos (rapido)."""
import sys
sys.path.insert(0, '.')
from shared.odoo_xmlrpc import OdooReader

EMBONOR_VAT = '93281000'
CHARGE_WORDS = ('recargo', 'flete', 'despacho', 'transporte', 'acarreo')


def f(v):
    try:
        return float(v or 0.0)
    except Exception:
        return 0.0


def is_charge(label):
    lab = (label or '').strip().lower()
    return any(w in lab for w in CHARGE_WORDS) if lab else False


def pct(sorted_xs, q):
    if not sorted_xs:
        return 0.0
    i = int(q * (len(sorted_xs) - 1))
    return sorted_xs[i]


def main():
    o = OdooReader()
    pid = o.search_read('res.partner', [('vat', 'like', EMBONOR_VAT)], fields=['id'], limit=1)[0]['id']
    moves = o.search_read('account.move',
                          [('move_type', '=', 'in_invoice'), ('state', '=', 'posted'),
                           ('partner_id', '=', pid),
                           ('invoice_date', '>=', '2025-09-01'), ('invoice_date', '<=', '2026-06-30')],
                          fields=['id'], order='id', limit=1500)
    pcts, netos = [], []
    for m in moves:
        lines = o.search_read('account.move.line', [('move_id', '=', m['id']), ('display_type', '=', 'product')],
                              fields=['name', 'product_id', 'quantity', 'price_subtotal'])
        prods, rec = [], 0.0
        for l in lines:
            if f(l['quantity']) <= 0:
                continue
            if is_charge(l['name']) and not l['product_id']:
                rec += f(l['price_subtotal'])
                continue
            if l['product_id']:
                prods.append(f(l['price_subtotal']))
        if rec > 0 and len(prods) == 1 and prods[0] > 0:
            pcts.append(rec / prods[0])
            netos.append(prods[0])

    n = len(pcts)
    pares = sorted(zip(pcts, netos))
    s = [p for p, _ in pares]
    media = sum(pcts) / n
    media_pond = sum(p * w for p, w in zip(pcts, netos)) / sum(netos)
    print("lineas mono-codigo: %s\n" % n)
    print("recargo %% del neto (por producto):")
    print("  media simple   : %.1f%%" % (100 * media))
    print("  media PONDERADA : %.1f%%  <- la que importa para el costo total" % (100 * media_pond))
    print("  mediana        : %.1f%%" % (100 * pct(s, 0.5)))
    print("  p10 / p90      : %.1f%% / %.1f%%" % (100 * pct(s, 0.10), 100 * pct(s, 0.90)))
    print("  p25 / p75      : %.1f%% / %.1f%%" % (100 * pct(s, 0.25), 100 * pct(s, 0.75)))
    print("  min / max      : %.1f%% / %.1f%%" % (100 * s[0], 100 * s[-1]))
    for band in (0.02, 0.05):
        dentro = 100.0 * sum(1 for p in pcts if abs(p - media_pond) <= band) / n
        print("  dentro de %.0fpp de la media pond: %.0f%%" % (100 * band, dentro))


if __name__ == '__main__':
    main()
