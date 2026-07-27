from odoo import models, api, fields, _


class PurchaseRequisitionExt(models.Model):
    _inherit = 'employee.purchase.requisition'

    purchase_request_count = fields.Integer(
        string='Líneas de solicitud',
        compute='_compute_purchase_request_count',
        help='Número de líneas de solicitud de insumos vinculadas a esta requisición'
    )

    def _compute_purchase_request_count(self):
        for req in self:
            # Obtener todas las líneas de requisición de esta requisición
            req_line_ids = req.requisition_order_ids.ids
            # Contar líneas de solicitud que tengan requisition_product_id en esas líneas
            count = self.env['purchase.request.line'].search_count([
                ('requisition_product_id', 'in', req_line_ids)
            ])
            req.purchase_request_count = count

    def action_open_purchase_requests(self):
        """Abre la lista de líneas de solicitud de insumos vinculadas a esta requisición"""
        self.ensure_one()
        # Obtener las líneas de requisición
        req_line_ids = self.requisition_order_ids.ids
        action = self.env['ir.actions.actions']._for_xml_id(
            'purchase_addons.purchase_request_line_form_action'
        )
        action['domain'] = [('requisition_product_id', 'in', req_line_ids)]
        action['context'] = {}
        return action

    def action_open_requi_purchase_request_wizard(self):
        """Abre el wizard para agregar líneas de requisición a solicitudes de insumos"""
        self.ensure_one()
        # El wizard ahora no necesita purchase_request_id, solo crea líneas directamente
        wizard = self.env['requi.purchase.request.wizard'].create({
            'requisition_id': self.id,
            'line_ids': [
                (0, 0, {
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
                }) for line in self.requisition_order_ids
            ]
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Agregar a solicitud de insumos'),
            'res_model': 'requi.purchase.request.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }