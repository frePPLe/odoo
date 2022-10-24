# -*- coding: utf-8 -*-
{
    "name": "frepple data",
    "summary": "Test data for frepple",
    "description": "This addon loads test and demo data for frepple in odoo.",
    "author": "frePPLe",
    "license": "AGPL-3",
    "category": "Uncategorized",
    "version": "15.0.0",
    "depends": ["frepple"],
    "data": [
        "data/config.xml",
        "data/product.template.csv",
        "data/mrp.workcenter.csv",
        "data/mrp.bom.csv",
        "data/sale.order.xml",
        "data/purchase.order.xml",
        "data/stock.warehouse.orderpoint.csv",
        "data/product.supplierinfo.xml",
    ],
    "autoinstall": False,
    "installable": True,
}
