# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class PurchaseRequestAddToRfqWizard(models.TransientModel):
    _name = 'purchase.request.add.to.rfq.wizard'
    _description = 'Agregar líneas de solicitud a RFQ existente o nueva'

    # Campos de cabecera para la nueva RFQ (se piden al usuario)
    purchaser_id = fields.Many2one(
        comodel_name='res.users',
        string='Comprador',
        required=True,
        default=lambda self: self.env.user,
        help='Comprador asignado a la nueva cotización'
    )
    picking_type_id = fields.Many2one(
        comodel_name='stock.picking.type',
        string='Entregar en',
        required=True,
        default=lambda self: self._default_picking_type(),
        help='Tipo de entrega para la nueva cotización'
    )
    company_id = fields.Many2one(
        comodel_name='res.company',
        string='Compañía',
        required=True,
        default=lambda self: self.env.company,
        help='Compañía para la nueva cotización'
    )
    group_id = fields.Many2one(
        comodel_name='procurement.group',
        string='Grupo de aprovisionamiento',
        help='Opcional: grupo de aprovisionamiento para la nueva cotización'
    )

    # Campos existentes
    purchase_order_id = fields.Many2one(
        comodel_name='purchase.order',
        string='Cotización existente',
        help='Opcional: seleccione una RFQ existente en estado Borrador o Cotización',
    )
    supplier_id = fields.Many2one(
        comodel_name='res.partner',
        string='Proveedor',
        required=True,
        help='Proveedor para la nueva cotización',
    )
    line_ids = fields.One2many(
        comodel_name='purchase.request.add.to.rfq.wizard.line',
        inverse_name='wizard_id',
        string='Líneas de solicitud',
    )

    # Obtiene el tipo de entrega por defecto de la compañía
    @api.model
    def _default_picking_type(self):
        company_id = self.env.company.id
        types = self.env['stock.picking.type'].search(
            [('code', '=', 'incoming'), ('warehouse_id.company_id', '=', company_id)]
        )
        if not types:
            types = self.env['stock.picking.type'].search(
                [('code', '=', 'incoming'), ('warehouse_id', '=', False)]
            )
        return types[:1]

    # Agrega las líneas seleccionadas a una RFQ existente o crea una nueva
    def add_to_rfq(self):
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

        # Crear la PO si no se seleccionó una existente
        if not order:
            order = self._create_purchase_order(selected_lines)

        added_lines = []
        skipped_lines = []
        lines_to_in_progress = self.env['purchase.request.line']

        # Procesar cada línea seleccionada
        for wizard_line in selected_lines:
            request_line = wizard_line.request_line_id
            # Obtener los IDs con sudo() pero sin crear el registro
            project_id = request_line.sudo().project_id.id if request_line.sudo().project_id else False
            task_id = request_line.sudo().task_id.id if request_line.sudo().task_id else False

            # Verificar duplicados: si la línea de solicitud ya está vinculada a alguna línea de compra en la orden
            existing = order.order_line.filtered(
                lambda ol: request_line.id in ol.purchase_request_lines.ids
            )
            if existing:
                # Si ya existe, sumar la cantidad a la línea existente
                existing_line = existing[0]
                new_qty = existing_line.product_qty + wizard_line.product_qty
                existing_line.write({
                    'product_qty': new_qty,
                    'purchase_request_lines': [fields.Command.link(request_line.id)]
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
            # Crear la línea de compra con sudo()
            po_line_vals = self._prepare_purchase_order_line(order, wizard_line, project_id, task_id)
            po_line = self.env['purchase.order.line'].sudo().create(po_line_vals)
            added_lines.append(po_line)

            # Vincular la línea de solicitud con la línea de PO
            po_line.write({'purchase_request_lines': [fields.Command.link(request_line.id)]})

            # Crear asignación
            allocation_vals = {
                'purchase_request_line_id': request_line.id,
                'purchase_line_id': po_line.id,
                'requested_product_uom_qty': wizard_line.product_qty,
                'product_uom_id': request_line.product_uom_id.id,
                'allocated_product_qty': 0.0,
            }
            self.env['purchase.request.allocation'].create(allocation_vals)

            lines_to_in_progress |= request_line

        # Actualizar estado de todas las líneas acumuladas en una sola operación
        if lines_to_in_progress:
            lines_to_in_progress.write({'line_state': 'in_progress'})

        # Mensaje en el chatter de cada línea de solicitud (ya que no hay cabecera)
        for request_line in selected_lines.mapped('request_line_id'):
            request_line.message_post(
                body=_('Línea agregada a la cotización %s.') % order.name
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

    # Crea una nueva orden de compra con los campos del wizard
    def _create_purchase_order(self, selected_lines):
        self.ensure_one()
        # Tomar datos del wizard
        po_vals = {
            'partner_id': self.supplier_id.id,
            'company_id': self.company_id.id,
            'picking_type_id': self.picking_type_id.id,
            'date_order': fields.Date.today(),
            'user_id': self.purchaser_id.id,
            'currency_id': self.company_id.currency_id.id,
        }
        if self.group_id:
            po_vals['group_id'] = self.group_id.id

        order = self.env['purchase.order'].create(po_vals)
        return order

    def _prepare_purchase_order_line(self, order, wizard_line, project_id=False, task_id=False):
        request_line = wizard_line.request_line_id.sudo()
        product = request_line.product_id
        uom = product.uom_po_id or product.uom_id

        qty = wizard_line.product_qty
        if request_line.product_uom_id != uom:
            qty = request_line.product_uom_id._compute_quantity(qty, uom)

        vals = {
            'order_id': order.id,
            'product_id': product.id,
            'product_uom': uom.id,
            'product_qty': qty,
            'name': request_line.name or product.display_name,
            'project_id': project_id,
            'task_id': task_id,
            'analytic_distribution': request_line.analytic_distribution,
            'priority': request_line.priority,
            'note': request_line.note or '',
            'req_ids': [(6, 0, [])],
        }
        if request_line.requisition_product_id:
            requisition = request_line.requisition_product_id.requisition_product_id
            if requisition:
                vals['req_ids'] = [(6, 0, [requisition.id])]
        return vals

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        active_model = self.env.context.get('active_model')
        active_ids = self.env.context.get('active_ids', [])

        if active_model == 'purchase.request.line' and active_ids:
            lines = self.env['purchase.request.line'].browse(active_ids)
            # Filtrar líneas que no estén canceladas ni compradas
            valid_lines = lines.filtered(
                lambda l: l.line_state not in ('cancel', 'purchased')
            )
            if valid_lines and 'line_ids' in fields_list:
                line_vals = []
                for line in valid_lines:
                    # Calcular cantidad pendiente por comprar
                    qty = line.pending_qty_to_buy or line.product_qty
                    if qty <= 0:
                        qty = line.product_qty  # Si no hay pendiente, usar la cantidad original
                    line_vals.append(fields.Command.create({
                        'request_line_id': line.id,
                        'selected': True,
                        'product_id': line.product_id.id,
                        'product_qty': qty,
                        'uom_id': line.product_uom_id.id,
                    }))
                defaults['line_ids'] = line_vals

        return defaults


class PurchaseRequestAddToRfqWizardLine(models.TransientModel):
    _name = 'purchase.request.add.to.rfq.wizard.line'
    _description = 'Línea del wizard para agregar a RFQ'

    wizard_id = fields.Many2one(
        comodel_name='purchase.request.add.to.rfq.wizard',
        required=True,
        ondelete='cascade',
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