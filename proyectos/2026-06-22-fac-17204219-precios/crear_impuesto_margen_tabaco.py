# Server Action (ir.actions.server, python_code / safe_eval)
# OH — Crea el impuesto "IVA Margen Comercializacion Tabaco" (cigarrillos, codigo SII 14).
#
# Contexto: el DTE de cigarrillos trae un <ImptoReten> codigo 14 = "IVA de margen de
# comercializacion" (Res. Ex. SII 1086/1978, cambio de sujeto). Odoo no lo aplica solo
# porque el codigo 14 colisiona con el IVA normal. Este tax se cuelga a los SKU de
# cigarrillo para que Odoo CALCULE un valor seed (~1,22% del costo); el monto exacto
# se ajusta despues contra el <MontoImp> del XML (manual o por cron).
#
# Config: espeja tax 17 "IVA Compra 19% No Recup." (mismo no-recuperable / cuenta /
# grupo / tags F29), solo cambia nombre y tasa. La tasa 1,22% es PROXY (la base legal
# real es ~5% del PVP; el valor exacto vive en el XML).
#
# PENDIENTE CONTADOR: confirmar cuenta (82 "Facturas por Recibir") y tags F29 del
# IVA-margen. Si difieren del IVA No Recup, ajustar account_id/tag_ids abajo.

NOMBRE = 'IVA Margen Comercializacion Tabaco'
TASA = 1.22                # PROXY sobre el costo (seed; se ajusta al XML)
CUENTA_IMP = 82            # 210230 Facturas por Recibir (espejo tax 17)
GRUPO = 7                  # tax_group "IVA 19%"
SII_CODE = 14             # IVA de margen de comercializacion

# tags F29 espejados de tax 17 (base/tax, invoice/refund)
TAG_BASE_INV, TAG_TAX_INV = 44, 62
TAG_BASE_REF, TAG_TAX_REF = 43, 61

existe = env['account.tax'].search([('name', '=', NOMBRE), ('company_id', '=', 1)], limit=1)
if existe:
    raise UserError('Ya existe el impuesto (id %s). Aborto para no duplicar.' % existe.id)

tax = env['account.tax'].create({
    'name': NOMBRE,
    'amount': TASA,
    'amount_type': 'percent',
    'type_tax_use': 'purchase',
    'price_include': False,
    'l10n_cl_sii_code': SII_CODE,
    'tax_group_id': GRUPO,
    'country_id': 46,          # Chile
    'company_id': 1,
    'tax_exigibility': 'on_invoice',
    'include_base_amount': False,
    'is_base_affected': False,
    'description': 'IVA margen comercializacion cigarrillos (cod 14). Tasa PROXY; ajustar al MontoImp del DTE.',
    'invoice_repartition_line_ids': [
        Command.create({'document_type': 'invoice', 'repartition_type': 'base',
                        'factor_percent': 100.0, 'tag_ids': [Command.set([TAG_BASE_INV])]}),
        Command.create({'document_type': 'invoice', 'repartition_type': 'tax',
                        'factor_percent': 100.0, 'account_id': CUENTA_IMP,
                        'tag_ids': [Command.set([TAG_TAX_INV])], 'use_in_tax_closing': True}),
    ],
    'refund_repartition_line_ids': [
        Command.create({'document_type': 'refund', 'repartition_type': 'base',
                        'factor_percent': 100.0, 'tag_ids': [Command.set([TAG_BASE_REF])]}),
        Command.create({'document_type': 'refund', 'repartition_type': 'tax',
                        'factor_percent': 100.0, 'account_id': CUENTA_IMP,
                        'tag_ids': [Command.set([TAG_TAX_REF])], 'use_in_tax_closing': True}),
    ],
})

msg = 'Creado impuesto id %s: %s (%.2f%%, cod SII %s, cuenta %s)' % (
    tax.id, NOMBRE, TASA, SII_CODE, CUENTA_IMP)
log(msg)
action = {
    'type': 'ir.actions.client',
    'tag': 'display_notification',
    'params': {'title': 'Impuesto creado', 'message': msg, 'type': 'success', 'sticky': True},
}
