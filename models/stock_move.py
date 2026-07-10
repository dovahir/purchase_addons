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
        Al validar el movimiento (recepción), actualizar las líneas de solicitud vinculadas.
        """
        res = super()._action_done(cancel_backorder=cancel_backorder)

        for move in self:
            if not move.purchase_request_line_id:
                continue

            request_line = move.purchase_request_line_id

            # Obtener todas las asignaciones de esta línea de solicitud que ya están en estado 'done'
            # (el movimiento ya pasó a 'done' al ejecutar super()._action_done())
            allocations = request_line.purchase_request_allocation_ids.filtered(
                lambda a: a.stock_move_id.state == 'done'
            )

            if not allocations:
                continue

            # Calcular la cantidad total recibida para esta línea de solicitud
            total_received = sum(allocations.mapped('allocated_product_qty'))

            # Actualizar estado según cantidad recibida
            if total_received >= request_line.product_qty:
                request_line.line_state = 'purchased'
                request_line.request_id._check_all_lines_purchased()
                request_line.request_id.message_post(
                    body=_('Línea %s completada (recepción total).') % (
                            request_line.name or request_line.product_id.display_name
                    )
                )
            elif total_received > 0:
                request_line.line_state = 'partially_purchased'
                request_line.request_id.message_post(
                    body=_('Línea %s parcialmente recibida (%.2f de %.2f %s).') % (
                        request_line.name or request_line.product_id.display_name,
                        total_received,
                        request_line.product_qty,
                        request_line.product_uom_id.name,
                    )
                )
            # Si no se ha recibido nada, no cambiar estado

        return res


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    purchase_request_line_id = fields.Many2one(
        related='move_id.purchase_request_line_id',
        string='Línea de solicitud',
        readonly=True,
        store=True,
    )