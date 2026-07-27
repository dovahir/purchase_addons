# -*- coding: utf-8 -*-

from odoo import api, fields, models, _


class PurchaseRequestAllocation(models.Model):
    _name = 'purchase.request.allocation'
    _description = 'Asignación de Solicitud de Insumos'
    _order = 'id desc'

    purchase_request_line_id = fields.Many2one(
        comodel_name='purchase.request.line',
        string='Línea de solicitud',
        required=True,
        ondelete='cascade',
        index=True,
    )
    company_id = fields.Many2one(
        comodel_name='res.company',
        string='Compañía',
        compute='_compute_company_id',
        store=True,
        index=True,
        help='Compañía determinada a partir de la línea de compra o movimiento de stock'
    )
    stock_move_id = fields.Many2one(
        comodel_name='stock.move',
        string='Movimiento de stock',
        ondelete='cascade',
        index=True,
    )
    purchase_line_id = fields.Many2one(
        comodel_name='purchase.order.line',
        string='Línea de compra',
        ondelete='cascade',
        index=True,
        help='Línea de orden de compra (para servicios)',
    )
    product_id = fields.Many2one(
        comodel_name='product.product',
        string='Producto',
        related='purchase_request_line_id.product_id',
        readonly=True,
    )
    product_uom_id = fields.Many2one(
        comodel_name='uom.uom',
        string='Unidad de medida',
        related='purchase_request_line_id.product_uom_id',
        readonly=True,
        required=True,
    )
    requested_product_uom_qty = fields.Float(
        string='Cantidad solicitada',
        help='Cantidad de la línea de solicitud asignada al movimiento, en la UoM de la solicitud',
        default=0.0,
    )
    allocated_product_qty = fields.Float(
        string='Cantidad asignada',
        copy=False,
        help='Cantidad ya asignada/recibida, en la UoM del producto',
        default=0.0,
    )
    open_product_qty = fields.Float(
        string='Cantidad pendiente',
        compute='_compute_open_product_qty',
        store=True,
        help='Cantidad aún no asignada/recibida',
    )
    purchase_state = fields.Selection(
        related='purchase_line_id.order_id.state',
        string='Estado de compra',
        store=True,
        related_sudo=True,
    )

    @api.depends('purchase_line_id.order_id.company_id', 'stock_move_id.company_id')
    def _compute_company_id(self):
        for rec in self:
            company = False
            if rec.purchase_line_id:
                company = rec.purchase_line_id.order_id.company_id
            elif rec.stock_move_id:
                company = rec.stock_move_id.company_id
            rec.company_id = company

    @api.depends('requested_product_uom_qty', 'allocated_product_qty', 'purchase_state')
    def _compute_open_product_qty(self):
        """Calcula la cantidad pendiente (open) para cada asignación."""
        for rec in self:
            if rec.purchase_state in ('cancel', 'done'):
                rec.open_product_qty = 0.0
            else:
                rec.open_product_qty = max(
                    0.0,
                    rec.requested_product_uom_qty - rec.allocated_product_qty
                )

    def _notify_allocation(self, allocated_qty):
        """
        Notifica en el chatter de la línea de solicitud cuando se asigna una cantidad.
        allocated_qty debe ser la cantidad específica para esta asignación.
        """
        if not allocated_qty:
            return
        for allocation in self:
            line = allocation.purchase_request_line_id
            po_line = allocation.purchase_line_id
            if po_line:
                line.message_post(
                    body=_(
                        'Se ha asignado %.2f %s del producto %s a la línea de compra %s.'
                    ) % (
                        allocated_qty,
                        allocation.product_uom_id.name,
                        allocation.product_id.display_name,
                        po_line.order_id.name,
                    )
                )
            elif allocation.stock_move_id:
                line.message_post(
                    body=_(
                        'Se ha asignado %.2f %s del producto %s al movimiento de stock %s.'
                    ) % (
                        allocated_qty,
                        allocation.product_uom_id.name,
                        allocation.product_id.display_name,
                        allocation.stock_move_id.name,
                    )
                )