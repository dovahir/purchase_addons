# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class PurchaseRequestSendEmailWizard(models.TransientModel):
    _name = 'purchase.request.send.email.wizard'
    _description = 'Enviar cotización por correo'

    partner_id = fields.Many2one(
        comodel_name='res.partner',
        string='Proveedor',
        # required=True,
        # domain="[('supplier_rank', '>', 0)]",
        help='Proveedor al que se enviará la cotización',
    )
    line_ids = fields.One2many(
        comodel_name='purchase.request.send.email.wizard.line',
        inverse_name='wizard_id',
        string='Líneas',
    )
    subject = fields.Char(
        string='Asunto',
        default='Cotización de productos',
        help='Asunto del correo electrónico',
    )
    email_body = fields.Html(
        string='Cuerpo del correo',
        default='''<p>Estimado proveedor,</p>
        <p>Adjunto encontrará la cotización de los siguientes productos:</p>
        <br/>
        <p>Saludos cordiales.</p>''',
        help='Cuerpo del mensaje en HTML',
    )
    company_id = fields.Many2one(
        comodel_name='res.company',
        default=lambda self: self.env.company,
        readonly=True,
    )

    def action_send_email(self):
        """Guarda los datos en la solicitud y delega el envío."""
        self.ensure_one()
        if not self.partner_id:
            raise UserError(_('Debe seleccionar un proveedor.'))

        selected_lines = self.line_ids.filtered('selected')
        if not selected_lines:
            raise UserError(_('Debe seleccionar al menos una línea.'))

        # Obtener la solicitud de la primera línea seleccionada
        request = selected_lines[0].request_line_id.request_id

        # Guardar datos temporales en la solicitud
        request.write({
            'email_partner_id': self.partner_id.id,
            'email_selected_line_ids': [(6, 0, selected_lines.mapped('request_line_id').ids)],
        })

        # Delegar en el método del modelo padre
        result = request.action_send_email_from_wizard()

        # Cerrar el wizard
        return result

    @api.model
    def default_get(self, fields_list):
        """Precarga las líneas seleccionadas en el wizard."""
        defaults = super().default_get(fields_list)

        active_model = self.env.context.get('active_model')
        active_ids = self.env.context.get('active_ids', [])

        if active_model == 'purchase.request.line' and active_ids:
            lines = self.env['purchase.request.line'].browse(active_ids)
            line_vals = []
            for line in lines.filtered(
                lambda l: l.line_state in ('pending', 'in_progress')
            ):
                line_vals.append(fields.Command.create({
                    'request_line_id': line.id,
                    'selected': True,
                    'product_id': line.product_id.id,
                    'product_qty': line.pending_qty_to_receive or line.product_qty,
                    'uom_id': line.product_uom_id.id,
                    'note': line.note,
                }))
            defaults['line_ids'] = line_vals

        elif active_model == 'purchase.request' and active_ids:
            request = self.env['purchase.request'].browse(active_ids[0])
            line_vals = []
            for line in request.line_ids.filtered(
                lambda l: l.line_state in ('pending', 'in_progress')
            ):
                line_vals.append(fields.Command.create({
                    'request_line_id': line.id,
                    'selected': False,
                    'product_id': line.product_id.id,
                    'product_qty': line.pending_qty_to_receive or line.product_qty,
                    'uom_id': line.product_uom_id.id,
                    'note': line.note,
                }))
            defaults['line_ids'] = line_vals

        return defaults


class PurchaseRequestSendEmailWizardLine(models.TransientModel):
    _name = 'purchase.request.send.email.wizard.line'
    _description = 'Línea del wizard para enviar cotización por correo'

    wizard_id = fields.Many2one(
        comodel_name='purchase.request.send.email.wizard',
        required=True,
        ondelete='cascade',
    )
    request_line_id = fields.Many2one(
        comodel_name='purchase.request.line',
        string='Línea de solicitud',
        required=True,
    )
    selected = fields.Boolean(
        string='Seleccionar',
        default=False,
    )
    product_id = fields.Many2one(
        comodel_name='product.product',
        string='Producto',
    )
    product_qty = fields.Float(
        string='Cantidad',
        required=True,
        default=1.0,
    )
    uom_id = fields.Many2one(
        comodel_name='uom.uom',
        string='UoM',
    )
    note = fields.Text(
        string='Especificaciones',
    )