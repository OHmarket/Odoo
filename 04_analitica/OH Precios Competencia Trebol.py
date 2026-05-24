# ============================================================
# OH Precios Competencia - Supertrebol vs OH Market
# ============================================================
#
# Version activa: v1.0
#
# Objetivo:
#   - Comparar precios de OH Market contra Supertrebol (competidor de
#     conveniencia) para el surtido que ambos venden, y detectar productos
#     que Trebol vende y OH no (candidatos a incorporar).
#
# Decision que alimenta:
#   - Equipo de precios: revisar SKUs donde OH esta por sobre Trebol.
#   - Surtido: evaluar productos nuevos a incorporar, por categoria.
#
# IMPORTANTE - corre FUERA de Odoo:
#   A diferencia de los *_reader.py (plantillas para server actions), este
#   script hace scraping externo + usa el cliente XML-RPC read-only desde
#   fuera (shared/odoo_xmlrpc). NO va dentro de Odoo. Ejecucion manual,
#   cadencia sugerida semanal.
#
# Metodo (como lo hacen las plataformas de price intelligence):
#   1. CAPTURA: sitemap de Trebol -> fichas (SSR, JSON-LD + meta OG) ->
#      EAN (campo sku), precio, marca, disponibilidad. HTTP concurrente.
#   2. CATEGORIA TREBOL: recorre /collections/<cat> y mapea EAN->categoria.
#      (la ficha no expone categoria; viene de la coleccion)
#   3. MATCH: por EAN (product.product.barcode) contra el maestro Odoo.
#      Match exacto: mismo SKU fisico, mismo formato. No es proxy.
#   4. BRECHA: list_price (con IVA, validado vs POS) vs precio Trebol (con
#      IVA, gondola). Comparables directos.
#
# Supuestos / contaminacion a tener presente:
#   - precio Trebol puede ser promo o de item sin stock -> se reporta
#     columna trebol_stock; candidatos se filtran a "in stock".
#   - "sin categoria Trebol" ~ producto descontinuado/sin stock (no listado
#     en colecciones). Se excluye de candidatos.
#   - cobertura tipica de categorizacion: ~90% del surtido activo.
#
# Salida (historico por fecha en OUTPUT_DIR):
#   - Trebol_vs_OHmarket_<fecha>.xlsx  (2 pestanas: comparacion + candidatos)
#   - comparacion_trebol_<fecha>.csv / candidatos_trebol_<fecha>.csv
#   El .xlsx se sube manualmente a Google Drive -> Google Sheets (2 pestanas).
#
# Cache: guarda la captura cruda del dia en CACHE_DIR para regenerar la
#   salida sin re-pegarle al sitio. Borra los cache_*_<fecha>.json para
#   forzar recaptura fresca.
#
# Uso:   python "04_analitica/OH Precios Competencia Trebol.py"
# ============================================================

import os
import re
import csv
import json
import time
import urllib.request
from collections import defaultdict, Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from shared.odoo_xmlrpc import OdooReader

# --- Config ---------------------------------------------------------------
BASE = "https://www.supertrebol.cl"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36")
CAT_FIELD = "x_studio_categoria_l1_id"     # categoria L1 en el maestro OH
WORKERS_FICHAS = 10
WORKERS_COLS = 8
TODAY = date.today().isoformat()

_HERE = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(_HERE, "salida_precios_competencia")
CACHE_CAP = os.path.join(OUTPUT_DIR, f"cache_trebol_{TODAY}.json")
CACHE_CAT = os.path.join(OUTPUT_DIR, f"cache_categorias_{TODAY}.json")

# --- Regex de parseo ------------------------------------------------------
RE_LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.I)
RE_LD = re.compile(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', re.S)
RE_PRICE = re.compile(r'product:price:amount"\s+content="([\d.,]+)"')
RE_BRAND = re.compile(r'product:brand"\s+content="([^"]*)"')
RE_TITLE = re.compile(r'og:title"\s+content="([^"]*)"')
RE_AVAIL = re.compile(r'product:availability"\s+content="([^"]*)"')
RE_IMG_EAN = re.compile(r'/\d+-(\d{13})\.')


def fetch(url, intentos=3):
    for i in range(intentos):
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "identity"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8", "replace")
        except Exception:
            if i < intentos - 1:
                time.sleep(1.0)
    return None


# --- 1. Captura del catalogo ---------------------------------------------
def _parse_ficha(html):
    if not html:
        return None
    ean = None
    m = RE_LD.search(html)
    if m:
        try:
            d = json.loads(m.group(1))
            if isinstance(d, list):
                d = next((x for x in d if x.get("@type") == "Product"), {})
            ean = (d.get("sku") or "").strip() or None
        except Exception:
            pass
    if not ean:
        mi = RE_IMG_EAN.search(html)
        ean = mi.group(1) if mi else None
    if not ean:
        return None
    mp = RE_PRICE.search(html)
    precio = int(re.sub(r"\D", "", mp.group(1))) if mp else None
    if not precio:
        return None
    mt, mb, ma = RE_TITLE.search(html), RE_BRAND.search(html), RE_AVAIL.search(html)
    return {"ean": ean, "nombre": mt.group(1) if mt else "",
            "marca": mb.group(1) if mb else "", "precio": precio,
            "disp": ma.group(1) if ma else ""}


def capturar_catalogo():
    if os.path.exists(CACHE_CAP):
        with open(CACHE_CAP, encoding="utf-8") as fh:
            data = json.load(fh)
        print(f">> [cache] catalogo Trebol: {len(data)} (borra {os.path.basename(CACHE_CAP)} para refrescar)")
        return data
    print(">> Capturando catalogo Trebol...")
    sm = fetch(f"{BASE}/sitemap.xml")
    urls = [u for u in RE_LOC.findall(sm) if "/products/" in u]
    print(f"   fichas: {len(urls)}")
    by_ean, done = {}, 0
    with ThreadPoolExecutor(max_workers=WORKERS_FICHAS) as ex:
        futs = {ex.submit(fetch, u): u for u in urls}
        for fut in as_completed(futs):
            done += 1
            if done % 2000 == 0:
                print(f"   ...{done}/{len(urls)}")
            rec = _parse_ficha(fut.result())
            if rec:
                by_ean.setdefault(rec["ean"], rec)
    with open(CACHE_CAP, "w", encoding="utf-8") as fh:
        json.dump(by_ean, fh, ensure_ascii=False)
    print(f"   capturados con EAN+precio: {len(by_ean)}")
    return by_ean


# --- 2. Categoria Trebol (por coleccion) ----------------------------------
def _recorrer_coleccion(slug):
    name = slug.replace("-", " ").title()
    eans, page, sin_nuevos = set(), 1, 0
    while page <= 80:
        url = f"{BASE}/collections/{slug}" + ("" if page == 1 else f"?page={page}")
        html = fetch(url)
        if not html:
            break
        pg = set(RE_IMG_EAN.findall(html))
        if not pg:
            break
        nuevos = pg - eans
        eans |= pg
        sin_nuevos = sin_nuevos + 1 if not nuevos else 0
        if sin_nuevos >= 2 or 'rel="next"' not in html:
            break
        page += 1
    return name, eans


def mapear_categorias():
    if os.path.exists(CACHE_CAT):
        with open(CACHE_CAT, encoding="utf-8") as fh:
            data = json.load(fh)
        print(f">> [cache] categorias Trebol: {len(data)} EAN")
        return data
    print(">> Mapeando categoria Trebol (colecciones)...")
    sm = fetch(f"{BASE}/sitemap.xml")
    slugs = sorted(set(re.findall(r"/collections/([a-z0-9-]+)", sm)))
    print(f"   colecciones: {len(slugs)}")
    ean_cats = defaultdict(set)
    with ThreadPoolExecutor(max_workers=WORKERS_COLS) as ex:
        futs = {ex.submit(_recorrer_coleccion, s): s for s in slugs}
        for fut in as_completed(futs):
            name, eans = fut.result()
            for e in eans:
                ean_cats[e].add(name)
    out = {e: sorted(cs) for e, cs in ean_cats.items()}
    with open(CACHE_CAT, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False)
    print(f"   EAN con categoria: {len(out)}")
    return out


# --- 3. Maestro Odoo ------------------------------------------------------
def leer_maestro():
    odoo = OdooReader()
    prods = odoo.search_read(
        "product.product",
        domain=[("sale_ok", "=", True), ("active", "=", True), ("barcode", "!=", False)],
        fields=["barcode", "name", "list_price", CAT_FIELD])
    print(f">> Maestro OH: {len(prods)} SKUs vendibles con barcode")
    return prods


# --- 4. Reportes ----------------------------------------------------------
def construir(trebol, ean_cats, prods):
    def cat_treb(ean):
        return " | ".join(ean_cats.get(ean, [])) or "(sin cat Trébol)"

    mis_eans = {p["barcode"] for p in prods}

    comparacion = []
    for p in prods:
        t = trebol.get(p["barcode"])
        if not t or not t["precio"]:
            continue
        mi, tre = p["list_price"], t["precio"]
        comparacion.append({
            "categoria_oh": p[CAT_FIELD][1] if p.get(CAT_FIELD) else "(sin categoría)",
            "categoria_trebol": cat_treb(p["barcode"]), "ean": p["barcode"],
            "producto_oh": p["name"], "mi_precio": round(mi),
            "producto_trebol": t["nombre"], "precio_trebol": tre,
            "trebol_stock": t["disp"], "brecha_$": round(mi - tre),
            "brecha_%": round((mi - tre) / tre * 100, 1) if tre else 0})
    comparacion.sort(key=lambda x: x["brecha_%"], reverse=True)

    candidatos, sin_stock = [], 0
    for e, t in trebol.items():
        if e in mis_eans:
            continue
        if t.get("disp") != "in stock":
            sin_stock += 1
            continue
        candidatos.append({
            "categoria_trebol": cat_treb(e), "ean": e,
            "producto_trebol": t["nombre"], "marca": t["marca"],
            "precio_trebol": t["precio"], "trebol_stock": t["disp"]})
    candidatos.sort(key=lambda x: (x["categoria_trebol"], x["producto_trebol"]))
    return comparacion, candidatos, sin_stock


def escribir_salida(comparacion, candidatos):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    f_cmp = os.path.join(OUTPUT_DIR, f"comparacion_trebol_{TODAY}.csv")
    f_cand = os.path.join(OUTPUT_DIR, f"candidatos_trebol_{TODAY}.csv")
    with open(f_cmp, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(comparacion[0].keys()))
        w.writeheader(); w.writerows(comparacion)
    with open(f_cand, "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(candidatos[0].keys()))
        w.writeheader(); w.writerows(candidatos)

    xlsx = os.path.join(OUTPUT_DIR, f"Trebol_vs_OHmarket_{TODAY}.xlsx")
    try:
        import pandas as pd
        from openpyxl.utils import get_column_letter
        dfc, dfk = pd.DataFrame(comparacion), pd.DataFrame(candidatos)
        with pd.ExcelWriter(xlsx, engine="openpyxl") as xl:
            dfc.to_excel(xl, sheet_name="Comparación de precios", index=False)
            dfk.to_excel(xl, sheet_name="Candidatos a incorporar", index=False)
            for sh, df in (("Comparación de precios", dfc), ("Candidatos a incorporar", dfk)):
                ws = xl.sheets[sh]
                ws.freeze_panes = "A2"
                for i, col in enumerate(df.columns, 1):
                    w = min(max(len(str(col)), df[col].astype(str).str.len().max() if len(df) else 10) + 2, 50)
                    ws.column_dimensions[get_column_letter(i)].width = w
    except ImportError:
        xlsx = None
        print("   (pandas/openpyxl no disponibles: se omite .xlsx, quedan los CSV)")
    return f_cmp, f_cand, xlsx


def main():
    trebol = capturar_catalogo()
    ean_cats = mapear_categorias()
    prods = leer_maestro()
    comparacion, candidatos, sin_stock = construir(trebol, ean_cats, prods)

    cob = len(comparacion) / len(prods) * 100 if prods else 0
    caro = sum(1 for f in comparacion if f["brecha_%"] > 1)
    barato = sum(1 for f in comparacion if f["brecha_%"] < -1)
    print("\n" + "=" * 70)
    print(f"OH Market vs Supertrebol  ({TODAY})")
    print("=" * 70)
    print(f"  Surtido OH (con barcode):  {len(prods)}")
    print(f"  Catalogo Trebol capturado: {len(trebol)}")
    print(f"  Matchean por EAN:          {len(comparacion)}  (cobertura {cob:.0f}%)")
    print(f"    mas caro: {caro} | mas barato: {barato} | igual: {len(comparacion)-caro-barato}")
    print(f"  Candidatos a incorporar:   {len(candidatos)}  (excluidos {sin_stock} sin stock)")

    cnt = Counter()
    for c in candidatos:
        for cat in c["categoria_trebol"].split(" | "):
            cnt[cat] += 1
    print("\n  Top categorias con candidatos:")
    for cat, n in cnt.most_common(12):
        print(f"    {cat[:34]:<35} {n:>4}")

    f_cmp, f_cand, xlsx = escribir_salida(comparacion, candidatos)
    print(f"\n>> Salida en {OUTPUT_DIR}")
    if xlsx:
        print(f"   ENTREGABLE: {os.path.basename(xlsx)}  (subir a Google Drive -> 2 pestañas)")
    print(f"   CSVs: {os.path.basename(f_cmp)} / {os.path.basename(f_cand)}")


if __name__ == "__main__":
    main()
