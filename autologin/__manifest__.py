# -*- coding: utf-8 -*-
{
    "name": "autologin",
    "summary": "Access odoo without password",
    "description": """
Automatically log in as administrator
=====================================

This module automatically authenticates somebody accessing the
login page as admin.

**Security warning** Use this module only on a demo environment
that needs open public access. Don't even think of deploying this
module on an actual production environment.
        """,
    "author": "frePPLe",
    "license": "AGPL-3",
    "category": "Uncategorized",
    "version": "15.0.0",
    "depends": ["base", "web"],
    "data": [],
    "demo": [],
    "autoinstall": False,
    "installable": True,
}
