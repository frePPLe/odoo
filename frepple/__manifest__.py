# -*- coding: utf-8 -*-
{
    "name": "frepple",
    "version": "16.0.0",
    "category": "Manufacturing",
    "summary": "Advanced planning and scheduling",
    "author": "frePPLe",
    "website": "https://frepple.com",
    "license": "Other OSI approved licence",
    "description": "Connector to frePPLe - finite capacity planning and scheduling",
    "external_dependencies": {"python": ["jwt"]},
    # Option 1: for manufacturing companies using MRP module
    "depends": ["product", "purchase", "sale", "resource", "mrp"],
    "data": [
        "security/frepple_security.xml",
        "security/ir.model.access.csv",
        "views/frepple_data.xml",
        "views/res_config_settings_views.xml",
        "views/mrp_skill.xml",
        "views/mrp_workcenter_skill.xml",
        "views/mrp_workcenter_inherit.xml",
        "views/mrp_secondary_workcenter.xml",
        "views/mrp_routing_workcenter_inherit.xml",
        "views/mrp_workorder_inherit.xml",
        "views/mrp_workorder_secondary_workcenter.xml",
        "views/product_supplierinfo_inherit.xml",
    ],
    # Option 2: for distribution companies not using the MRP module
    # "depends": ["product", "purchase", "sale"],
    # "data": [
    #     "views/frepple_data_no_mrp.xml",
    #     "views/res_config_settings_views_no_mrp.xml",
    #     "views/product_supplierinfo_inherit.xml",
    #     "security/frepple_security.xml",
    # ],
    "test": [],
    "installable": True,
    "auto_install": False,
    "application": True,
    "assets": {
        "web.assets_backend": [
            "frepple/static/src/js/frepple.js",
        ],
    },
    "price": 0,
    "currency": "EUR",
    "images": ["static/description/images/frepple_animation.gif"],
}
