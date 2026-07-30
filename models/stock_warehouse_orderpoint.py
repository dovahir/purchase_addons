# -*- coding: utf-8 -*-

from odoo import models, api, fields, _


class StockWarehouseOrderpoint(models.Model):
    _inherit = 'stock.warehouse.orderpoint'

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