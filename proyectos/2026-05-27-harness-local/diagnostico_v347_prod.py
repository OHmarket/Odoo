"""
Diagnostico v3.47 productivo - via XMLRPC read-only.

CUIDADO con el server: solo queries con limit, fields explicitos, sin search masivos.
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from shared.odoo_xmlrpc import OdooReader

# Para Windows console con tildes
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')


def main():
    print("Conectando a Odoo...")
    odoo = OdooReader()
    print(f"  uid={odoo.uid}")

    # ============================================================
    # 1. x_categ_calib_factor - cuantos activos
    # ============================================================
    print("\n[1] x_categ_calib_factor - registros activos")
    print("-" * 80)
    n_active = odoo.search_count('x_categ_calib_factor',
                                  domain=[('x_studio_active', '=', True)])
    n_total = odoo.search_count('x_categ_calib_factor', domain=[])
    print(f"  Total: {n_total} | Activos: {n_active}")

    # Top 10 factores
    samples = odoo.search_read(
        'x_categ_calib_factor',
        domain=[('x_studio_active', '=', True)],
        fields=['x_studio_categ_id', 'x_studio_abc_letter', 'x_studio_factor_corr',
                'x_studio_raw_factor', 'x_studio_n_real_units',
                'x_studio_regimenes_aplicables', 'x_studio_target_week'],
        limit=10,
        order='x_studio_n_real_units desc',
    )
    print(f"\n  Top 10 factores por unidades reales:")
    for r in samples:
        cat = r.get('x_studio_categ_id')
        cat_name = cat[1] if isinstance(cat, list) else str(cat)
        print(f"    {cat_name[:50]:<50s} abc={r['x_studio_abc_letter']} "
              f"f={r['x_studio_factor_corr']:.3f} n={r['x_studio_n_real_units']:.0f} "
              f"regs={r['x_studio_regimenes_aplicables']}")

    # ============================================================
    # 2. x_hm_si_forecast - validar campos nuevos
    # ============================================================
    print("\n[2] x_hm_si_forecast - validacion campos v3.47")
    print("-" * 80)
    fields_meta = odoo.fields_get('x_hm_si_forecast')
    for fname in ['x_studio_categ_calib_factor', 'x_studio_categ_calib_meta',
                  'x_studio_mu_week_pre_calib', 'x_studio_mu_week_pre_bias',
                  'x_studio_mu_week_pre_corr']:
        if fname in fields_meta:
            ftype = fields_meta[fname].get('type', '?')
            print(f"  {fname:<40s} type={ftype}  [OK]")
        else:
            print(f"  {fname:<40s} [MISSING]")

    # ============================================================
    # 3. x_hm_si_forecast - conteo total y con factor aplicado
    # ============================================================
    print("\n[3] x_hm_si_forecast - cobertura factor")
    print("-" * 80)
    n_fwd_total = odoo.search_count('x_hm_si_forecast', domain=[])
    print(f"  Total forecasts: {n_fwd_total}")

    if 'x_studio_categ_calib_factor' in fields_meta:
        n_with_factor = odoo.search_count(
            'x_hm_si_forecast',
            domain=[('x_studio_categ_calib_factor', '!=', 1.0),
                    ('x_studio_categ_calib_factor', '!=', 0.0)])
        n_factor_eq_1 = odoo.search_count(
            'x_hm_si_forecast',
            domain=[('x_studio_categ_calib_factor', '=', 1.0)])
        n_factor_eq_0 = odoo.search_count(
            'x_hm_si_forecast',
            domain=[('x_studio_categ_calib_factor', '=', 0.0)])
        print(f"  Con factor != 1.0 y != 0.0: {n_with_factor}  ({n_with_factor/n_fwd_total*100:.1f}%)")
        print(f"  Con factor = 1.0:           {n_factor_eq_1}  ({n_factor_eq_1/n_fwd_total*100:.1f}%)")
        print(f"  Con factor = 0.0 (no pop):  {n_factor_eq_0}  ({n_factor_eq_0/n_fwd_total*100:.1f}%)")
    else:
        print("  Campo x_studio_categ_calib_factor NO existe en x_hm_si_forecast")

    # ============================================================
    # 4. Muestra de filas con factor aplicado
    # ============================================================
    print("\n[4] Muestra de filas con factor aplicado")
    print("-" * 80)
    if 'x_studio_categ_calib_factor' in fields_meta:
        rows = odoo.search_read(
            'x_hm_si_forecast',
            domain=[('x_studio_categ_calib_factor', '!=', 1.0),
                    ('x_studio_categ_calib_factor', '!=', 0.0)],
            fields=['x_studio_product_id', 'x_studio_team_id', 'x_studio_categ_id',
                    'x_studio_mu_week', 'x_studio_mu_week_pre_calib',
                    'x_studio_categ_calib_factor', 'x_studio_categ_calib_meta',
                    'x_studio_regimen'],
            limit=15,
            order='x_studio_mu_week desc',
        )
        print(f"  {'team':>6s} {'sku':>6s} {'categ':<40s} {'reg':<7s} {'mu_pre':>8s} {'fac':>5s} {'mu':>8s}  meta")
        for r in rows:
            team = r.get('x_studio_team_id')
            team_str = str(team[0]) if isinstance(team, list) else str(team)
            sku = r.get('x_studio_product_id')
            sku_id = sku[0] if isinstance(sku, list) else sku
            cat = r.get('x_studio_categ_id')
            cat_name = (cat[1][:38] if isinstance(cat, list) else str(cat)[:38])
            print(f"  {team_str:>6s} {sku_id:>6} {cat_name:<40s} "
                  f"{r.get('x_studio_regimen', '')[:7]:<7s} "
                  f"{r['x_studio_mu_week_pre_calib']:>8.2f} "
                  f"{r['x_studio_categ_calib_factor']:>5.2f} "
                  f"{r['x_studio_mu_week']:>8.2f}  "
                  f"{r.get('x_studio_categ_calib_meta', '')[:60]}")

    # ============================================================
    # 5. Distribucion factor por regimen (read_group)
    # ============================================================
    print("\n[5] Cobertura factor por regimen (read_group)")
    print("-" * 80)
    if 'x_studio_categ_calib_factor' in fields_meta:
        groups = odoo.execute(
            'x_hm_si_forecast', 'read_group',
            [], ['x_studio_regimen'], ['x_studio_regimen'],
            lazy=False,
        )
        groups_dict = {g['x_studio_regimen']: g['__count'] for g in groups}

        # Por regimen con factor != 1.0
        groups_with = odoo.execute(
            'x_hm_si_forecast', 'read_group',
            [('x_studio_categ_calib_factor', '!=', 1.0),
             ('x_studio_categ_calib_factor', '!=', 0.0)],
            ['x_studio_regimen'], ['x_studio_regimen'],
            lazy=False,
        )
        with_dict = {g['x_studio_regimen']: g['__count'] for g in groups_with}

        print(f"  {'regimen':<10s} {'total':>8s} {'con_factor':>12s} {'pct':>7s}")
        for reg in sorted(groups_dict.keys(), key=lambda x: str(x)):
            total = groups_dict.get(reg, 0)
            with_f = with_dict.get(reg, 0)
            pct = with_f / total * 100 if total else 0
            reg_str = str(reg) if reg else 'null'
            print(f"  {reg_str:<10s} {total:>8} {with_f:>12} {pct:>6.1f}%")

    # ============================================================
    # 6. mu_week_pre_calib vs mu_week en muestra (para validar)
    # ============================================================
    print("\n[6] Sanity check: mu_week_pre_calib * factor == mu_week ?")
    print("-" * 80)
    if 'x_studio_categ_calib_factor' in fields_meta:
        rows = odoo.search_read(
            'x_hm_si_forecast',
            domain=[('x_studio_categ_calib_factor', '!=', 1.0),
                    ('x_studio_categ_calib_factor', '!=', 0.0),
                    ('x_studio_mu_week_pre_calib', '>', 0)],
            fields=['x_studio_mu_week', 'x_studio_mu_week_pre_calib',
                    'x_studio_categ_calib_factor'],
            limit=5,
        )
        for r in rows:
            pre = r['x_studio_mu_week_pre_calib']
            fac = r['x_studio_categ_calib_factor']
            mu = r['x_studio_mu_week']
            expected = pre * fac  # solo capa calib - despues hay trend_factor
            print(f"  pre_calib={pre:>7.3f} x fac={fac:>5.3f} = {expected:>7.3f}  vs mu_week={mu:>7.3f}  "
                  f"(diff={mu-expected:+.3f}, prob trend_factor)")

    print("\n[FIN] Diagnostico completado.")


if __name__ == "__main__":
    main()
