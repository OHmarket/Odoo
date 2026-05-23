"""
odoo_xmlrpc — Cliente XML-RPC read-only contra Odoo de OH Market.

Distinto a los demas *_reader.py de esta carpeta: estos son plantillas que
se pegan dentro de Odoo (usan env inyectado). Este archivo corre DESDE FUERA
de Odoo: tu PC u otro host abre una conexion HTTP al servidor.

Uso tipico (desde la raiz del repo):

    from shared.odoo_xmlrpc import OdooReader
    odoo = OdooReader()
    rows = odoo.search_read(
        'x_calculo_abc_xyz',
        domain=[('x_studio_abc', '=', 'A')],
        fields=['x_studio_rank_abcxyz', 'x_studio_abcxyz', 'x_studio_categ_id'],
        limit=10,
    )
    df = odoo.to_dataframe(rows)

Credenciales: lee .env en la raiz del repo. El .env esta en .gitignore.
Restriccion: solo metodos de lectura. Cualquier intento de create/write/unlink
lanza PermissionError sin contactar al servidor.
"""

from __future__ import annotations

import os
import xmlrpc.client
from pathlib import Path

# Whitelist de metodos. Mas vale ampliar manualmente que abrir todo por error.
ALLOWED_METHODS = frozenset({
    'search',
    'search_read',
    'search_count',
    'read',
    'fields_get',
    'read_group',
    'name_search',
    'name_get',
    'default_get',
})


def _load_env(env_path: Path | None = None) -> dict[str, str]:
    """Lee .env sin dependencias externas. Linea formato KEY=value."""
    if env_path is None:
        env_path = Path(__file__).resolve().parents[1] / '.env'
    if not env_path.exists():
        raise FileNotFoundError(
            f'No existe {env_path}. Crear con ODOO_URL, ODOO_DB, ODOO_USER, ODOO_API_KEY.'
        )
    out: dict[str, str] = {}
    for raw in env_path.read_text(encoding='utf-8').splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, val = line.split('=', 1)
        out[key.strip()] = val.strip().strip('"').strip("'")
    return out


class OdooReader:
    """Cliente XML-RPC read-only. Reusa la misma conexion para todas las queries."""

    def __init__(self, env_path: Path | None = None):
        creds = _load_env(env_path)
        try:
            self.url = creds['ODOO_URL']
            self.db = creds['ODOO_DB']
            self.user = creds['ODOO_USER']
            self._key = creds['ODOO_API_KEY']
        except KeyError as e:
            raise KeyError(f'Falta variable {e} en .env') from None

        common = xmlrpc.client.ServerProxy(f'{self.url}/xmlrpc/2/common')
        self.uid = common.authenticate(self.db, self.user, self._key, {})
        if not self.uid:
            raise PermissionError(
                'Autenticacion fallida. Revisa ODOO_USER y ODOO_API_KEY en .env. '
                'Si la API key fue revocada, crea una nueva en Odoo.'
            )
        self._models = xmlrpc.client.ServerProxy(f'{self.url}/xmlrpc/2/object')

    def execute(self, model: str, method: str, *args, **kwargs):
        if method not in ALLOWED_METHODS:
            raise PermissionError(
                f'Metodo {method!r} bloqueado. Cliente es read-only. '
                f'Permitidos: {sorted(ALLOWED_METHODS)}'
            )
        return self._models.execute_kw(
            self.db, self.uid, self._key,
            model, method,
            list(args), kwargs or {},
        )

    def search_read(
        self,
        model: str,
        domain: list | None = None,
        fields: list[str] | None = None,
        limit: int | None = None,
        offset: int = 0,
        order: str | None = None,
    ) -> list[dict]:
        kw: dict = {}
        if fields is not None:
            kw['fields'] = fields
        if limit is not None:
            kw['limit'] = limit
        if offset:
            kw['offset'] = offset
        if order is not None:
            kw['order'] = order
        return self.execute(model, 'search_read', domain or [], **kw)

    def search_count(self, model: str, domain: list | None = None) -> int:
        return self.execute(model, 'search_count', domain or [])

    def fields_get(self, model: str, attributes: list[str] | None = None) -> dict:
        kw = {'attributes': attributes} if attributes else {}
        return self.execute(model, 'fields_get', **kw)

    @staticmethod
    def to_dataframe(records: list[dict]):
        import pandas as pd
        return pd.DataFrame(records)

    def __repr__(self) -> str:
        return f'OdooReader(url={self.url!r}, db={self.db!r}, uid={self.uid})'
