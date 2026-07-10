# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class ReplenishPurchaseRequestWizard(models.TransientModel):
    _name = 'replenish.purchase.request.wizard'
    _description = 'Agregar productos de reabastecimiento a solicitud de insumos'

    purchase_request_id = fields.Many2one(
        comodel_name='purchase.request',
        string='Solicitud de insumos',
        domain="[('state', '=', 'draft')]",
        # required=True,
        help='Seleccione una solicitud en estado Activa',
    )
    line_ids = fields.One2many(
        comodel_name='replenish.purchase.request.wizard.line',
        inverse_name='wizard_id',
        string='Productos',
    )

    def add_to_request(self):
        """Agrega los productos seleccionados a la solicitud de insumos."""
        self.ensure_one()
        request = self.purchase_request_id
        if not request:
            raise UserError(_('Debe seleccionar una solicitud de insumos.'))

        lines = self.line_ids.filtered(lambda l: l.product_qty > 0)
        if not lines:
            raise UserError(_('Ingrese una cantidad mayor a 0 en al menos un producto.'))

        added_lines = []
        skipped_lines = []

        for wizard_line in lines:
            product = wizard_line.product_id
            uom = wizard_line.uom_id
            qty = wizard_line.product_qty

            if not product:
                # Si por algún motivo el producto no está definido, se omite
                skipped_lines.append(wizard_line)
                continue

            # Buscar si ya existe una línea de reabastecimiento con el mismo producto y UoM
            existing = request.line_ids.filtered(
                lambda l: l.product_id == product
                and l.product_uom_id == uom
                and l.is_replenishment == True
            )

            if existing:
                # Sumar la cantidad a la línea existente usando write() para disparar recomputes
                existing_line = existing[0]
                new_qty = existing_line.product_qty + qty
                existing_line.write({'product_qty': new_qty})
                added_lines.append(existing_line)
                continue

            # Crear nueva línea
            new_line_vals = {
                'request_id': request.id,
                'product_id': product.id,
                'product_uom_id': uom.id,
                'product_qty': qty,
                'date_required': fields.Date.today(),
                'name': product.display_name,
                'line_state': 'pending',
                'is_replenishment': True,
                'priority': 'normal',
                'note': wizard_line.note or '',
            }
            new_line = self.env['purchase.request.line'].create(new_line_vals)
            added_lines.append(new_line)

        # Actualizar origen de la solicitud si se agregaron líneas
        if added_lines:
            if not request.origin:
                request.write({'origin': _('Reabastecimiento')})
            else:
                # Usar f-string para mayor claridad
                if 'Reabastecimiento' not in request.origin:
                    request.write({'origin': f"{request.origin}, Reabastecimiento"})

            # Mensaje en el chatter
            request.message_post(
                body=_('Se agregaron %d productos desde reabastecimiento.')
                % len(added_lines)
            )

        # Construir mensaje de notificación
        message = _('Se agregaron %d productos a la solicitud %s.') % (
            len(added_lines),
            request.name or ''
        )
        if skipped_lines:
            skipped_names = ', '.join([l.product_id.display_name for l in skipped_lines if l.product_id])
            if skipped_names:
                message += _('\n\nLos siguientes productos no pudieron agregarse:\n%s') % skipped_names

        # Retornar notificación
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Proceso Completado'),
                'message': message,
                'type': 'warning' if skipped_lines else 'success',
                'sticky': True if skipped_lines else False,
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }

    @api.model
    def default_get(self, fields_list):
        """Precarga los productos seleccionados desde los puntos de pedido."""
        defaults = super().default_get(fields_list)

        active_model = self.env.context.get('active_model')
        active_ids = self.env.context.get('active_ids', [])

        if active_model == 'stock.warehouse.orderpoint' and active_ids:
            orderpoints = self.env['stock.warehouse.orderpoint'].browse(active_ids)
            if orderpoints and 'line_ids' in fields_list:
                line_vals = []
                for orderpoint in orderpoints:
                    line_vals.append(fields.Command.create({
                        'product_id': orderpoint.product_id.id,
                        'product_qty': 1.0,  # Cantidad por defecto, el usuario la editará
                        'uom_id': orderpoint.product_uom.id or orderpoint.product_id.uom_id.id,
                        'note': '',
                    }))
                defaults['line_ids'] = line_vals

        return defaults


class ReplenishPurchaseRequestWizardLine(models.TransientModel):
    _name = 'replenish.purchase.request.wizard.line'
    _description = 'Línea de reabastecimiento para solicitud de insumos'

    wizard_id = fields.Many2one(
        comodel_name='replenish.purchase.request.wizard',
        required=True,
        ondelete='cascade',
    )
    product_id = fields.Many2one(
        comodel_name='product.product',
        string='Producto',
        # readonly removido - se manejará en la vista XML
    )
    product_qty = fields.Float(
        string='Cantidad a solicitar',
        required=True,
        default=1.0,
    )
    uom_id = fields.Many2one(
        comodel_name='uom.uom',
        string='Unidad',
        readonly=True,
        related='product_id.uom_id',
    )
    note = fields.Char(
        string='Notas',
        help='Notas adicionales para esta línea',
    )