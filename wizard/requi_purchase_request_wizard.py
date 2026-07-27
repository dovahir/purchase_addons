# -*- coding: utf-8 -*-

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class RequiPurchaseRequestWizard(models.TransientModel):
    _name = 'requi.purchase.request.wizard'
    _description = 'Agregar líneas de requisición a solicitud de insumos'

    # Campo eliminado: purchase_request_id (ya no se usa)
    requisition_id = fields.Many2one(
        comodel_name='employee.purchase.requisition',
        string='Requisición',
        required=True,
    )
    company_id = fields.Many2one(
        comodel_name='res.company',
        related='requisition_id.company_id',
    )
    line_ids = fields.One2many(
        comodel_name='requi.purchase.request.wizard.line',
        inverse_name='wizard_id',
        string='Líneas',
    )

    def add_to_request(self):
        """Agrega las líneas seleccionadas como nuevas líneas de solicitud."""
        self.ensure_one()

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
            if line.product_qty > line.requisition_qty:
                raise UserError(
                    _('La cantidad solicitada para %s (%.2f) excede la cantidad original de la requisición (%.2f).')
                    % (line.product_id.display_name, line.product_qty, line.requisition_qty)
                )

        added_lines = []
        skipped_lines = []

        # Procesar cada línea seleccionada
        for wizard_line in selected_lines:
            req_line = wizard_line.requisition_line_id

            # Verificar si ya existe una línea con el mismo producto y requisición origen
            # Ahora no hay cabecera, pero podemos verificar si ya existe alguna línea de solicitud
            # con el mismo producto y origen (para evitar duplicados exactos)
            # Como no hay cabecera, simplemente creamos la línea, pero podemos buscar líneas
            # existentes con el mismo requisition_product_id que no estén canceladas
            existing = self.env['purchase.request.line'].search([
                ('requisition_product_id', '=', req_line.id),
                ('line_state', '!=', 'cancel')
            ], limit=1)
            if existing:
                skipped_lines.append(wizard_line)
                continue

            # Crear nueva línea en la solicitud
            new_line_vals = {
                # request_id eliminado
                'requisition_product_id': req_line.id,
                'product_id': wizard_line.product_id.id,
                'product_uom_id': wizard_line.uom_id.id,
                'product_qty': wizard_line.product_qty,
                'date_required': self.requisition_id.requisition_deadline or fields.Date.today(),
                'name': wizard_line.product_id.display_name,
                'project_id': wizard_line.project_id.id if wizard_line.project_id else False,
                'task_id': wizard_line.task_id.id if wizard_line.task_id else False,
                'priority': wizard_line.priority or 'normal',
                'analytic_distribution': wizard_line.analytic_distribution,
                'note': wizard_line.note if wizard_line.note else False,
                'is_replenishment': False,
                'line_state': 'pending',
            }
            new_line = self.env['purchase.request.line'].create(new_line_vals)
            added_lines.append(new_line)

        # Ya no actualizamos origin ni enviamos mensajes a cabecera

        # Mensaje de éxito
        message = _('Se agregaron %d líneas desde la requisición %s.') % (
            len(added_lines),
            self.requisition_id.name
        )
        if skipped_lines:
            skipped_names = ', '.join([
                l.product_id.display_name or 'Producto sin nombre'
                for l in skipped_lines
                if l.product_id and l.product_id.display_name
            ])
            if skipped_names:
                message += _('\n\nLíneas omitidas por ya existir en el destino:\n%s') % skipped_names

        # Publicar mensaje en el chatter de cada línea creada
        for line in added_lines:
            line.message_post(
                body=_('Creada desde la requisición %s.') % self.requisition_id.name
            )

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
        """Precarga las líneas de la requisición en el wizard."""
        defaults = super().default_get(fields_list)

        active_id = self.env.context.get('active_id')
        if active_id and 'requisition_id' not in defaults:
            requisition = self.env['employee.purchase.requisition'].browse(active_id)
            if requisition.exists():
                defaults['requisition_id'] = requisition.id
                if 'line_ids' in fields_list:
                    line_vals = []
                    for line in requisition.requisition_order_ids:
                        line_vals.append(fields.Command.create({
                            'requisition_line_id': line.id,
                            'selected': False,
                            'product_id': line.product_id.id,
                            'requisition_qty': line.quantity,
                            'product_qty': line.quantity,
                            'uom_id': line.product_id.uom_id.id,
                            'note': line.note or '',
                            'analytic_distribution': line.analytic_distribution,
                            'project_id': line.project_id.id if line.project_id else False,
                            'task_id': line.task_id.id if line.task_id else False,
                            'priority': line.priority or 'normal',
                        }))
                    defaults['line_ids'] = line_vals
        return defaults


class RequiPurchaseRequestWizardLine(models.TransientModel):
    _name = 'requi.purchase.request.wizard.line'
    _description = 'Línea del wizard para transferir requisición a solicitud de insumos'

    wizard_id = fields.Many2one(
        comodel_name='requi.purchase.request.wizard',
        required=True,
        ondelete='cascade',
    )
    requisition_line_id = fields.Many2one(
        comodel_name='requisition.order',
        string='Línea de requisición',
        required=True,
    )
    selected = fields.Boolean(
        string='Seleccionar',
        default=False,
    )
    product_id = fields.Many2one(
        comodel_name='product.product',
        string='Producto',
        related='requisition_line_id.product_id',
        readonly=True,
    )
    requisition_qty = fields.Float(
        string='Cantidad requerida',
        related='requisition_line_id.quantity',
        readonly=True,
    )
    product_qty = fields.Float(
        string='Cantidad a solicitar',
        required=True,
        default=1.0,
        help='Cantidad a transferir a la solicitud (no puede superar la cantidad requerida)',
    )
    uom_id = fields.Many2one(
        comodel_name='uom.uom',
        string='Unidad',
        related='product_id.uom_id',
        readonly=True,
    )
    note = fields.Char(
        string='Notas',
        related='requisition_line_id.note',
        readonly=True,
    )
    analytic_distribution = fields.Json(
        string='Analítica',
        related='requisition_line_id.analytic_distribution',
        readonly=True,
    )
    project_id = fields.Many2one(
        comodel_name='project.project',
        string='Proyecto',
        related='requisition_line_id.project_id',
        readonly=True,
    )
    task_id = fields.Many2one(
        comodel_name='project.task',
        string='Tarea',
        related='requisition_line_id.task_id',
        readonly=True,
    )
    priority = fields.Selection(
        selection=[('normal', 'Normal'), ('urgent', 'Urgente')],
        string='Prioridad',
        related='requisition_line_id.priority',
        readonly=True,
    )