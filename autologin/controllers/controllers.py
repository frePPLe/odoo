# -*- coding: utf-8 -*-

import logging

from odoo import http
from odoo.http import request
import odoo.addons.web.controllers.home as main

logger = logging.getLogger(__name__)

# Hardcoded default superuser account details
ADMIN_USERID = "admin"
ADMIN_PASSWORD = "admin"


class AutoLoginHome(main.Home):
    @http.route("/web/login", type="http", auth="none", sitemap=False)
    def web_login(self, redirect=None, **kw):
        try:
            # Force a login
            main.ensure_db()
            uid = request.session.authenticate(
                request.session.db,
                {"login": ADMIN_USERID, "password": ADMIN_PASSWORD, "type": "password"},
            )
            request.params["login_success"] = True
            request.params["password"] = ADMIN_PASSWORD
            return request.redirect(self._login_redirect(uid, redirect=redirect))
        except Exception:
            # Autologin failed
            logger.warning("Autologin failed")
            # Use the standard login page
            return super().web_login(redirect=redirect, **kw)
