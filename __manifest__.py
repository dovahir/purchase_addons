# -*- coding: utf-8 -*-

{
    'name': 'Complementos para Compras',
    'version': '17.0.1.1',
    'category': 'Purchases',
    'summary': 'Serie de modificaciones y Funcionalidades para Compras',
    'description': """
        Características principales:
        
        Gestión de solicitudes de insumos (lista de compras):
        Permite agrupar productos desde requisiciones de empleados o reabastecimiento
        para su posterior compra mediante RFQ/PO.
        - Integración con requisiciones de empleados
        - Integración con reabastecimiento
        - Creación de RFQ desde líneas de solicitud
        - Trazabilidad completa con asignaciones (stock.move y purchase.order.line)
        
    """,
    'author': 'Aldahir',
    'website': 'https://github.com/dovahir/purchase_addons',
    'depends': [
        'purchase',
        'stock',
        'project',
        'employee_purchase_requisition',
    ],
    'data': [
        # Seguridad
        # 'security/purchase_request_security.xml',
        'security/ir.model.access.csv',

        # Datos
        # 'data/purchase_request_sequence.xml',

        # Reportes
        'reports/purchase_request_email_report.xml',

        # Wizards
        'wizard/requi_purchase_request_wizard_view.xml',
        'wizard/replenish_purchase_request_wizard_view.xml',
        'wizard/purchase_request_add_to_rfq_wizard_view.xml',

        # Vistas principales
        'views/res_partner.xml',
        # 'views/purchase_request_view.xml',
        'views/purchase_request_line_view.xml',
        'views/purchase_order_view.xml',
        'views/stock_move_views.xml',
        'views/replenishment_base_view.xml',
        'views/menu_views.xml',
		'views/purchase_requisition_view.xml',
		'wizard/purchase_request_send_email_wizard_view.xml',
],
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
    'assets': {
        'web.assets_backend': [
            # Si se necesitan widgets personalizados
        ],
    },
}