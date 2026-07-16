# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class StockMove(models.Model):
    _inherit = 'stock.move'

    purchase_request_line_id = fields.Many2one(
        comodel_name='purchase.request.line',
        string='Línea de solicitud de insumos',
        ondelete='set null',
        readonly=True,
        copy=False,
        index=True,
        help='Línea de solicitud de insumos que generó este movimiento',
    )

    purchase_request_allocation_ids = fields.One2many(
        comodel_name='purchase.request.allocation',
        inverse_name='stock_move_id',
        copy=False,
        string='Asignaciones de solicitud',
    )

    @api.model
    def _prepare_merge_moves_distinct_fields(self):
        distinct_fields = super()._prepare_merge_moves_distinct_fields()
        distinct_fields += ['purchase_request_line_id']
        return distinct_fields

    def _merge_moves_fields(self):
        res = super()._merge_moves_fields()
        res['purchase_request_allocation_ids'] = [
            fields.Command.link(m.id) for m in self.mapped('purchase_request_allocation_ids')
        ]
        return res

    def _action_cancel(self):
        """Al cancelar un movimiento, actualizar las líneas de solicitud si corresponde."""
        res = super()._action_cancel()
        for move in self:
            if move.purchase_request_line_id:
                move.purchase_request_line_id._update_state_from_purchase_lines()
        return res

    def _action_done(self, cancel_backorder=False):
        """
        Sobrescritura del método _action_done en Odoo v17.
        Al validar el movimiento (recepción), actualizar las asignaciones y las líneas de solicitud.
        """
        res = super()._action_done(cancel_backorder=cancel_backorder)

        for move in self:
            if not move.purchase_request_line_id:
                continue

            request_line = move.purchase_request_line_id

            # Obtener todas las líneas de movimiento (stock.move.line) asociadas a este move
            move_lines = move.move_line_ids.filtered(lambda ml: ml.state == 'done' and ml.quantity > 0)

            if not move_lines:
                continue

            # Para cada línea de movimiento, buscar la asignación correspondiente y actualizar allocated_product_qty
            for ml in move_lines:
                # Buscar la asignación que coincide con esta línea de movimiento
                # Normalmente hay una asignación por cada movimiento, pero puede haber varias si se dividió
                allocations = request_line.purchase_request_allocation_ids.filtered(
                    lambda a: a.stock_move_id.id == move.id
                )

                # Si no hay asignaciones, no podemos hacer nada
                if not allocations:
                    continue

                # La cantidad recibida en esta línea de movimiento (en la UoM del producto)
                qty_received = ml.quantity

                # Para simplificar, asignamos la cantidad a la primera asignación (o distribuir según corresponda)
                # Pero lo correcto es que cada asignación tenga su propia cantidad
                # Como normalmente hay una asignación por movimiento, tomamos la primera
                allocation = allocations[0]

                # Incrementar allocated_product_qty con la cantidad recibida
                # Asegurarse de que la cantidad no supere lo solicitado
                new_allocated = min(
                    allocation.allocated_product_qty + qty_received,
                    allocation.requested_product_uom_qty
                )
                if new_allocated != allocation.allocated_product_qty:
                    allocation.write({'allocated_product_qty': new_allocated})
                    # Notificar
                    allocation._notify_allocation(qty_received)

            # Después de actualizar todas las asignaciones, recalcular el estado de la línea de solicitud
            request_line._update_state_from_purchase_lines()

            # Si la línea de solicitud está completamente recibida, marcar como 'purchased'
            if request_line.qty_done >= request_line.product_qty:
                request_line.line_state = 'purchased'
                request_line.request_id._check_all_lines_purchased()
                request_line.request_id.message_post(
                    body=_('Línea %s completada (recepción total).') % (
                        request_line.name or request_line.product_id.display_name
                    )
                )
            elif request_line.qty_done > 0:
                request_line.line_state = 'partially_purchased'
                request_line.request_id.message_post(
                    body=_('Línea %s parcialmente recibida (%.2f de %.2f %s).') % (
                        request_line.name or request_line.product_id.display_name,
                        request_line.qty_done,
                        request_line.product_qty,
                        request_line.product_uom_id.name,
                    )
                )

        return res


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    purchase_request_line_id = fields.Many2one(
        related='move_id.purchase_request_line_id',
        string='Línea de solicitud',
        readonly=True,
        store=True,
    )

    def allocate(self):
        """
        Método que se puede llamar desde el picking para asignar cantidades.
        Pero ahora la lógica principal está en _action_done de stock.move.
        """
        # Mantenemos este método por compatibilidad, pero la lógica se movió a _action_done
        pass