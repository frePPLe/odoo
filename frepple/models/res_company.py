# -*- coding: utf-8 -*-
#
# Copyright (C) 2014 by frePPLe bv
#
# Permission is hereby granted, free of charge, to any person obtaining
# a copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish,
# distribute, sublicense, and/or sell copies of the Software, and to
# permit persons to whom the Software is furnished to do so, subject to
# the following conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE
# LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION
# WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
#

import logging
import time

from odoo import api, models, fields, exceptions
from ..controllers.frepplexml import encode_jwt, decode_jwt

_logger = logging.getLogger(__name__)


class ResCompany(models.Model):
    _name = "res.company"
    _inherit = "res.company"

    manufacturing_warehouse = fields.Many2one(
        "stock.warehouse", "Manufacturing warehouse", ondelete="set null"
    )
    calendar = fields.Many2one("resource.calendar", "Calendar", ondelete="set null")
    webtoken_key = fields.Char(
        "Webtoken key",
        size=128,
        default="advanced_planning_and_scheduling_service",
    )
    frepple_server = fields.Char(
        "frePPLe web server", size=128, default="https://odoo.frepple.com"
    )
    disclose_stack_trace = fields.Boolean(
        default=False,
        help="Send stack trace to your frepple server upon connector exceptions.",
    )
    respect_reservations = fields.Boolean(
        default=True,
        help="When checked frepple respects the reservations. When unchecked frepple can reallocate material.",
    )
    frepple_interface_user = fields.Many2one(
        "res.users", "frePPLe interface user", ondelete="set null"
    )

    def getWebtoken_key(self):
        return self.env.company.webtoken_key

    def getFrepple_server(self):
        return self.env.company.frepple_server

    @api.model
    def getFreppleURL(self, navbar=True, _url="/", branding=False):
        """
        Create an authorization header trusted by frePPLe
        """
        user_company_webtoken = self.env.company.webtoken_key
        if not user_company_webtoken:
            raise exceptions.UserError("FrePPLe company web token not configured")
        encode_params = dict(
            exp=round(time.time()) + 600,
            user=self.env.user.login,
            navbar=navbar,
            branding=branding,
        )
        webtoken = encode_jwt(encode_params, user_company_webtoken)
        if not isinstance(webtoken, str):
            webtoken = webtoken.decode("ascii")
        server = self.env.company.frepple_server
        if not server:
            raise exceptions.UserError("FrePPLe server URL not configured")
        url = "%s%s?webtoken=%s" % (server, _url, webtoken)
        return url

    @api.model
    def actionOpenFreppleWindow(self):
        current_company = self.env.company

        server = (current_company.frepple_server or "").rstrip("/").lower()
        if server == "https://odoo.frepple.com":
            return {
                "type": "ir.actions.client",
                "tag": "frepple.aps_service_info",
                "name": "FrePPLe APS",
            }

        frepple_url = current_company.getFreppleURL(True, "/", True)

        if not frepple_url:
            # If the URL is missing, return a notification action
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": "Configuration Required",
                    "message": "Please configure the base URL for Frepple in the company settings.",
                    "sticky": False,
                    "type": "warning",
                },
            }
        else:
            return {"type": "ir.actions.act_url", "url": frepple_url, "target": "new"}
