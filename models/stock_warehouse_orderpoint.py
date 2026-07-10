# -*- coding: utf-8 -*-

from odoo import models, api, fields, _


class StockWarehouseOrderpoint(models.Model):
    _inherit = 'stock.warehouse.orderpoint'

    # def action_add_to_purchase_request(self):
    #     """
    #     Abre el wizard para agregar los productos de los puntos de pedido seleccionados
    #     a una solicitud de insumos existente.
    #     """
    #     wizard = self.env['replenish.purchase.request.wizard'].create({
    #         'line_ids': [fields.Command.create({
    #             'product_id': rec.product_id.id,
    #             'product_qty': 1.0,  # cantidad por defecto, el usuario la editará
    #             'uom_id': rec.product_uom.id or rec.product_id.uom_id.id,
    #         }) for rec in self]
    #     })
    #
    #     return {
    #         'type': 'ir.actions.act_window',
    #         'name': _('Agregar a solicitud de insumos'),
    #         'res_model': 'replenish.purchase.request.wizard',
    #         'res_id': wizard.id,
    #         'views': [(self.env.ref('purchase_addons.replenish_purchase_request_wizard_view_form').id, 'form')],
    #         'view_mode': 'form',
    #         'target': 'new',
    #     }

    def action_add_to_purchase_request(self):
        """Abre el wizard de reabastecimiento con los productos seleccionados."""
        wizard = self.env['replenish.purchase.request.wizard'].create({
            'line_ids': [
                (0, 0, {
                    'product_id': rec.product_id.id,
                    'product_qty': 1.0,  # cantidad por defecto
                    'uom_id': rec.product_uom.id or rec.product_id.uom_id.id,
                    'note': '',
                }) for rec in self
            ]
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Agregar a solicitud de insumos'),
            'res_model': 'replenish.purchase.request.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }