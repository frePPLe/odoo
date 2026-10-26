# -*- coding: utf-8 -*-
{
    "name": "freppledata",
    "summary": "Test data for frepple",
    "description": "This addon loads test and demo data for frepple in odoo.",
    "author": "frePPLe",
    "license": "Other OSI approved licence",
    "category": "Uncategorized",
    "version": "20.0.0.0",
    "depends": ["mrp_subcontracting", "sale_stock", "purchase_requisition"],
    "data": [
        "data/config.xml",  # First to assure the config is correct for the rest of the data
        "data/res.partner.csv",
        "data/stock.route.csv",
        "data/product.template.csv",
        "data/stock.onhand.xml",
        "data/mrp.workcenter.csv",
        "data/mrp.bom.csv",
        "data/mrp.production.xml",
        "data/purchase.order.xml",
        "data/stock.warehouse.orderpoint.csv",
        "data/product.supplierinfo.xml",
        "data/purchase.requisition.csv",
        "data/sale.order.xml",  # Last to assure the bom and suppliers are in place for MTO sales orders
    ],
    "autoinstall": False,
    "installable": True,
    "price": 0,
    "currency": "EUR",
    "images": ["static/description/images/freppledata.png"],
}
