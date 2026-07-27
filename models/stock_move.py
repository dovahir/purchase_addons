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
        res = super()._action_cancel()
        for move in self:
            for allocation in move.purchase_request_allocation_ids:
                allocation.purchase_request_line_id._update_state_from_purchase_lines()
        return res

    def _action_done(self, cancel_backorder=False):
        """
        Sobrescritura del método _action_done en Odoo v17.
        Al validar el movimiento (recepción), actualizar las asignaciones y las líneas de solicitud.
        """
        res = super()._action_done(cancel_backorder=cancel_backorder)

        for move in self:
            allocations = move.purchase_request_allocation_ids
            if not allocations:
                continue

            # Obtener líneas de movimiento ya hechas (cantidad recibida)
            done_move_lines = move.move_line_ids.filtered(lambda ml: ml.state == 'done' and ml.quantity > 0)
            if not done_move_lines:
                continue

            total_received = sum(done_move_lines.mapped('quantity'))

            # Agrupar asignaciones por línea de solicitud
            for request_line in allocations.mapped('purchase_request_line_id'):
                line_allocations = allocations.filtered(lambda a: a.purchase_request_line_id == request_line)
                total_requested = sum(line_allocations.mapped('requested_product_uom_qty'))

                if total_requested <= 0:
                    continue

                # Distribuir la cantidad recibida proporcionalmente entre las asignaciones
                for allocation in line_allocations:
                    qty_to_add = total_received * (allocation.requested_product_uom_qty / total_requested)
                    new_allocated = min(
                        allocation.allocated_product_qty + qty_to_add,
                        allocation.requested_product_uom_qty
                    )
                    if new_allocated != allocation.allocated_product_qty:
                        allocation.write({'allocated_product_qty': new_allocated})
                        allocation._notify_allocation(qty_to_add)

                # Actualizar el estado de la línea de solicitud
                request_line._update_state_from_purchase_lines()

                # Si la línea de solicitud está completamente recibida, marcar como 'purchased'
                if request_line.qty_done >= request_line.product_qty:
                    request_line.write({'line_state': 'purchased'})
                    request_line.message_post(
                        body=_('Línea completada (recepción total).')
                    )
                elif request_line.qty_done > 0:
                    request_line.write({'line_state': 'partially_purchased'})
                    request_line.message_post(
                        body=_('Línea parcialmente recibida (%.2f de %.2f %s).') % (
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