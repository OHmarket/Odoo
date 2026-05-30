"""Busca la ultima notificacion de 'POS Semana SKU' (el subject que usa
el script OH Analisis Ventas SKU para reportar resultado)."""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader


def main():
    odoo = OdooReader()

    msgs = odoo.search_read(
        'mail.message',
        domain=[('subject', 'ilike', 'POS Semana SKU')],
        fields=['id', 'date', 'subject', 'body', 'message_type'],
        order='date desc',
        limit=10,
    )
    print(f"Notificaciones encontradas: {len(msgs)}")
    for m in msgs:
        body = (m.get('body') or '').replace('<p>', '').replace('</p>', '')[:300]
        print(f"\n  {m['date']} | {m.get('subject', '')[:50]}")
        print(f"    body: {body}")


if __name__ == "__main__":
    main()
