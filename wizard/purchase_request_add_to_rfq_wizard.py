# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class PurchaseRequestAddToRfqWizard(models.TransientModel):
    _name = 'purchase.request.add.to.rfq.wizard'
    _description = 'Agregar líneas de solicitud a RFQ existente o nueva'

    purchase_order_id = fields.Many2one(
        comodel_name='purchase.order',
        string='Cotización existente',
        domain="[('state', 'in', ['draft', 'sent'])]",
        help='Opcional: seleccione una RFQ existente en estado Borrador o Cotización',
    )
    supplier_id = fields.Many2one(
        comodel_name='res.partner',
        string='Proveedor',
        # required=True,
        # domain="[('supplier_rank', '>', 0)]",
        help='Proveedor para la nueva cotización (obligatorio)',
    )
    line_ids = fields.One2many(
        comodel_name='purchase.request.add.to.rfq.wizard.line',
        inverse_name='wizard_id',
        string='Líneas de solicitud',
    )

    def add_to_rfq(self):
        """Agrega las líneas seleccionadas a una RFQ existente o crea una nueva."""
        self.ensure_one()
        order = self.purchase_order_id
        supplier = self.supplier_id

        if not supplier:
            raise UserError(_('Debe seleccionar un proveedor.'))

        selected_lines = self.line_ids.filtered('selected')
        if not selected_lines:
            raise UserError(_('Debe seleccionar al menos una línea.'))

        # Validar cantidades
        for line in selected_lines:
            if line.product_qty <= 0:
                raise UserError(
                    _('La cantidad para el producto %s debe ser mayor a 0.')
                    % line.product_id.display_name
                )
            # Validar que no supere la cantidad pendiente por comprar
            if hasattr(line.request_line_id, 'pending_qty_to_buy') and line.product_qty > line.request_line_id.pending_qty_to_buy:
                raise UserError(
                    _('La cantidad solicitada para %s (%.2f) excede la cantidad pendiente por comprar (%.2f).')
                    % (line.product_id.display_name, line.product_qty, line.request_line_id.pending_qty_to_buy)
                )

        # Crear la PO si no se seleccionó una existente
        if not order:
            order = self._create_purchase_order(supplier, selected_lines)

        added_lines = []
        skipped_lines = []
        lines_to_in_progress = self.env['purchase.request.line']

        # Procesar cada línea seleccionada
        for wizard_line in selected_lines:
            request_line = wizard_line.request_line_id

            # Verificar duplicados según el origen de la línea
            if request_line.is_replenishment:
                # Para reabastecimiento: validar por producto (puede haber varias líneas de distintas solicitudes)
                existing = order.order_line.filtered(
                    lambda ol: ol.product_id == request_line.product_id
                    and request_line.id in ol.purchase_request_lines.ids
                )
            else:
                # Para líneas de requisición: validar por producto y línea de requisición origen
                existing = order.order_line.filtered(
                    lambda ol: ol.product_id == request_line.product_id
                               and request_line.id in ol.purchase_request_lines.ids
                )

            if existing:
                existing_line = existing[0]
                new_qty = existing_line.product_qty + wizard_line.product_qty
                existing_line.write({
                    'product_qty': new_qty,
                    'purchase_request_lines': [fields.Command.link(request_line.id)]
                    # Agregar la nueva línea de solicitud
                })
                # Crear una nueva asignación para la nueva cantidad
                allocation_vals = {
                    'purchase_request_line_id': request_line.id,
                    'purchase_line_id': existing_line.id,
                    'requested_product_uom_qty': wizard_line.product_qty,
                    'product_uom_id': request_line.product_uom_id.id,
                    'allocated_product_qty': 0.0,
                }
                self.env['purchase.request.allocation'].create(allocation_vals)
                added_lines.append(existing_line)
                continue

            # Crear nueva línea de PO
            po_line_vals = self._prepare_purchase_order_line(order, wizard_line)
            po_line = self.env['purchase.order.line'].create(po_line_vals)
            added_lines.append(po_line)

            # Vincular la línea de solicitud con la línea de PO usando fields.Command.link
            po_line.write({'purchase_request_lines': [fields.Command.link(request_line.id)]})

            # --- CREAR ASIGNACIÓN ---
            allocation_vals = {
                'purchase_request_line_id': request_line.id,
                'purchase_line_id': po_line.id,
                'requested_product_uom_qty': wizard_line.product_qty,
                'product_uom_id': request_line.product_uom_id.id,
                'allocated_product_qty': 0.0,  # inicialmente cero, se actualizará con recepciones
            }
            self.env['purchase.request.allocation'].create(allocation_vals)
            # ------------------------

            lines_to_in_progress |= request_line

        # Actualizar estado de todas las líneas acumuladas en una sola operación
        if lines_to_in_progress:
            lines_to_in_progress.write({'line_state': 'in_progress'})

        # # Mensaje en el chatter de la solicitud
        # for req in selected_lines.mapped('request_line_id.request_id'):
        #     req.message_post(
        #         body=_('Se agregaron %d líneas a la cotización %s.')
        #         % (len(selected_lines.filtered(lambda l: l.request_line_id.request_id == req)), order.name)
        #     )
        #
        # # Mensaje en el chatter de la PO
        # if added_lines:
        #     order.message_post(
        #         body=_('Se agregaron %d líneas desde solicitudes de insumos.')
        #         % len(added_lines)
        #     )
        #
        # # Construir mensaje de notificación
        # message = _('Se agregaron %d líneas a la cotización %s.') % (
        #     len(added_lines),
        #     order.name
        # )
        #
        # if skipped_lines:
        #     skipped_names = ', '.join([
        #         l.product_id.display_name or 'Producto sin nombre'
        #         for l in skipped_lines
        #         if l.product_id and l.product_id.display_name
        #     ])
        #     if skipped_names:
        #         message += _('\n\nLíneas omitidas por ya existir en la cotización:\n%s') % skipped_names
        #
        # # Retornar notificación y abrir la PO
        # return {
        #     'type': 'ir.actions.client',
        #     'tag': 'display_notification',
        #     'params': {
        #         'title': _('Proceso Completado'),
        #         'message': message,
        #         'type': 'warning' if skipped_lines else 'success',
        #         'sticky': True if skipped_lines else False,
        #         'next': {
        #             'type': 'ir.actions.act_window',
        #             'res_model': 'purchase.order',
        #             'res_id': order.id,
        #             'view_mode': 'form',
        #             'target': 'current',
        #         },
        #     }
        # }

        # Mensaje en el chatter de la solicitud
        for req in selected_lines.mapped('request_line_id.request_id'):
            req.message_post(
                body=_('Se agregaron %d líneas a la cotización %s.')
                     % (len(selected_lines.filtered(lambda l: l.request_line_id.request_id == req)), order.name)
            )

        # Mensaje en el chatter de la PO
        if added_lines:
            order.message_post(
                body=_('Se agregaron %d líneas desde solicitudes de insumos.')
                     % len(added_lines)
            )

        # Retornar la acción para abrir la orden de compra
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'purchase.order',
            'res_id': order.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def _create_purchase_order(self, supplier, selected_lines):
        """Crea una nueva orden de compra con el proveedor seleccionado."""
        first_line = selected_lines[0].request_line_id
        request = first_line.request_id

        origin = request.origin or request.name

        po_vals = {
            'partner_id': supplier.id,
            'origin': origin,
            'company_id': request.company_id.id,
            'picking_type_id': request.picking_type_id.id,
            'currency_id': request.currency_id.id,
            'date_order': fields.Date.today(),
            'purchase_request_ids': [fields.Command.link(request.id)],
        }
        order = self.env['purchase.order'].create(po_vals)
        return order

    def _prepare_purchase_order_line(self, order, wizard_line):
        """Prepara los valores para crear una línea de PO desde una línea del wizard."""
        # Usar sudo() para evitar problemas de permisos al leer project_id/task_id
        request_line = wizard_line.request_line_id.sudo()
        product = request_line.product_id
        uom = product.uom_po_id or product.uom_id

        # Convertir cantidad a la UoM de la PO
        qty = wizard_line.product_qty
        if request_line.product_uom_id != uom:
            qty = request_line.product_uom_id._compute_quantity(qty, uom)

        vals = {
            'order_id': order.id,
            'product_id': product.id,
            'product_uom': uom.id,
            'product_qty': qty,
            'name': request_line.name or product.display_name,
            'project_id': request_line.project_id.id if request_line.project_id else False,
            'task_id': request_line.task_id.id if request_line.task_id else False,
            'analytic_distribution': request_line.analytic_distribution,
            'priority': request_line.priority,
            'note': request_line.note if request_line else False,
            'req_ids': [fields.Command.link(
                request_line.requisition_product_id.requisition_product_id.id)] if request_line.requisition_product_id else False,
        }
        return vals

    @api.model
    def default_get(self, fields_list):
        """Precarga las líneas de la solicitud activa. En test"""
        defaults = super().default_get(fields_list)

        return defaults


class PurchaseRequestAddToRfqWizardLine(models.TransientModel):
    _name = 'purchase.request.add.to.rfq.wizard.line'
    _description = 'Línea del wizard para agregar a RFQ'

    wizard_id = fields.Many2one(
        comodel_name='purchase.request.add.to.rfq.wizard',
        required=True,
        ondelete='cascade',
    )
    request_id = fields.Many2one(
        comodel_name='purchase.request',
        related='request_line_id.request_id',
        string='Solicitud',
        readonly=True,
    )
    line_state = fields.Selection(
        related='request_line_id.line_state',
        string='Estado',
        readonly=True,
    )
    request_line_id = fields.Many2one(
        comodel_name='purchase.request.line',
        string='Línea de solicitud',
        required=True,
    )
    selected = fields.Boolean(
        string='Seleccionar',
        default=False,
    )
    product_id = fields.Many2one(
        comodel_name='product.product',
        string='Producto',
        related='request_line_id.product_id',
        readonly=True,
    )
    product_qty = fields.Float(
        string='Cantidad a solicitar',
        required=True,
        default=1.0,
        help='Cantidad a transferir a la cotización',
    )
    uom_id = fields.Many2one(
        comodel_name='uom.uom',
        string='Unidad',
        related='request_line_id.product_uom_id',
        readonly=True,
    )