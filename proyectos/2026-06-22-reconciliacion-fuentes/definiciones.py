# -*- coding: utf-8 -*-
"""
Capa de definiciones canónicas para informes OH Market.
Única fuente de verdad de: qué es venta, stock, sala, CD, ventanas y exclusiones.
Los informes deben importar de aquí en vez de re-derivar filtros a mano.

Uso:
    from definiciones import Fuentes, CD_TEAMS, ONLINE_TEAMS
    f = Fuentes()              # abre conexión read-only
    stock = f.stock_salas()    # stock parado real en salas (sin kits/combos/CD)
    venta = f.venta_semanal()  # venta viva desde x_pos_week_sku_sale
"""
from __future__ import annotations
import datetime
import pandas as pd
from shared.odoo_xmlrpc import OdooReader

# ---- nodos del echelon que NO son salas físicas (validado 2026-06-22) ----
CD_TEAMS = {26}        # Bodega Central (Centro de Distribución)
ONLINE_TEAMS = {2}     # Website (canal e-commerce)
NO_SALA_TEAMS = CD_TEAMS | ONLINE_TEAMS

# ---- ventanas estándar (semanas) ----
W_CORRIENTE = 13       # demanda corriente / u_mes
W_SEMESTRE = 26
W_ANIO = 52

CACHE_PARQUET = 'proyectos/2026-05-27-harness-local/cache/pos_weekly.parquet'
CACHE_MAX_STALE_DAYS = 8

MODELO_VENTA = 'x_pos_week_sku_sale'
MODELO_STOCK = 'x_analisis_de_stock'


class Fuentes:
    def __init__(self):
        self.o = OdooReader()
        self._kits = None
        self._tmpl_attr = None

    # ---------- catálogo / atributos ----------
    def kit_templates(self) -> set[int]:
        """Templates que son kits phantom (su stock es fantasma: vive en componentes)."""
        if self._kits is None:
            bom = self.o.search_read('mrp.bom', [['type', '=', 'phantom']], ['product_tmpl_id'])
            self._kits = {b['product_tmpl_id'][0] for b in bom if b.get('product_tmpl_id')}
        return self._kits

    def tmpl_attr(self) -> pd.DataFrame:
        """Atributos por template: type, purchase_ok, sale_ok, active, list_price."""
        if self._tmpl_attr is None:
            rows = self.o.search_read('product.template', [],
                   ['id', 'name', 'type', 'purchase_ok', 'sale_ok', 'active', 'list_price', 'categ_id'])
            df = pd.DataFrame(rows)
            df['categ'] = df['categ_id'].apply(lambda x: x[1] if x else '')
            df['es_kit'] = df['id'].isin(self.kit_templates())
            df['es_combo'] = df['type'] == 'combo'
            self._tmpl_attr = df.set_index('id')
        return self._tmpl_attr

    # ---------- stock ----------
    def stock_raw(self) -> pd.DataFrame:
        """x_analisis_de_stock crudo + flags (kit, combo, no_sala). Sin filtrar."""
        rows = self.o.search_read(MODELO_STOCK, [],
               ['x_studio_product_id', 'x_studio_team_id',
                'x_studio_stock_real', 'x_studio_stock_value_cash_physical'])
        df = pd.DataFrame(rows)
        df['tmpl'] = df['x_studio_product_id'].apply(lambda x: x[0] if x else None)
        df['team_id'] = df['x_studio_team_id'].apply(lambda x: x[0] if x else None)
        df = df.dropna(subset=['tmpl', 'team_id']).rename(columns={
            'x_studio_stock_real': 'stock_u', 'x_studio_stock_value_cash_physical': 'stock_val'})
        df['tmpl'] = df['tmpl'].astype(int); df['team_id'] = df['team_id'].astype(int)
        attr = self.tmpl_attr()
        df['es_kit'] = df['tmpl'].map(attr['es_kit']).fillna(False)
        df['es_combo'] = df['tmpl'].map(attr['es_combo']).fillna(False)
        df['es_cd'] = df['team_id'].isin(CD_TEAMS)
        df['es_no_sala'] = df['team_id'].isin(NO_SALA_TEAMS)
        return df[['team_id', 'tmpl', 'stock_u', 'stock_val', 'es_kit', 'es_combo', 'es_cd', 'es_no_sala']]

    def stock_salas(self) -> pd.DataFrame:
        """STOCK PARADO REAL en salas: excluye kits phantom, combos y nodos no-sala (CD/Web)."""
        df = self.stock_raw()
        return df[~df.es_kit & ~df.es_combo & ~df.es_no_sala].copy()

    def stock_cd(self) -> pd.DataFrame:
        """Pipeline del CD (no es stock parado de sala; se reporta aparte)."""
        df = self.stock_raw()
        return df[df.es_cd & ~df.es_kit & ~df.es_combo].copy()

    # ---------- venta ----------
    def venta_semanal(self, weeks_back: int | None = None, prefer_cache=True) -> pd.DataFrame:
        """Venta semanal por SKU×sala. Usa cache si está fresco y completo; sino, vivo.
        Cols: team_id, product_id, tmpl, week_start, qty_sold."""
        if prefer_cache and self._cache_ok():
            df = pd.read_parquet(CACHE_PARQUET)
            df['week_start'] = pd.to_datetime(df['week_start'])
        else:
            df = self._venta_viva(weeks_back)
        if weeks_back:
            cut = df['week_start'].max() - pd.Timedelta(weeks=weeks_back)
            df = df[df['week_start'] > cut]
        # mapear variante -> template
        df['tmpl'] = df['product_id'].map(self._variant_to_tmpl(df['product_id'].unique()))
        return df

    def _cache_ok(self) -> bool:
        import os
        if not os.path.exists(CACHE_PARQUET):
            return False
        df = pd.read_parquet(CACHE_PARQUET, columns=['week_start'])
        maxw = pd.to_datetime(df['week_start']).max().date()
        stale = (datetime.date.today() - maxw).days
        return stale <= CACHE_MAX_STALE_DAYS

    def _venta_viva(self, weeks_back: int | None) -> pd.DataFrame:
        dom = []
        if weeks_back:
            start = (datetime.date.today() - datetime.timedelta(weeks=weeks_back)).isoformat()
            dom = [['x_studio_week_start', '>=', start]]
        rows = self.o.search_read(MODELO_VENTA, dom,
               ['x_studio_product_id', 'x_studio_team_id', 'x_studio_week_start', 'x_studio_qty_sold'])
        df = pd.DataFrame(rows)
        df['product_id'] = df['x_studio_product_id'].apply(lambda x: x[0] if x else None)
        df['team_id'] = df['x_studio_team_id'].apply(lambda x: x[0] if x else None)
        df = df.dropna(subset=['product_id', 'team_id']).rename(
            columns={'x_studio_week_start': 'week_start', 'x_studio_qty_sold': 'qty_sold'})
        df['week_start'] = pd.to_datetime(df['week_start'])
        return df[['team_id', 'product_id', 'week_start', 'qty_sold']]

    def _variant_to_tmpl(self, pids) -> dict:
        ids = [int(x) for x in pids if pd.notna(x)]
        rows = self.o.search_read('product.product', [['id', 'in', ids]], ['id', 'product_tmpl_id'])
        return {r['id']: (r['product_tmpl_id'][0] if r.get('product_tmpl_id') else None) for r in rows}
