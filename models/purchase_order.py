# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    # ===== Nuevos campos =====
    purchase_request_ids = fields.Many2many(
        comodel_name='purchase.request',
        relation='purchase_order_purchase_request_rel',
        column1='purchase_order_id',
        column2='purchase_request_id',
        string='Solicitudes de insumos',
        readonly=True,
        copy=False,
        help='Solicitudes de insumos vinculadas a esta orden de compra',
        tracking=False,
    )
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

    purchase_request_count = fields.Integer(
        compute='_compute_purchase_request_count',
        string='Solicitudes'
    )

    def _compute_purchase_request_count(self):
        for order in self:
            order.purchase_request_count = len(order.purchase_request_ids)

    # ===== Smart button =====
    def action_open_purchase_requests(self):
        self.ensure_one()
        action = self.env['ir.actions.actions']._for_xml_id(
            'purchase_addons.action_purchase_request_form'
        )
        requests = self.mapped('purchase_request_ids')
        if len(requests) > 1:
            action['domain'] = [('id', 'in', requests.ids)]
        elif requests:
            action['views'] = [(self.env.ref('purchase_addons.purchase_request_form').id, 'form')]
            action['view_mode'] = 'form'
            action['res_id'] = requests.id
        return action

    # ===== Sobrescritura de métodos =====
    def button_confirm(self):
        """Al confirmar la orden, actualizar el estado de las líneas de solicitud vinculadas."""
        res = super().button_confirm()
        for order in self:
            request_lines = order.mapped('order_line.purchase_request_lines')
            if request_lines:
                to_update = request_lines.filtered(
                    lambda l: l.line_state in ('pending', 'in_progress')
                )
                if to_update:
                    to_update.write({'line_state': 'to_receive'})
                    # Agrupar por solicitud para mensajes claros
                    for req in to_update.mapped('request_id'):
                        lines_for_req = to_update.filtered(lambda l: l.request_id == req)
                        names = [l.name or l.product_id.display_name for l in lines_for_req]
                        req.message_post(
                            body=_('La orden de compra %s ha sido confirmada. Las líneas %s están pendientes de recepción.')
                            % (order.name, ', '.join(names))
                        )
        return res

    def button_cancel(self):
        """Al cancelar la orden, actualizar el estado de las líneas de solicitud vinculadas."""
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
                    for req in to_update.mapped('request_id'):
                        req.message_post(
                            body=_('La orden de compra %s ha sido cancelada. Se ha actualizado el estado de las líneas relacionadas.')
                            % order.name
                        )
        return res

    def unlink(self):
        """Al eliminar la orden, desvincular las líneas de solicitud y actualizar su estado."""
        for order in self:
            # Obtener todas las líneas de compra que se van a eliminar
            po_lines = order.order_line
            for po_line in po_lines:
                request_lines = po_line.purchase_request_lines
                if request_lines:
                    # Desvincular esta línea de compra de cada línea de solicitud usando Command.unlink
                    for req_line in request_lines:
                        # Remover la relación con esta línea de compra
                        req_line.purchase_lines = [fields.Command.unlink(po_line.id)]
                        req_line._update_state_from_purchase_lines()
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

    def action_open_request_line_tree_view(self):
        """
        Abre la vista de líneas de solicitud vinculadas a esta línea de compra.
        """
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
                        for req_line in request_lines:
                            req_line._update_state_from_purchase_lines()

        return res

    def unlink(self):
        """Al eliminar una línea de compra, desvincular de las solicitudes y actualizar estado."""
        for line in self:
            request_lines = line.purchase_request_lines
            if request_lines:
                for req_line in request_lines:
                    # Remover la relación con esta línea de compra usando Command.unlink
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