# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

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

    def _get_default_requested_by(self):
        return self.env['res.users'].browse(self.env.uid)

    def _get_default_name(self):
        return self.env['ir.sequence'].next_by_code('seq_purchase_request') or _('New')

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
    name = fields.Char(
        string='Referencia',
        required=True,
        default=_get_default_name,
        tracking=True,
    )
    origin = fields.Char(
        string='Origen',
        help='Documento o proceso que origina la solicitud',
        tracking=True,
    )
    date_start = fields.Date(
        string='Fecha de creación',
        default=fields.Date.context_today,
        tracking=True,
    )
    requested_by = fields.Many2one(
        comodel_name='res.users',
        string='Solicitante',
        required=True,
        copy=False,
        tracking=True,
        default=_get_default_requested_by,
        index=True,
    )
    description = fields.Text(
        string='Descripción',
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
        tracking=True,
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
        string='Tipo de operación',
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
        """Cancelar la solicitud y manejar sus líneas según corresponda."""
        self.ensure_one()
        if self.state in ('done', 'cancel'):
            raise UserError(_('No se puede cancelar una solicitud ya completada o cancelada.'))

        non_cancelable_lines = self.line_ids.filtered(
            lambda l: l.line_state in ('to_receive', 'partially_purchased', 'purchased')
        )
        if non_cancelable_lines:
            warning_msg = _(
                'Las siguientes líneas están en estado de recepción o ya compradas y no serán afectadas:\n'
            ) + '\n'.join([f'  - {l.name or l.product_id.display_name}' for l in non_cancelable_lines])
            raise UserError(warning_msg)

        # Líneas en pending -> cancel
        pending_lines = self.line_ids.filtered(lambda l: l.line_state == 'pending')
        pending_lines.write({'line_state': 'cancel'})

        # Líneas en in_progress -> manejar reducción de cantidades o cancelación de PO
        in_progress_lines = self.line_ids.filtered(lambda l: l.line_state == 'in_progress')
        for line in in_progress_lines:
            line._cancel_line()

        self.write({'state': 'cancel'})
        self.message_post(
            body=_('La solicitud ha sido cancelada.'),
            subtype_id=self.env.ref('mail.mt_comment').id,
        )

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
    def action_view_purchase_request_line(self):
        self.ensure_one()
        action = self.env['ir.actions.actions']._for_xml_id(
            'purchase_addons.action_purchase_request_line_form'
        )
        lines = self.mapped('line_ids')
        if len(lines) > 1:
            action['domain'] = [('id', 'in', lines.ids)]
        elif lines:
            action['views'] = [(self.env.ref('purchase_addons.purchase_request_line_form').id, 'form')]
            action['view_mode'] = 'form'
            action['res_id'] = lines.id
        return action

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
            'name': self._get_default_name(),
            'date_start': fields.Date.today(),
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
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self._get_default_name()
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
                    lambda l: l.line_state in ('pending', 'in_progress')
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