# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare

_LINE_STATES = [
    ('pending', 'Pendiente'),
    ('in_progress', 'En cotización'),
    ('to_receive', 'Por recepcionar'),
    ('partially_purchased', 'Parcialmente comprado'),
    ('purchased', 'Comprado'),
    ('cancel', 'Cancelado'),
]

# Estados de purchase.order para el campo purchase_state (fijo)
_PURCHASE_STATES = [
    ('draft', 'RFQ'),
    ('sent', 'RFQ Sent'),
    ('to approve', 'To Approve'),
    ('purchase', 'Purchase Order'),
    ('done', 'Locked'),
    ('cancel', 'Cancelled'),
]


class PurchaseRequestLine(models.Model):
    _name = 'purchase.request.line'
    _description = 'Línea de Solicitud de Insumos'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'analytic.mixin']
    _order = 'id desc'
    _rec_name = 'product_id'

    # =========================== Campos ===========================
    name = fields.Char(
        string='Descripción',
        tracking=True,
    )
    product_id = fields.Many2one(
        comodel_name='product.product',
        string='Producto',
        domain=[('purchase_ok', '=', True)],
        tracking=True,
    )
    product_uom_id = fields.Many2one(
        comodel_name='uom.uom',
        string='Unidad de medida',
        tracking=True,
        domain="[('category_id', '=', product_uom_category_id)]",
    )
    product_uom_category_id = fields.Many2one(
        related='product_id.uom_id.category_id',
    )
    product_qty = fields.Float(
        string='Cantidad',
        tracking=True,
        digits='Product Unit of Measure',
    )
    request_id = fields.Many2one(
        comodel_name='purchase.request',
        string='Solicitud',
        ondelete='cascade',
        readonly=True,
        index=True,
        auto_join=True,
    )
    company_id = fields.Many2one(
        comodel_name='res.company',
        related='request_id.company_id',
        string='Compañía',
        store=True,
    )
    date_required = fields.Date(
        string='Fecha requerida',
        required=True,
        tracking=True,
        default=fields.Date.context_today,
    )
    note = fields.Text(
        string='Especificaciones',
    )
    # supplier_id = fields.Many2one(
    #     comodel_name='res.partner',
    #     string='Proveedor preferido',
    #     compute='_compute_supplier_id',
    #     compute_sudo=True,
    #     store=True,
    # )
    origin = fields.Char(
        string='Origen',
        help='Documento o proceso que origina la solicitud',
        tracking=True,
    )

    # ===== Nuevos campos =====
    line_state = fields.Selection(
        selection=_LINE_STATES,
        string='Estado de la línea',
        default='pending',
        tracking=True,
        index=True,
    )
    requisition_product_id = fields.Many2one(
        comodel_name='requisition.order',
        string='Línea de requisición origen',
        help='Referencia a la línea de requisición de empleado que originó esta solicitud',
        index=True,
        ondelete='set null',
    )
    project_id = fields.Many2one(
        comodel_name='project.project',
        string='Proyecto',
        help='Proyecto asociado a la línea',
    )
    task_id = fields.Many2one(
        comodel_name='project.task',
        string='Tarea',
        domain="[('project_id', '=', project_id), ('state', 'not in', ['1_done', '1_canceled'])]",
        help='Tarea asociada a la línea',
    )
    priority = fields.Selection(
        selection=[('normal', 'Normal'), ('urgent', 'Urgente')],
        string='Prioridad',
        default='normal',
        tracking=True,
    )
    is_replenishment = fields.Boolean(
        string='Proviene de reabastecimiento',
        default=False,
        help='Indica si la línea fue creada desde el módulo de reabastecimiento',
    )

    # ===== Campos relacionados con compras y stock =====
    purchase_lines = fields.Many2many(
        comodel_name='purchase.order.line',
        relation='purchase_request_purchase_order_line_rel',
        column1='purchase_request_line_id',
        column2='purchase_order_line_id',
        string='Líneas de compra',
        readonly=True,
        copy=False,
        tracking=False,
    )
    purchase_state = fields.Selection(
        selection=_PURCHASE_STATES,
        compute='_compute_purchase_state',
        string='Estado de compra',
        store=True,  # Se mantiene store=True con selección fija
    )
    purchase_request_allocation_ids = fields.One2many(
        comodel_name='purchase.request.allocation',
        inverse_name='purchase_request_line_id',
        string='Asignaciones',
        copy=False,
    )

    # ===== Campos de seguimiento de cantidades =====
    qty_in_progress = fields.Float(
        string='Cantidad en proceso',
        digits='Product Unit of Measure',
        compute='_compute_qty',
        store=True,
    )
    qty_done = fields.Float(
        string='Cantidad completada',
        digits='Product Unit of Measure',
        compute='_compute_qty',
        store=True,
    )
    qty_cancelled = fields.Float(
        string='Cantidad cancelada',
        digits='Product Unit of Measure',
        compute='_compute_qty_cancelled',
        store=True,
    )
    pending_qty_to_receive = fields.Float(
        string='Cantidad pendiente por recibir',
        compute='_compute_pending_qty',
        digits='Product Unit of Measure',
        store=True,
    )
    pending_qty_to_buy = fields.Float(
        string='Cantidad pendiente por comprar',
        compute='_compute_pending_qty',
        digits='Product Unit of Measure',
        store=True,
    )

    email_log_ids = fields.One2many(
        comodel_name='purchase.request.line.email.log',
        inverse_name='line_id',
        string='Envíos de cotización',
        readonly=True,
        copy=False,
    )

    # =========================== Computed ===========================
    # @api.depends('product_id', 'product_id.seller_ids')
    # def _compute_supplier_id(self):
    #     for rec in self:
    #         sellers = rec.product_id.seller_ids.filtered(
    #             lambda si: not si.company_id or si.company_id == rec.company_id
    #         )
    #         rec.supplier_id = sellers[0].partner_id if sellers else False

    @api.depends('purchase_lines.state', 'purchase_lines.order_id.state')
    def _compute_purchase_state(self):
        for rec in self:
            if not rec.purchase_lines:
                rec.purchase_state = False
                continue
            states = rec.purchase_lines.mapped('state')
            # Tomamos el estado más relevante (por jerarquía: done > purchase > ...)
            if 'done' in states:
                rec.purchase_state = 'done'
            elif 'purchase' in states:
                rec.purchase_state = 'purchase'
            elif 'to approve' in states:
                rec.purchase_state = 'to approve'
            elif 'sent' in states:
                rec.purchase_state = 'sent'
            elif 'draft' in states and not any(s in ('purchase', 'done') for s in states):
                rec.purchase_state = 'draft'
            else:
                rec.purchase_state = states[0] if states else False

    @api.depends('purchase_request_allocation_ids.allocated_product_qty',
                 'purchase_request_allocation_ids.open_product_qty')
    def _compute_qty(self):
        for rec in self:
            qty_done = sum(rec.purchase_request_allocation_ids.mapped('allocated_product_qty'))
            qty_open = sum(rec.purchase_request_allocation_ids.mapped('open_product_qty'))
            rec.qty_done = qty_done
            rec.qty_in_progress = qty_open

    @api.depends('purchase_request_allocation_ids.stock_move_id.state',
                 'purchase_request_allocation_ids.purchase_line_id.order_id.state')
    def _compute_qty_cancelled(self):
        for rec in self:
            if rec.product_id.type != 'service':
                cancelled_moves = rec.purchase_request_allocation_ids.mapped('stock_move_id').filtered(
                    lambda sm: sm.state == 'cancel'
                )
                qty_cancelled = sum(cancelled_moves.mapped('product_qty'))
            else:
                cancelled_po_lines = rec.purchase_request_allocation_ids.mapped('purchase_line_id').filtered(
                    lambda pl: pl.state == 'cancel'
                )
                qty_cancelled = sum(cancelled_po_lines.mapped('product_qty'))
                qty_cancelled -= rec.qty_done
            rec.qty_cancelled = max(0.0, qty_cancelled)

    @api.depends('product_qty', 'qty_done', 'qty_in_progress', 'qty_cancelled')
    def _compute_pending_qty(self):
        for rec in self:
            # Cantidad pendiente por recibir (lo que aún no se ha recibido)
            rec.pending_qty_to_receive = max(0.0, rec.product_qty - rec.qty_done)
            # Cantidad pendiente por comprar (lo que no ha sido asignado a PO confirmada)
            rec.pending_qty_to_buy = max(0.0, rec.product_qty - rec.qty_done - rec.qty_in_progress)

    # =========================== Onchange ===========================
    @api.onchange('product_id')
    def onchange_product_id(self):
        if self.product_id:
            name = self.product_id.name
            if self.product_id.code:
                name = f"[{self.product_id.code}] {name}"
            if self.product_id.description_purchase:
                name += "\n" + self.product_id.description_purchase
            self.product_uom_id = self.product_id.uom_id.id
            self.product_qty = 1.0
            self.name = name

    # =========================== Métodos de actualización de estado ===========================
    def _update_state_from_purchase_lines(self):
        """
        Actualiza el estado de la línea basándose en las líneas de compra vinculadas
        y las cantidades recibidas.
        """
        for rec in self:
            if not rec.purchase_lines:
                if rec.line_state != 'cancel':
                    rec.line_state = 'pending'
                continue

            total_ordered = 0.0
            for po_line in rec.purchase_lines:
                if po_line.state == 'cancel':
                    continue
                total_ordered += po_line.product_uom._compute_quantity(
                    po_line.product_qty, rec.product_uom_id
                )

            received_qty = rec.qty_done
            in_progress_qty = rec.qty_in_progress

            if rec.line_state == 'cancel':
                continue
            elif total_ordered <= 0:
                rec.line_state = 'pending'
            elif received_qty >= rec.product_qty:
                rec.line_state = 'purchased'
            elif received_qty > 0 and received_qty < rec.product_qty:
                rec.line_state = 'partially_purchased'
            elif in_progress_qty > 0:
                rec.line_state = 'to_receive' if total_ordered >= rec.product_qty else 'in_progress'
            else:
                rec.line_state = 'in_progress' if total_ordered > 0 else 'pending'

            rec.request_id._check_all_lines_purchased()

    def _cancel_line(self):
        """
        Lógica de cancelación de una línea individual.
        """
        self.ensure_one()
        if self.line_state in ('cancel', 'purchased', 'partially_purchased'):
            return

        if not self.purchase_lines:
            self.line_state = 'cancel'
            self.message_post(body=_('Línea cancelada manualmente.'))
            return

        for po_line in self.purchase_lines:
            po = po_line.order_id
            other_lines = po.order_line.filtered(lambda l: l.id != po_line.id)
            other_request_lines = other_lines.mapped('purchase_request_lines')
            related_to_this_request = self.request_id in other_request_lines.mapped('request_id')
            if not other_lines or all(related_to_this_request for _ in other_lines):
                po.button_cancel()
                self.message_post(body=_('La orden de compra %s ha sido cancelada.') % po.name)
            else:
                if po_line.product_qty > 0:
                    po_line.product_qty = 0.0
                    po.message_post(body=_(
                        'La línea de solicitud %s ha sido cancelada, por lo que su cantidad se ha reducido a 0.'
                    ) % self.display_name)
                    self.message_post(body=_('Cantidad reducida a 0 en la orden %s.') % po.name)

        self._update_state_from_purchase_lines()

    # =========================== Acciones de smart buttons ===========================
    def action_open_request(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Solicitud'),
            'res_model': 'purchase.request',
            'res_id': self.request_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_open_purchase_orders(self):
        self.ensure_one()
        orders = self.purchase_lines.mapped('order_id')
        action = self.env['ir.actions.actions']._for_xml_id('purchase.purchase_rfq')
        if len(orders) > 1:
            action['domain'] = [('id', 'in', orders.ids)]
        elif orders:
            action['views'] = [(self.env.ref('purchase.purchase_order_form').id, 'form')]
            action['view_mode'] = 'form'
            action['res_id'] = orders.id
        return action

    def action_open_pickings(self):
        self.ensure_one()
        pickings = self.purchase_request_allocation_ids.mapped('stock_move_id.picking_id')
        action = self.env['ir.actions.actions']._for_xml_id('stock.action_picking_tree_all')
        action['context'] = {}
        if len(pickings) > 1:
            action['domain'] = [('id', 'in', pickings.ids)]
        elif pickings:
            action['views'] = [(self.env.ref('stock.view_picking_form').id, 'form')]
            action['view_mode'] = 'form'
            action['res_id'] = pickings.id
        return action

    # =========================== CRUD y validaciones ===========================
    def write(self, vals):
        res = super().write(vals)
        if 'line_state' in vals:
            for rec in self:
                if rec.line_state == 'purchased':
                    rec.request_id._check_all_lines_purchased()
        return res

    def unlink(self):
        for rec in self:
            if rec.line_state not in ('pending', 'cancel') and rec.purchase_lines:
                raise UserError(
                    _('No se puede eliminar una línea que ya ha sido añadida a una orden de compra.')
                )
        return super().unlink()

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        for line in lines:
            if line.request_id.state == 'draft':
                line.request_id.message_post(
                    body=_('Línea %s agregada.') % (line.name or line.product_id.display_name),
                )
        return lines

    def action_open_send_email_wizard(self):
        """Abre el wizard de envío de correo desde el tree de líneas."""
        wizard = self.env['purchase.request.send.email.wizard'].create({
            'line_ids': [
                (0, 0, {
                    'request_line_id': line.id,
                    'selected': True,
                    'product_id': line.product_id.id,
                    'product_qty': line.pending_qty_to_receive or line.product_qty,
                    'uom_id': line.product_uom_id.id,
                    'note': line.note,
                }) for line in self.filtered(
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
