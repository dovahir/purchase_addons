# -*- coding : utf-8 -*-

from odoo import api, fields, models, _


class ResPartner(models.Model):
    _inherit = 'res.partner'

    seller_ids = fields.One2many(comodel_name='product.supplierinfo',inverse_name='partner_id',string='Productos')

    # Campo para las órdenes generáles/abiertas
    # requisition_ids = fields.One2many(comodel_name='purchase.requisition', inverse_name='vendor_id', string='Órdenes abiertas')