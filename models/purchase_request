# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
import base64

_STATES = [
    ('draft', 'Activa'),
    ('in_progress', 'En proceso'),
    ('done', 'Completada'),
    ('cancel', 'Cancelada'),
]


class PurchaseRequest(models.Model):
    _name = 'purchase.request'
    _description = 'Solicitud de Insumos'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    # =========================== Métodos de valor por defecto (sin @api.model) ===========================
    def _company_get(self):
        return self.env['res.company'].browse(self.env.company.id)

    def _get_default_purchaser(self):
        return self.env['res.users'].browse(self.env.uid)

    def _default_picking_type(self):
        type_obj = self.env['stock.picking.type']
        company_id = self.env.context.get('company_id') or self.env.company.id
        types = type_obj.search(
            [('code', '=', 'incoming'), ('warehouse_id.company_id', '=', company_id)]
        )
        if not types:
            types = type_obj.search(
                [('code', '=', 'incoming'), ('warehouse_id', '=', False)]
            )
        return types[:1]

    # =========================== Campos ===========================
    name = fields.Char(string='Solicitud',
                       required=True,
                       default=lambda self: _('Solicitud'),
                       tracking=True,
                       readonly=True,
                       copy=False, index=True,
    )
    # origin = fields.Char(
    #     string='Origen',
    #     help='Documento o proceso que origina la solicitud',
    #     tracking=True,
    # )
    # date_start = fields.Date(
    #     string='Fecha de creación',
    #     default=fields.Date.context_today,
    #     tracking=True,
    # )
    purchaser = fields.Many2one(
        comodel_name='res.users',
        string='Comprador',
        required=True,
        copy=False,
        tracking=True,
        default=_get_default_purchaser,
        index=True,
    )
    description = fields.Text(
        string='Notas de la solicitud',
        tracking=True,
    )
    company_id = fields.Many2one(
        comodel_name='res.company',
        string='Compañía',
        required=False,
        default=_company_get,
        tracking=True,
    )
    line_ids = fields.One2many(
        comodel_name='purchase.request.line',
        inverse_name='request_id',
        string='Líneas',
        readonly=False,
        copy=True,
    )
    state = fields.Selection(
        selection=_STATES,
        string='Estado',
        index=True,
        tracking=True,
        required=True,
        copy=False,
        default='draft',
    )
    picking_type_id = fields.Many2one(
        comodel_name='stock.picking.type',
        string='Entregar en',
        required=True,
        default=_default_picking_type,
    )
    group_id = fields.Many2one(
        comodel_name='procurement.group',
        string='Grupo de aprovisionamiento',
        copy=False,
        index=True,
    )
    line_count = fields.Integer(
        string='Número de líneas',
        compute='_compute_line_count',
        readonly=True,
    )
    move_count = fields.Integer(
        string='Número de movimientos',
        compute='_compute_move_count',
        readonly=True,
    )
    purchase_count = fields.Integer(
        string='Número de Órdenes de Compra',
        compute='_compute_purchase_count',
        readonly=True,
    )
    currency_id = fields.Many2one(
        related='company_id.currency_id',
        readonly=True,
    )
    requisition_ids = fields.Many2many(
        comodel_name='employee.purchase.requisition',
        string='Requisiciones origen',
        compute='_compute_requisition_ids',
        store=True,
        readonly=True,
        help='Requisiciones que originaron las líneas de esta solicitud'
    )

    # Campos para envío de cotización por correo (temporales)
    email_partner_id = fields.Many2one(
        comodel_name='res.partner',
        string='Proveedor para cotización',
        help='Proveedor seleccionado para enviar la cotización temporal'
    )
    email_selected_line_ids = fields.Many2many(
        comodel_name='purchase.request.line',
        relation='purchase_request_email_line_rel',
        column1='request_id',
        column2='line_id',
        string='Líneas seleccionadas para cotización',
        help='Líneas seleccionadas temporalmente para enviar la cotización'
    )

    def action_send_email_from_wizard(self):
        """
        Genera el PDF y envía el correo usando los datos temporales almacenados.
        Luego limpia los campos temporales.
        """
        self.ensure_one()
        partner = self.email_partner_id
        selected_lines = self.email_selected_line_ids

        if not partner:
            raise UserError(_('No hay proveedor seleccionado para enviar la cotización.'))
        if not partner.email:
            raise UserError(_('El proveedor seleccionado no tiene correo electrónico.'))
        if not selected_lines:
            raise UserError(_('No hay líneas seleccionadas para enviar la cotización.'))

        # Generar PDF
        pdf_content = self._generate_email_pdf(partner, selected_lines)

        # Crear adjunto
        attachment = self.env['ir.attachment'].create({
            'name': f'Cotizacion_{partner.name}_{fields.Datetime.now().strftime("%Y%m%d_%H%M%S")}.pdf',
            'type': 'binary',
            'datas': base64.b64encode(pdf_content),
            'res_model': 'purchase.request',
            'res_id': self.id,
            'mimetype': 'application/pdf',
        })

        # Enviar correo real
        mail_values = {
            'subject': 'Cotización de productos',
            'body_html': f"""
                <p>Estimado {partner.name},</p>
                <p>Adjunto encontrará la cotización de los siguientes productos:</p>
                <ul>
                    {''.join([f'<li><b>{line.product_id.display_name}</b>: {line.product_qty} {line.product_uom_id.name}</li>' for line in selected_lines])}
                </ul>
                <p>Saludos cordiales.</p>
            """,
            'email_to': partner.email,
            'attachment_ids': [(4, attachment.id)],
            'author_id': self.env.user.partner_id.id,
        }
        mail = self.env['mail.mail'].create(mail_values)
        mail.send()

        # Publicar en el chatter de la solicitud (HTML sin escapado)
        html_body = f"""
            Cotización enviada a <b>{partner.name}</b> ({partner.email}) con los siguientes productos:<br/><br/>
            <ul>
                {''.join([f'<li><b>{line.product_id.display_name}</b>: {line.product_qty} {line.product_uom_id.name}</li>' for line in selected_lines])}
            </ul>
        """

        # Crear el mensaje del chatter
        self.env['mail.message'].create({
            'body': html_body,
            'model': 'purchase.request',
            'res_id': self.id,
            'attachment_ids': [(4, attachment.id)],
            'partner_ids': [(4, partner.id)],
            'message_type': 'comment',
            'subtype_id': self.env.ref('mail.mt_comment').id,
        })

        # Registrar envíos en las líneas
        log_model = self.env['purchase.request.line.email.log']
        for line in selected_lines:
            log_model.create({
                'line_id': line.id,
                'partner_id': partner.id,
                'date_sent': fields.Datetime.now(),
                'subject': 'Cotización de productos',
            })
            line.message_post(
                body=_('Cotización enviada a %s por correo.') % partner.name
            )

        for line in selected_lines:
            if line.line_state == 'pending':
                line.write({'line_state': 'email_sent'})

        # Limpiar campos temporales
        self.write({
            'email_partner_id': False,
            'email_selected_line_ids': [(6, 0, [])],
        })

        # Notificación de éxito
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Correo enviado'),
                'message': _('La cotización fue enviada a %s.') % partner.name,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }

    def _generate_email_pdf(self, partner, selected_lines):
        """Genera el PDF de cotización usando el template QWeb y wkhtmltopdf."""
        # Preparar valores para QWeb
        values = {
            'object': self,
            'partner_name': partner.name,
            'selected_lines': selected_lines,
        }

        # Obtener el template QWeb
        try:
            template = self.env.ref('purchase_addons.report_purchase_request_email_content')
        except ValueError:
            raise UserError(_('No se encontró la plantilla del reporte.'))

        # Renderizar el template a HTML
        try:
            qweb = self.env['ir.qweb']
            html_content = qweb._render(template.id, values)
        except Exception as e:
            raise UserError(_('Error al renderizar la plantilla: %s') % str(e))

        if not html_content:
            raise UserError(_('El template no generó contenido HTML.'))

        # Asegurar que el HTML tenga estructura completa para wkhtmltopdf
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

        # Convertir HTML a PDF usando el método nativo de Odoo
        try:
            pdf_content = self.env['ir.actions.report']._run_wkhtmltopdf([full_html])
            return pdf_content
        except Exception as e:
            raise UserError(_('Error al convertir HTML a PDF: %s') % str(e))

    # =========================== Computed ===========================
    @api.depends('line_ids')
    def _compute_line_count(self):
        for rec in self:
            rec.line_count = len(rec.line_ids)

    @api.depends('line_ids.purchase_lines')
    def _compute_purchase_count(self):
        for rec in self:
            po_lines = rec.mapped('line_ids.purchase_lines')
            rec.purchase_count = len(po_lines.mapped('order_id'))

    @api.depends('line_ids.purchase_request_allocation_ids.stock_move_id')
    def _compute_move_count(self):
        for rec in self:
            moves = rec.mapped('line_ids.purchase_request_allocation_ids.stock_move_id')
            rec.move_count = len(moves)

    @api.depends('line_ids.requisition_id')
    def _compute_requisition_ids(self):
        for request in self:
            reqs = request.line_ids.mapped('requisition_id').filtered(bool)
            request.requisition_ids = [(6, 0, reqs.ids)]

    # =========================== Acciones de botones ===========================
    def action_close(self):
        """Cerrar la lista (pasar a estado 'in_progress') bloqueando nuevas adiciones."""
        for rec in self:
            if rec.state != 'draft':
                raise UserError(_('Solo se pueden cerrar las solicitudes en estado Activa.'))
            if not rec.line_ids:
                raise UserError(_('No se puede cerrar una solicitud sin líneas.'))
            rec.write({'state': 'in_progress'})

    def action_reopen(self):
        """Reabrir la lista (volver a 'draft') permitiendo nuevas adiciones."""
        for rec in self:
            if rec.state != 'in_progress':
                raise UserError(_('Solo se pueden reabrir las solicitudes en estado "En proceso".'))
            rec.write({'state': 'draft'})

    def action_cancel(self):
        self.ensure_one()
        if self.state in ('done', 'cancel'):
            raise UserError(_('No se puede cancelar una solicitud ya completada o cancelada.'))

        for line in self.line_ids:
            if line.line_state != 'cancel':
                line.action_cancel_line()

        self.write({'state': 'cancel'})
        self.message_post(body=_('Solicitud cancelada. Se procesaron todas las líneas.'))

    def _check_all_lines_purchased(self):
        """Si todas las líneas están en 'purchased', cambiar el estado a 'done'."""
        for rec in self:
            if rec.state == 'cancel':
                continue
            if rec.line_ids and all(l.line_state == 'purchased' for l in rec.line_ids):
                rec.write({'state': 'done'})
                rec.message_post(
                    body=_('La solicitud se ha completado automáticamente (todas las líneas compradas).'),
                    subtype_id=self.env.ref('mail.mt_comment').id,
                )

    # =========================== Métodos de vista ===========================
    # def action_view_purchase_request_line(self):
    #     self.ensure_one()
    #     action = self.env['ir.actions.actions']._for_xml_id(
    #         'purchase_addons.action_purchase_request_line_form'
    #     )
    #     lines = self.mapped('line_ids')
    #     if len(lines) > 1:
    #         action['domain'] = [('id', 'in', lines.ids)]
    #     elif lines:
    #         action['views'] = [(self.env.ref('purchase_addons.purchase_request_line_form').id, 'form')]
    #         action['view_mode'] = 'form'
    #         action['res_id'] = lines.id
    #     return action

    def action_view_purchase_order(self):
        self.ensure_one()
        action = self.env['ir.actions.actions']._for_xml_id('purchase.purchase_rfq')
        po_lines = self.mapped('line_ids.purchase_lines')
        orders = po_lines.mapped('order_id')
        if len(orders) > 1:
            action['domain'] = [('id', 'in', orders.ids)]
        elif orders:
            action['views'] = [(self.env.ref('purchase.purchase_order_form').id, 'form')]
            action['view_mode'] = 'form'
            action['res_id'] = orders.id
        return action

    def action_view_stock_picking(self):
        self.ensure_one()
        action = self.env['ir.actions.actions']._for_xml_id('stock.action_picking_tree_all')
        action['context'] = {}
        pickings = self.mapped('line_ids.purchase_request_allocation_ids.stock_move_id.picking_id')
        if len(pickings) > 1:
            action['domain'] = [('id', 'in', pickings.ids)]
        elif pickings:
            action['views'] = [(self.env.ref('stock.view_picking_form').id, 'form')]
            action['view_mode'] = 'form'
            action['res_id'] = pickings.id
        return action

    # =========================== CRUD ===========================
    def copy(self, default=None):
        default = dict(default or {})
        self.ensure_one()
        default.update({
            'state': 'draft',
            # 'date_start': fields.Date.today(),
        })
        return super().copy(default)

    def unlink(self):
        for rec in self:
            if rec.state not in ('draft', 'cancel'):
                raise UserError(
                    _('No se puede eliminar una solicitud que no esté en estado Activa o Cancelada.')
                )
        return super().unlink()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('Nueva solicitud')) == _('Nueva solicitud'):
                vals['name'] = (self.env['ir.sequence'].next_by_code('purchase.request'))
        return super().create(vals_list)

    def action_open_add_to_rfq_wizard(self):
        self.ensure_one()
        wizard = self.env['purchase.request.add.to.rfq.wizard'].create({
            'line_ids': [
                (0, 0, {
                    'request_line_id': line.id,
                    'selected': False,
                    'product_id': line.product_id.id,
                    'product_qty': line.pending_qty_to_buy or line.product_qty,
                    'uom_id': line.product_uom_id.id,
                }) for line in self.line_ids.filtered(
                    lambda l: l.line_state not in ('purchased', 'cancel')
                )
            ]
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Agregar a RFQ'),
            'res_model': 'purchase.request.add.to.rfq.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_open_send_email_wizard(self):
        self.ensure_one()
        # Crear el wizard con las líneas de la solicitud
        wizard = self.env['purchase.request.send.email.wizard'].create({
            'line_ids': [
                (0, 0, {
                    'request_line_id': line.id,
                    'selected': False,
                    'product_id': line.product_id.id,
                    'product_qty': line.pending_qty_to_receive or line.product_qty,
                    'uom_id': line.product_uom_id.id,
                    'note': line.note,
                }) for line in self.line_ids.filtered(
                    lambda l: l.line_state in ('pending', 'in_progress')
                )
            ]
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Enviar cotización por correo'),
            'res_model': 'purchase.request.send.email.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }
