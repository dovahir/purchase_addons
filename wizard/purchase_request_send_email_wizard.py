# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError
import base64


class PurchaseRequestSendEmailWizard(models.TransientModel):
    _name = 'purchase.request.send.email.wizard'
    _description = 'Enviar cotización por correo'

    partner_id = fields.Many2one(
        comodel_name='res.partner',
        string='Proveedor',
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
        """Envía el correo con las líneas seleccionadas."""
        self.ensure_one()
        if not self.partner_id:
            raise UserError(_('Debe seleccionar un proveedor.'))
        if not self.partner_id.email:
            raise UserError(_('El proveedor seleccionado no tiene correo electrónico.'))

        selected_wiz_lines = self.line_ids.filtered('selected')
        if not selected_wiz_lines:
            raise UserError(_('Debe seleccionar al menos una línea.'))

        # Obtener las líneas de solicitud reales
        selected_lines = selected_wiz_lines.mapped('request_line_id')

        # Generar PDF
        pdf_content = self._generate_email_pdf(selected_lines)

        # Crear adjunto
        attachment = self.env['ir.attachment'].create({
            'name': f'Cotizacion_{self.partner_id.name}_{fields.Datetime.now().strftime("%Y%m%d_%H%M%S")}.pdf',
            'type': 'binary',
            'datas': base64.b64encode(pdf_content),
            'res_model': 'purchase.request.line',
            'res_id': selected_lines[0].id,  # O puedes dejar False y vincularlo solo al mensaje
            'mimetype': 'application/pdf',
        })

        # Enviar correo
        mail_values = {
            'subject': self.subject or 'Cotización de productos',
            'body_html': self.email_body,
            'email_to': self.partner_id.email,
            'attachment_ids': [(4, attachment.id)],
            'author_id': self.env.user.partner_id.id,
        }
        mail = self.env['mail.mail'].create(mail_values)
        mail.send()

        # Registrar logs en cada línea y publicar en chatter
        for line in selected_lines:
            log = self.env['purchase.request.line.email.log'].create({
                'line_id': line.id,
                'partner_id': self.partner_id.id,
                'date_sent': fields.Datetime.now(),
                'subject': self.subject or 'Cotización de productos',
            })
            # Publicar mensaje en el chatter de la línea con el attachment
            line.message_post(
                body=_('Cotización enviada a %s por correo.') % self.partner_id.name,
                attachment_ids=[attachment.id]  # <--- AQUÍ SE VINCULA EL PDF
            )
            # Si la línea estaba en 'pending', pasa a 'email_sent'
            if line.line_state == 'pending':
                line.write({'line_state': 'email_sent'})

        # Notificación de éxito
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Correo enviado'),
                'message': _('La cotización fue enviada a %s.') % self.partner_id.name,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }

    def _generate_email_pdf(self, lines):
        """Genera el PDF de cotización usando la plantilla QWeb."""
        # Preparar valores para QWeb
        values = {
            'lines': lines,
            'partner_name': self.partner_id.name,
            'company_name': self.company_id.name,
            'date': fields.Date.today().strftime('%Y-%m-%d'),
        }

        try:
            template = self.env.ref('purchase_addons.report_purchase_request_email_content')
        except ValueError:
            raise UserError(_('No se encontró la plantilla del reporte.'))

        try:
            qweb = self.env['ir.qweb']
            html_content = qweb._render(template.id, values)
        except Exception as e:
            raise UserError(_('Error al renderizar la plantilla: %s') % str(e))

        if not html_content:
            raise UserError(_('El template no generó contenido HTML.'))

        # Asegurar HTML completo (mantener igual)
        full_html = f"""
        <!DOCTYPE html>
        <html>
            <head>
                <meta charset="utf-8"/>
                <style>
                    body {{ font-family: Arial, sans-serif; font-size: 12px; }}
                    .page {{ padding: 20px; }}
                    .table {{ width: 100%; border-collapse: collapse; }}
                    .table th, .table td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
                    .table th {{ background-color: #f2f2f2; }}
                    .text-right {{ text-align: right; }}
                    .text-center {{ text-align: center; }}
                </style>
            </head>
            <body>
                {html_content}
            </body>
        </html>
        """

        try:
            pdf_content = self.env['ir.actions.report']._run_wkhtmltopdf([full_html])
            return pdf_content
        except Exception as e:
            raise UserError(_('Error al convertir HTML a PDF: %s') % str(e))

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)

        active_model = self.env.context.get('active_model')
        active_ids = self.env.context.get('active_ids', [])

        if active_model == 'purchase.request.line' and active_ids:
            lines = self.env['purchase.request.line'].browse(active_ids)
            valid_lines = lines.filtered(
                lambda l: l.line_state not in ('cancel', 'purchased')
            )
            if valid_lines and 'line_ids' in fields_list:
                line_vals = []
                for line in valid_lines:
                    line_vals.append(fields.Command.create({
                        'request_line_id': line.id,
                        'selected': True,
                        'product_id': line.product_id.id,
                        'product_qty': line.product_qty,
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
        related='request_line_id.product_id',
        readonly=True,
    )
    product_qty = fields.Float(
        string='Cantidad',
        required=True,
        default=1.0,
    )
    uom_id = fields.Many2one(
        comodel_name='uom.uom',
        string='UoM',
        related='request_line_id.product_uom_id',
        readonly=True,
    )
    note = fields.Text(
        string='Especificaciones',
        related='request_line_id.note',
        readonly=True,
    )