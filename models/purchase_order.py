# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    purchase_request_line_ids = fields.Many2many(
        comodel_name='purchase.request.line',
        relation='purchase_order_purchase_request_line_rel',
        column1='purchase_order_id',
        column2='purchase_request_line_id',
        string='Líneas de solicitud de insumos',
        readonly=True,
        copy=False,
        help='Líneas de solicitud de insumos vinculadas a esta orden de compra',
        tracking=False,
    )
    purchase_request_line_count = fields.Integer(
        compute='_compute_purchase_request_line_count',
        string='Líneas origen'
    )

    def _compute_purchase_request_line_count(self):
        for order in self:
            order.purchase_request_line_count = len(order.purchase_request_line_ids)

    def action_open_purchase_request_lines(self):
        self.ensure_one()
        action = self.env['ir.actions.actions']._for_xml_id('purchase_addons.purchase_request_line_form_action')
        action['domain'] = [('id', 'in', self.purchase_request_line_ids.ids)]
        return action

    # ===== Sobrescritura de métodos =====
    @api.model_create_multi
    def create(self, vals_list):
        res = super().create(vals_list)
        for record in res:
            partners = record.partner_id | record.partner_id.commercial_partner_id
            partners._increase_rank("supplier_rank")
        return res

    def button_confirm(self):

        res = super().button_confirm()
        for order in self:
            # 1. Actualizar líneas de solicitud (productos stock)
            request_lines = order.mapped('order_line.purchase_request_lines')
            if request_lines:
                to_update = request_lines.filtered(
                    lambda l: l.line_state in ('pending', 'in_progress')
                )
                if to_update:
                    to_update.write({'line_state': 'to_receive'})
                    for line in to_update:
                        line.message_post(
                            body=_('La orden de compra %s ha sido confirmada. La línea está pendiente de recepción.')
                                 % order.name
                        )

            # 2. Manejar servicios (no generan recepciones)
            service_lines = order.order_line.filtered(lambda l: l.product_id.type == 'service')
            for po_line in service_lines:
                for allocation in po_line.purchase_request_allocation_ids:
                    # Si la asignación aún no está completada, marcarla como completada
                    if allocation.allocated_product_qty < allocation.requested_product_uom_qty:
                        qty_to_add = allocation.requested_product_uom_qty - allocation.allocated_product_qty
                        allocation.write({
                            'allocated_product_qty': allocation.requested_product_uom_qty
                        })
                        allocation._notify_allocation(qty_to_add)
                # Recalcular estado de las líneas de solicitud afectadas
                for req_line in po_line.purchase_request_lines:
                    req_line._refresh_quantities()

        return res

    # Al cancelar la orden, actualizar el estado de las líneas de solicitud vinculadas
    def button_cancel(self):
        res = super().button_cancel()
        for order in self:
            request_lines = order.mapped('order_line.purchase_request_lines')
            if request_lines:
                to_update = request_lines.filtered(
                    lambda l: l.line_state not in ('cancel', 'purchased')
                )
                if to_update:
                    for line in to_update:
                        line._update_state_from_purchase_lines()
                        line._refresh_quantities()
                    # Publicar mensaje en cada línea
                    for line in to_update:
                        line.message_post(
                            body=_('La orden de compra %s ha sido cancelada. Se ha actualizado el estado de la línea.')
                                 % order.name
                        )
        return res

    # Al eliminar la orden, desvincular las líneas de solicitud y actualizar su estado
    def unlink(self):
        for order in self:
            po_lines = order.order_line
            for po_line in po_lines:
                request_lines = po_line.purchase_request_lines
                if request_lines:
                    for req_line in request_lines:
                        # Remover la relación con esta línea de compra
                        req_line.purchase_lines = [fields.Command.unlink(po_line.id)]
                        req_line._refresh_quantities()
        return super().unlink()


class PurchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'

    # ===== Campos =====
    purchase_request_lines = fields.Many2many(
        comodel_name='purchase.request.line',
        relation='purchase_request_purchase_order_line_rel',
        column1='purchase_order_line_id',
        column2='purchase_request_line_id',
        string='Líneas de solicitud de insumos',
        readonly=True,
        copy=False,
        tracking=False,
    )

    purchase_request_allocation_ids = fields.One2many(
        'purchase.request.allocation',
        'purchase_line_id',
        string='Asignaciones',
        readonly=False,  # para que se pueda modificar desde código
    )


    # Abre la vista de líneas de solicitud vinculadas a esta línea de compra
    def action_open_request_line_tree_view(self):
        self.ensure_one()
        request_line_ids = self.purchase_request_lines.ids
        if not request_line_ids:
            return {'type': 'ir.actions.act_window_close'}
        action = self.env['ir.actions.actions']._for_xml_id('purchase_addons.purchase_request_line_form_action')
        action['domain'] = [('id', 'in', request_line_ids)]
        action['context'] = {}
        return action

    # ===== Al escribir la línea, actualizar el estado de las solicitudes =====
    def write(self, vals):
        # Guardar datos antes de la escritura si cambia product_qty
        if 'product_qty' in vals:
            lines_data = {}
            for line in self:
                allocations = line.purchase_request_allocation_ids
                if allocations:
                    lines_data[line.id] = {
                        'old_qty': line.product_qty,
                        'allocations': allocations,
                        'total_requested': sum(allocations.mapped('requested_product_uom_qty')),
                        'request_lines': allocations.mapped('purchase_request_line_id'),
                    }
        # Ejecutar escritura
        res = super().write(vals)

        # Procesar cambios si se modificó product_qty
        if 'product_qty' in vals:
            for line in self:
                if line.id in lines_data:
                    data = lines_data[line.id]
                    old_qty = data['old_qty']
                    new_qty = line.product_qty
                    allocations = data['allocations']
                    total_requested = data['total_requested']
                    request_lines = data['request_lines']

                    if old_qty != new_qty and total_requested > 0:
                        # Calcular factor de escala (evitar división por cero)
                        factor = new_qty / old_qty if old_qty != 0 else 1.0

                        for alloc in allocations:
                            # Nueva cantidad solicitada en esta asignación
                            new_requested = alloc.requested_product_uom_qty * factor

                            # No puede ser menor que lo ya recibido
                            if new_requested < alloc.allocated_product_qty:
                                new_requested = alloc.allocated_product_qty

                            # No puede superar la cantidad disponible de la línea de solicitud
                            request_line = alloc.purchase_request_line_id
                            # Suma de otras asignaciones de la misma línea (excluyendo esta)
                            other_allocations = request_line.purchase_request_allocation_ids - alloc
                            total_other = sum(other_allocations.mapped('requested_product_uom_qty'))
                            # Cantidad máxima permitida para esta asignación
                            max_allowed = request_line.product_qty - request_line.qty_done - total_other
                            if new_requested > max_allowed:
                                new_requested = max_allowed
                            if new_requested < 0:
                                new_requested = 0.0

                            # Escribir el nuevo valor si cambió
                            if new_requested != alloc.requested_product_uom_qty:
                                alloc.write({'requested_product_uom_qty': new_requested})

                        # Actualizar el estado de todas las líneas de solicitud afectadas
                        # Después de actualizar las asignaciones y request_lines
                        for req_line in request_lines:
                            req_line._refresh_quantities()

        return res

    # Al eliminar una línea de compra: desvincular y actualizar estado
    def unlink(self):
        for line in self:
            # Desvincular líneas de solicitud
            request_lines = line.purchase_request_lines
            if request_lines:
                for req_line in request_lines:
                    # Remover la relación con esta línea de compra
                    req_line.purchase_lines = [fields.Command.unlink(line.id)]
                    req_line._update_state_from_purchase_lines()
        return super().unlink()

    def _prepare_stock_moves(self, picking):
        self.ensure_one()
        val = super()._prepare_stock_moves(picking)
        all_list = []
        for v in val:
            all_ids = self.env['purchase.request.allocation'].search(
                [('purchase_line_id', '=', v['purchase_line_id'])]
            )
            for all_id in all_ids:
                all_list.append((4, all_id.id))
            v['purchase_request_allocation_ids'] = all_list
        return val