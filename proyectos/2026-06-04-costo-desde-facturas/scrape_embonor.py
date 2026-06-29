"""scrape_embonor.py — login + captura de API del portal miembonor.cl con Playwright.
Lee EMBONOR_USER/PASS del .env (nunca los imprime). Loguea, navega al TARGET,
captura TODAS las respuestas JSON (xhr/fetch) a archivos para identificar la de
precios/recargo. Deja screenshots y HTML para diagnostico.

Uso: python proyectos/2026-06-04-costo-desde-facturas/scrape_embonor.py [URL]
"""
import sys
import os
import json
sys.path.insert(0, '.')
from shared.odoo_xmlrpc import _load_env
from playwright.sync_api import sync_playwright

env = _load_env()
USER = env.get('EMBONOR_USER')
PWD = env.get('EMBONOR_PASS')
TARGET = sys.argv[1] if len(sys.argv) > 1 else 'https://www.miembonor.cl/app/907822'
OUT = 'proyectos/2026-06-04-costo-desde-facturas/embonor_scrape'
os.makedirs(OUT, exist_ok=True)

if not USER or not PWD:
    print('FALTAN credenciales EMBONOR_USER/EMBONOR_PASS en .env')
    sys.exit(1)

captured = []   # (url, status, idx)


def main():
    with sync_playwright() as p:
        br = p.chromium.launch(headless=True)
        ctx = br.new_context(user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"))
        page = ctx.new_page()

        def on_response(resp):
            try:
                ct = (resp.headers or {}).get('content-type', '')
                if 'application/json' in ct and resp.request.resource_type in ('xhr', 'fetch'):
                    body = resp.text()
                    idx = len(captured)
                    with open(os.path.join(OUT, 'resp_%02d.json' % idx), 'w', encoding='utf-8') as fh:
                        fh.write(body[:500000])
                    captured.append((resp.url, resp.status, idx))
            except Exception:
                pass
        page.on('response', on_response)

        print('>> abriendo TARGET (sin sesion -> deberia ir a login)...')
        page.goto(TARGET, wait_until='networkidle', timeout=60000)
        page.screenshot(path=os.path.join(OUT, '01_landing.png'), full_page=True)
        with open(os.path.join(OUT, '01_landing.html'), 'w', encoding='utf-8') as fh:
            fh.write(page.content())

        inputs = page.eval_on_selector_all(
            'input', "els => els.map(e=>({name:e.name,type:e.type,id:e.id,ph:e.placeholder}))")
        print('INPUTS en landing:', json.dumps(inputs, ensure_ascii=False))

        pw = page.query_selector('input[type=password]')
        if pw:
            print('>> form de login detectado, ingresando credenciales...')
            uf = (page.query_selector('input[type=email]') or
                  page.query_selector('input[type=text]') or
                  page.query_selector('input:not([type=password]):not([type=hidden])'))
            if uf:
                uf.fill(USER)
            pw.fill(PWD)
            btn = (page.query_selector('button[type=submit]') or
                   page.query_selector('button'))
            if btn:
                btn.click()
            else:
                pw.press('Enter')
            try:
                page.wait_for_load_state('networkidle', timeout=60000)
            except Exception:
                pass
            page.screenshot(path=os.path.join(OUT, '02_postlogin.png'), full_page=True)
            print('>> post-login, navegando al TARGET...')
            page.goto(TARGET, wait_until='networkidle', timeout=60000)
        else:
            print('>> NO se detecto password field (¿ya logueado o login distinto?)')

        page.screenshot(path=os.path.join(OUT, '03_data.png'), full_page=True)
        with open(os.path.join(OUT, '03_data.html'), 'w', encoding='utf-8') as fh:
            fh.write(page.content())
        print('URL final:', page.url)
        br.close()

    print('\n>> JSON (xhr/fetch) capturados: %s' % len(captured))
    for url, status, idx in captured:
        sz = os.path.getsize(os.path.join(OUT, 'resp_%02d.json' % idx))
        print('  [%02d] %s  %s bytes  %s' % (idx, status, sz, url[:90]))
    print('\nArtefactos en %s (screenshots 01/02/03, resp_*.json)' % OUT)


if __name__ == '__main__':
    main()
