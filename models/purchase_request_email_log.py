# -*- coding: utf-8 -*-

from odoo import api, fields, models, _


class PurchaseRequestLineEmailLog(models.Model):
    _name = 'purchase.request.line.email.log'
    _description = 'Registro de envíos de cotización por correo'
    _order = 'date_sent desc'

    line_id = fields.Many2one(
        comodel_name='purchase.request.line',
        string='Línea de solicitud',
        required=True,
        ondelete='cascade',
        index=True,
    )
    partner_id = fields.Many2one(
        comodel_name='res.partner',
        string='Proveedor',
        required=True,
        ondelete='restrict',
    )
    date_sent = fields.Datetime(
        string='Fecha de envío',
        required=True,
        default=fields.Datetime.now,
    )
    email_to = fields.Char(
        string='Correo electrónico',
        related='partner_id.email',
        readonly=True,
    )
    subject = fields.Char(
        string='Asunto',
        default='Cotización de productos',
    )