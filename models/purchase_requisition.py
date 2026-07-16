from odoo import models, api, _

class PurchaseRequisitionExt(models.Model):
    _inherit = 'employee.purchase.requisition'

    def action_open_requi_purchase_request_wizard(self):
        self.ensure_one()
        wizard = self.env['requi.purchase.request.wizard'].create({
            'requisition_id': self.id,
            'line_ids': [
                (0, 0, {
                    'requisition_line_id': line.id,
                    'selected': False,
                    'product_id': line.product_id.id,
                    'requisition_qty': line.quantity,
                    'product_qty': line.quantity,  # cantidad por defecto
                    'uom_id': line.product_id.uom_id.id,
                    'note': line.note or '',
                    'analytic_distribution': line.analytic_distribution,
                    'project_id': line.project_id.id if line.project_id else False,
                    'task_id': line.task_id.id if line.task_id else False,
                    'priority': line.priority or 'normal',
                    # 'supplier_id': line.partner_id.id if line.partner_id else False,
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