# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare

_LINE_STATES = [
    ('pending', 'Pendiente'),
    ('email_sent', 'Cotización enviada'),
    ('in_progress', 'En RFQ'),
    ('to_receive', 'Por recepcionar'),
    ('partially_purchased', 'Parcialmente comprado'),
    ('purchased', 'Comprado'),
    ('cancel', 'Cancelado'),
]

# Estados de purchase.order para el campo purchase_state (fijo)
_PURCHASE_STATES = [
    ('draft', 'RFQ'),
    ('sent', 'RFQ Envíado'),
    ('to approve', 'Por aprobar'),
    ('purchase', 'Orden de compra'),
    ('done', 'Bloqueado'),
    ('cancel', 'Cancelado'),
]


class PurchaseRequestLine(models.Model):
    _name = 'purchase.request.line'
    _description = 'Línea de Solicitud de Insumos'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'analytic.mixin']
    _order = 'create_date desc'
    _rec_name = 'product_id'

    active = fields.Boolean(string='Activo', default=True)

    # =========================== Campos ===========================
    name = fields.Char(
        string='Descripción',
        tracking=True,
    )
    product_id = fields.Many2one(
        comodel_name='product.product',
        string='Producto',
        domain=[('purchase_ok', '=', True)],
        tracking=True,
    )
    product_uom_id = fields.Many2one(
        comodel_name='uom.uom',
        string='UoM',
        tracking=True,
        domain="[('category_id', '=', product_uom_category_id)]",
    )
    product_uom_category_id = fields.Many2one(
        related='product_id.uom_id.category_id',
    )
    product_qty = fields.Float(
        string='Cant. Solicitada',
        tracking=True,
        digits='Product Unit of Measure',
    )
    date_required = fields.Date(
        string='Fecha requerida',
        required=True,
        tracking=True,
        default=fields.Date.context_today,
    )
    note = fields.Text(
        string='Especificaciones',
    )
    requester_name = fields.Char(
        string='Solicitado por',
        help='Nombre de la persona que solicitó la compra',
        readonly=True,
        copy=False,
        index=True,
    )
    # ===== Nuevos campos =====
    line_state = fields.Selection(
        selection=_LINE_STATES,
        string='Estado de la línea',
        default='pending',
        tracking=True,
        index=True,
    )
    requisition_id = fields.Many2one(
        related='requisition_product_id.requisition_product_id',
        string='Requisición origen',
        store=True,
        readonly=True,
        index=True,
    )
    requisition_product_id = fields.Many2one(
        comodel_name='requisition.order',
        string='Línea de requisición origen',
        help='Referencia a la línea de requisición de empleado que originó esta solicitud',
        index=True,
        ondelete='set null',
    )
    project_id = fields.Many2one(
        comodel_name='project.project',
        string='Proyecto',
        help='Proyecto asociado a la línea',
    )
    task_id = fields.Many2one(
        comodel_name='project.task',
        string='Tarea',
        domain="[('project_id', '=', project_id), ('state', 'not in', ['1_done', '1_canceled'])]",
        help='Tarea asociada a la línea',
    )
    priority = fields.Selection(
        selection=[('normal', 'Normal'), ('urgent', 'Urgente')],
        string='Prioridad',
        default='normal',
        tracking=True,
    )
    is_replenishment = fields.Boolean(
        string='Es reabastecimiento',
        default=False,
        help='Indica si la línea fue creada desde el módulo de reabastecimiento',
    )

    # ===== Campos relacionados con compras y stock =====
    purchase_lines = fields.Many2many(
        comodel_name='purchase.order.line',
        relation='purchase_request_purchase_order_line_rel',
        column1='purchase_request_line_id',
        column2='purchase_order_line_id',
        string='Líneas de compra',
        readonly=True,
        copy=False,
        tracking=False,
    )
    purchase_state = fields.Selection(
        selection=_PURCHASE_STATES,
        compute='_compute_purchase_state',
        string='Estado de compra',
        store=True,  # Se mantiene store=True con selección fija
    )
    purchase_request_allocation_ids = fields.One2many(
        comodel_name='purchase.request.allocation',
        inverse_name='purchase_request_line_id',
        string='Asignaciones',
        copy=False,
    )

    # ===== Campos de seguimiento de cantidades =====
    qty_in_progress = fields.Float(
        string='Cant. en proceso',
        digits='Product Unit of Measure',
        compute='_compute_qty',
        store=True,
    )
    qty_done = fields.Float(
        string='Cant. completada',
        digits='Product Unit of Measure',
        compute='_compute_qty',
        store=True,
    )
    qty_cancelled = fields.Float(
        string='Cantidad cancelada',
        digits='Product Unit of Measure',
        default=0.0,
        readonly=True,  # solo se modifica desde la lógica de cancelación
        store=True,
        help='Cantidad que ha sido cancelada (por cancelación de la solicitud o de la línea).'
    )
    pending_qty_to_receive = fields.Float(
        string='Cant. por recibir',
        compute='_compute_pending_qty',
        digits='Product Unit of Measure',
        store=True,
    )
    pending_qty_to_buy = fields.Float(
        string='Cant. pendiente',
        compute='_compute_pending_qty',
        digits='Product Unit of Measure',
        store=True,
    )

    email_log_ids = fields.One2many(
        comodel_name='purchase.request.line.email.log',
        inverse_name='line_id',
        string='Envíos de cotización',
        readonly=True,
        copy=False,
    )
    picking_count = fields.Integer(
        string='Recepciones',
        compute='_compute_picking_count',
        help='Número de pickings asociados a esta línea de solicitud'
    )
    purchase_order_ids = fields.Many2many(
        comodel_name='purchase.order',
        compute='_compute_purchase_order_ids',
        string='Cotizaciones/Órdenes',
        help='Órdenes de compra asociadas a esta línea de solicitud'
    )

    # Campo usado para filtro de búsqueda
    warehouse_id = fields.Many2one(
        related='requisition_id.warehouse_id',
        string='Almacén',
        store='True',
        readonly=True
    )

    @api.model
    def default_get(self, fields_list):
        defaults = super().default_get(fields_list)
        if 'requester_name' in fields_list and not defaults.get('requester_name'):
            defaults['requester_name'] = self.env.user.name
        return defaults
    # =========================== Computed ===========================

    def _compute_picking_count(self):
        for line in self:
            # Obtener pickings únicos de las asignaciones que tengan stock_move_id
            pickings = line.purchase_request_allocation_ids.mapped('stock_move_id.picking_id').filtered(bool)
            line.picking_count = len(pickings)

    @api.depends('purchase_lines.order_id')
    def _compute_purchase_order_ids(self):
        for rec in self:
            orders = rec.purchase_lines.mapped('order_id').filtered(bool)
            rec.purchase_order_ids = [(6, 0, orders.ids)]

    @api.depends('purchase_lines.state', 'purchase_lines.order_id.state')
    def _compute_purchase_state(self):
        for rec in self:
            if not rec.purchase_lines:
                rec.purchase_state = False
                continue
            states = rec.purchase_lines.mapped('state')
            # Tomamos el estado más relevante (por jerarquía: done > purchase > ...)
            if 'done' in states:
                rec.purchase_state = 'done'
            elif 'purchase' in states:
                rec.purchase_state = 'purchase'
            elif 'to approve' in states:
                rec.purchase_state = 'to approve'
            elif 'sent' in states:
                rec.purchase_state = 'sent'
            elif 'draft' in states and not any(s in ('purchase', 'done') for s in states):
                rec.purchase_state = 'draft'
            else:
                rec.purchase_state = states[0] if states else False

    @api.depends(
        'purchase_request_allocation_ids.allocated_product_qty',
        'purchase_request_allocation_ids.open_product_qty',
        'purchase_request_allocation_ids.purchase_state',  # Aseguramos recálculo al cambiar estado de PO
    )
    def _compute_qty(self):
        for rec in self:
            qty_done = sum(rec.purchase_request_allocation_ids.mapped('allocated_product_qty'))
            qty_open = sum(rec.purchase_request_allocation_ids.mapped('open_product_qty'))
            rec.qty_done = qty_done
            rec.qty_in_progress = qty_open

    @api.depends('product_qty', 'qty_done', 'qty_in_progress', 'qty_cancelled')
    def _compute_pending_qty(self):
        for rec in self:
            # Cantidad pendiente por recibir (lo que aún no se ha recibido)
            rec.pending_qty_to_receive = max(0.0, rec.product_qty - rec.qty_done)
            # Cantidad pendiente por comprar (lo que no ha sido asignado a PO confirmada)
            rec.pending_qty_to_buy = max(0.0, rec.product_qty - rec.qty_done - rec.qty_in_progress)

    # =========================== Onchange ===========================
    @api.onchange('product_id')
    def onchange_product_id(self):
        if self.product_id:
            name = self.product_id.name
            if self.product_id.code:
                name = f"[{self.product_id.code}] {name}"
            if self.product_id.description_purchase:
                name += "\n" + self.product_id.description_purchase
            self.product_uom_id = self.product_id.uom_id.id
            self.product_qty = 1.0
            self.name = name

    # =========================== Métodos de actualización de estado ===========================
    def _update_state_from_purchase_lines(self):
        """
        Actualiza el estado de la línea basándose en:
        - PO confirmadas (purchase/done) → se consideran firmes.
        - RFQ en draft/sent → solo cuentan si tienen cantidad > 0.
        - Cantidades recibidas (qty_done).
        - Para servicios: si todas las PO están en done, se considera completado.
        """
        for rec in self:
            if rec.line_state == 'cancel':
                continue

            # Obtener líneas de compra activas (no canceladas y con cantidad > 0)
            active_po_lines = rec.purchase_lines.filtered(
                lambda l: l.state != 'cancel' and l.product_qty > 0
            )
            if not active_po_lines:
                # No hay líneas de compra activas
                rec.line_state = 'email_sent' if rec.email_log_ids else 'pending'
                continue

            # Separar confirmadas y no confirmadas
            confirmed_lines = active_po_lines.filtered(
                lambda l: l.order_id.state in ('purchase', 'done')
            )
            draft_lines = active_po_lines.filtered(
                lambda l: l.order_id.state in ('draft', 'sent')
            )

            # Calcular cantidades totales en UoM de la línea de solicitud
            total_ordered = 0.0
            for po_line in active_po_lines:
                total_ordered += po_line.product_uom._compute_quantity(
                    po_line.product_qty, rec.product_uom_id
                )

            # Si hay PO confirmadas, su cantidad es la base
            if confirmed_lines:
                confirmed_qty = sum(
                    po_line.product_uom._compute_quantity(po_line.product_qty, rec.product_uom_id)
                    for po_line in confirmed_lines
                )

                # Si la cantidad confirmada ya cubre la solicitud
                if confirmed_qty >= rec.product_qty:
                    # Ya se compró todo (o más)
                    rec.line_state = 'purchased' if rec.qty_done >= rec.product_qty else 'to_receive'
                else:
                    # La cantidad confirmada es menor a la solicitada
                    # El resto (si hay draft_lines) se cancela o se queda pendiente
                    rec.line_state = 'partially_purchased' if rec.qty_done > 0 else 'in_progress'

                # Si hay cantidad recibida, ajustar estado
                if rec.qty_done >= rec.product_qty:
                    rec.line_state = 'purchased'
                elif rec.qty_done > 0:
                    rec.line_state = 'partially_purchased' if rec.qty_done < rec.product_qty else 'purchased'
            else:
                # Solo hay RFQ en draft/sent (no hay PO confirmadas)
                if total_ordered >= rec.product_qty:
                    rec.line_state = 'to_receive' if rec.qty_done > 0 else 'in_progress'
                else:
                    rec.line_state = 'in_progress'

            # Caso especial: servicios
            if rec.product_id.type == 'service':
                # Si todas las líneas de compra están en 'done', consideramos completado
                if all(po_line.order_id.state == 'done' for po_line in active_po_lines):
                    rec.line_state = 'purchased'
                    # Si por algún motivo qty_done no está actualizado, forzarlo
                    if rec.qty_done < rec.product_qty:
                        # Sumar la cantidad de las PO en done a qty_done
                        for po_line in active_po_lines.filtered(lambda l: l.order_id.state == 'done'):
                            # Buscar asignación y forzar allocated
                            for alloc in po_line.purchase_request_allocation_ids:
                                if alloc.allocated_product_qty < alloc.requested_product_uom_qty:
                                    alloc.write({
                                        'allocated_product_qty': alloc.requested_product_uom_qty
                                    })
                                    alloc._notify_allocation(
                                        alloc.requested_product_uom_qty - alloc.allocated_product_qty
                                    )
                        # Recalcular qty_done después de forzar
                        rec._compute_qty()

    def action_cancel_multiple(self):
        if not self:
            raise UserError(_('No hay líneas seleccionadas.'))

        cancelled = 0
        errors = []
        for line in self:
            try:
                # action_cancel_line ya valida cancel/purchased y todo lo demás
                line.action_cancel_line()
                cancelled += 1
            except UserError as e:
                errors.append(_('Línea %s: %s') % (line.display_name, str(e)))

        # Construir mensaje final
        if errors:
            error_msg = _('Se cancelaron %d líneas.\n\nErrores:\n%s') % (cancelled, '\n'.join(errors))
            if cancelled == 0:
                raise UserError(error_msg)
            else:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _('Cancelación parcial'),
                        'message': error_msg,
                        'type': 'warning',
                        'sticky': False,
                    }
                }
        else:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Cancelación completada'),
                    'message': _('Se cancelaron %d líneas correctamente.') % cancelled,
                    'type': 'success',
                    'sticky': False,
                }
            }

    def action_cancel_line(self):
        self.ensure_one()
        if self.line_state in ('cancel', 'purchased'):
            raise UserError(_('No se puede cancelar una línea en este estado.'))
        if self.line_state in ('pending', 'email_sent'):
            self._cancel_direct()
        elif self.line_state in ('in_progress', 'to_receive', 'partially_purchased'):
            self._cancel_in_progress()
        # Ya no es necesario llamar a _update_state_from_purchase_lines porque _cancel_in_progress ya lo hace

    def _cancel_direct(self):
        self.ensure_one()
        # La cantidad pendiente de esta línea se considera cancelada
        pending_qty = self.product_qty - self.qty_done - self.qty_in_progress
        if pending_qty > 0:
            self.qty_cancelled += pending_qty
        self.write({'line_state': 'cancel'})
        self.message_post(body=_('Línea cancelada por cancelación de la solicitud.'))

    def _cancel_in_progress(self):
        self.ensure_one()

        draft_sent_lines = self.purchase_lines.filtered(
            lambda l: l.order_id.state in ('draft', 'sent')
        )
        confirmed_lines = self.purchase_lines.filtered(
            lambda l: l.order_id.state in ('purchase', 'done')
        )

        # Procesar RFQ en draft/sent
        for po_line in draft_sent_lines:
            po = po_line.order_id
            if po_line.product_qty != 0.0:
                # Esta cantidad se cancela
                self.qty_cancelled += po_line.product_uom._compute_quantity(
                    po_line.product_qty, self.product_uom_id
                )
                po_line.write({'product_qty': 0.0})
                alloc = self.purchase_request_allocation_ids.filtered(
                    lambda a: a.purchase_line_id == po_line
                )
                if alloc:
                    alloc.write({'requested_product_uom_qty': 0.0})
            if not po.order_line:
                po.button_cancel()
                self.message_post(body=_('La RFQ %s ha sido cancelada (quedó vacía).') % po.name)

        # Calcular cantidad total de PO confirmadas
        confirmed_qty = 0.0
        if confirmed_lines:
            for po_line in confirmed_lines:
                confirmed_qty += po_line.product_uom._compute_quantity(
                    po_line.product_qty, self.product_uom_id
                )
            # La cantidad cancelada es la diferencia entre la cantidad solicitada original
            # y la cantidad confirmada + la ya recibida (qty_done)
            # Pero qty_done ya está incluida en la cantidad confirmada (es parte de ella)
            if confirmed_qty < self.product_qty:
                self.qty_cancelled += (self.product_qty - confirmed_qty)
            self.write({'product_qty': confirmed_qty})
            self.message_post(body=_(
                'La cantidad solicitada se ha reducido a %.2f %s, correspondiente a las órdenes de compra confirmadas.'
            ) % (confirmed_qty, self.product_uom_id.name))
        else:
            # No hay PO confirmadas: toda la cantidad se cancela
            self.qty_cancelled += self.product_qty
            self.write({'product_qty': 0.0})
            self.write({'line_state': 'cancel'})
            self.message_post(body=_('Línea cancelada (sin órdenes de compra confirmadas).'))
            return

        # Recalcular estado
        self._update_state_from_purchase_lines()



    def _cancel_empty_rfqs(self):
        # Obtener PO de las líneas de compra de esta línea
        for po in self.purchase_lines.mapped('order_id'):
            if po.state in ('draft', 'sent') and not po.order_line:
                po.button_cancel()
                self.message_post(body=_('La RFQ %s ha sido cancelada porque quedó vacía.') % po.name)

    def _refresh_quantities(self):
        for rec in self:
            rec._compute_qty()
            rec._compute_pending_qty()
            rec._update_state_from_purchase_lines()

    # =========================== Acciones de smart buttons ===========================

    def action_open_purchase_orders(self):
        self.ensure_one()
        orders = self.purchase_lines.mapped('order_id')
        action = self.env['ir.actions.actions']._for_xml_id('purchase.purchase_rfq')
        if len(orders) > 1:
            action['domain'] = [('id', 'in', orders.ids)]
        elif orders:
            action['views'] = [(self.env.ref('purchase.purchase_order_form').id, 'form')]
            action['view_mode'] = 'form'
            action['res_id'] = orders.id
        return action

    def action_open_pickings(self):
        self.ensure_one()
        pickings = self.purchase_request_allocation_ids.mapped('stock_move_id.picking_id')
        action = self.env['ir.actions.actions']._for_xml_id('stock.action_picking_tree_all')
        action['context'] = {}
        if len(pickings) > 1:
            action['domain'] = [('id', 'in', pickings.ids)]
        elif pickings:
            action['views'] = [(self.env.ref('stock.view_picking_form').id, 'form')]
            action['view_mode'] = 'form'
            action['res_id'] = pickings.id
        return action

    # =========================== CRUD y validaciones ===========================

    def unlink(self):
        for rec in self:
            if rec.line_state not in ('pending', 'cancel') and rec.purchase_lines:
                raise UserError(
                    _('No se puede eliminar una línea que ya ha sido añadida a una orden de compra.')
                )
        return super().unlink()

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        # for line in lines:
        #     if line.request_id.state == 'draft':
        #         line.request_id.message_post(
        #             body=_('Producto %s agregado.') % (line.name or line.product_id.display_name),
        #         )
        return lines

    # Abre el wizard de agregar a RFQ con las líneas seleccionadas
    def action_open_add_to_rfq_wizard(self):
        action = self.env['ir.actions.actions']._for_xml_id('purchase_addons.action_purchase_request_add_to_rfq')
        action['context'] = {
            'active_model': 'purchase.request.line',
            'active_ids': self.ids,
        }
        return action

    # Abre el wizard de envío de correo con las líneas seleccionadas
    def action_open_send_email_wizard(self):
        wizard = self.env['purchase.request.send.email.wizard'].create({
            'line_ids': [
                (0, 0, {
                    'request_line_id': line.id,
                    'selected': True,
                    'product_id': line.product_id.id,
                    'product_qty': line.product_qty,
                    'uom_id': line.product_uom_id.id,
                    'note': line.note,
                }) for line in self.filtered(
                    lambda l: l.line_state not in ('cancel', 'purchased')
                )
            ]
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Enviar cotización por correo'),
            'res_model': 'purchase.request.send.email.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }
