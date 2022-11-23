# -*- coding: utf-8 -*-
#
# Copyright (C) 2014-2016 by frePPLe bv
#
# This library is free software; you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU Affero
# General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public
# License along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

import base64
import logging
import odoo
import os
from pathlib import Path
import traceback
from tempfile import NamedTemporaryFile
from werkzeug.exceptions import MethodNotAllowed, InternalServerError
from werkzeug.wrappers import Response

from odoo import http
from odoo.addons.web.controllers.main import db_monodb, ensure_db
from odoo.addons.frepple.controllers.outbound import exporter, Odoo_generator
from odoo.addons.frepple.controllers.inbound import importer

logger = logging.getLogger(__name__)

try:
    import jwt
except Exception:
    logger.error(
        "PyJWT module has not been installed. Please install the library from https://pypi.python.org/pypi/PyJWT"
    )


class XMLController(odoo.http.Controller):
    def authenticate(self, req, database, language, company, version):
        """
        Implements HTTP authentication using either "basic" or "bearer" JWT token.
        """
        if "authorization" not in req.httprequest.headers:
            raise Exception("No authentication header")
        authmeth, auth = req.httprequest.headers["authorization"].split(" ", 1)
        if authmeth.lower() == "basic":
            auth = base64.b64decode(auth).decode("utf-8")
            self.user, password = auth.split(":", 1)
            if not database or not self.user or not password:
                raise Exception("Missing user, password or database")
            uid = req.session.authenticate(database, self.user, password)
            if not uid:
                raise Exception("Odoo basic authentication failed")
        elif authmeth.lower() == "bearer" and version and version[0] >= 7:
            try:
                if not company or not company.webtoken_key:
                    raise Exception("Missing company or webtoken key")
                decoded = jwt.decode(
                    auth,
                    company.webtoken_key,
                    algorithms=["HS256"],
                )
                if (
                    not database
                    or not decoded.get("user", None)
                    or not decoded.get("password", None)
                ):
                    raise Exception(
                        "Missing user, password, company or database in token"
                    )
                uid = req.session.authenticate(
                    database, decoded["user"], decoded["password"]
                )
                if not uid:
                    raise Exception("Odoo token authentication failed")
            except jwt.exceptions.InvalidTokenError:
                raise Exception("Odoo token authentication failed")
        else:
            raise Exception("Unknown authentication method")
        if language:
            # If not set we use the default language of the user
            req.session.context["lang"] = language
        return uid

    @odoo.http.route(
        "/frepple/xml", type="http", auth="none", methods=["POST", "GET"], csrf=False
    )
    def xml(self, **kwargs):
        req = odoo.http.request
        if req.httprequest.method not in ("GET", "POST"):
            raise MethodNotAllowed("Only GET and POST requests are accepted")

        # Validate arguments
        version_string = kwargs.get(
            "version", req.httprequest.form.get("version", None)
        )
        version = []
        if version_string:
            for v in version_string.split("."):
                try:
                    version.append(int(v))
                except Exception:
                    version.append(v)
        language = kwargs.get("language", req.httprequest.form.get("language", None))
        database = kwargs.get("database", req.httprequest.form.get("database", None))
        if not database:
            database = odoo.http.db_monodb(httprequest=req.httprequest)
        company_name = kwargs.get("company", req.httprequest.form.get("company", None))
        company = None
        if company_name:
            for i in req.env["res.company"].search(
                [("name", "=", company_name)], limit=1
            ):
                company = i
            if not company:
                return Response("Invalid company name argument", 401)

        # Login
        req.session.db = database
        try:
            uid = self.authenticate(req, database, language, company, version)
        except Exception as e:
            logger.warning("Failed login attempt: %s" % e)
            return Response(
                "Login with Odoo user name and password",
                401,
                headers=[("WWW-Authenticate", 'Basic realm="odoo"')],
            )

        if req.httprequest.method == "GET":
            # Generate data
            try:
                xp = exporter(
                    Odoo_generator(req.env),
                    req,
                    uid=uid,
                    database=database,
                    company=company_name,
                    mode=int(kwargs.get("mode", 1)),
                    timezone=kwargs.get("timezone", None),
                    singlecompany=kwargs.get("singlecompany", "false").lower()
                    == "true",
                    version=version,
                )
                # last empty double quote is to let python understand frepple is a folder.
                xml_folder = os.path.join(str(Path.home()), "logs", "frepple", "")
                os.makedirs(os.path.dirname(xml_folder), exist_ok=True)

                # delete any old xml file in that folder
                for file_name in os.listdir(xml_folder):
                    # construct full file path
                    file = xml_folder + file_name
                    if os.path.isfile(file):
                        os.remove(file)

                with NamedTemporaryFile(
                    mode="w+t", delete=False, dir=xml_folder
                ) as tmpfile:

                    for i in xp.run():
                        tmpfile.write(i)
                    filename = tmpfile.name

                res = http.send_file(
                    filename,
                    mimetype="application/xml;charset=utf8",
                    as_attachment=False,
                )
                res.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
                res.headers["Pragma"] = "no-cache"
                res.headers["Expires"] = "0"
                return res
            except Exception as e:
                logger.exception("Error generating frePPLe XML data")
                raise InternalServerError(
                    description="Error generating frePPLe XML data:<br>%s"
                    % (
                        traceback.format_exc()
                        if company and company.disclose_stack_trace
                        else e
                    )
                )
        elif req.httprequest.method == "POST":
            # Import the data
            try:
                ip = importer(
                    req,
                    database=database,
                    company=company,
                    mode=req.httprequest.form.get("mode", 1),
                )
                return req.make_response(
                    ip.run(),
                    [
                        ("Content-Type", "text/plain"),
                        ("Cache-Control", "no-cache, no-store, must-revalidate"),
                        ("Pragma", "no-cache"),
                        ("Expires", "0"),
                    ],
                )
            except Exception as e:
                logger.exception("Error processing data posted by frePPLe")
                raise InternalServerError(
                    description="Error processing data posted by frePPLe:<br>%s"
                    % (
                        traceback.format_exc()
                        if company and company.disclose_stack_trace
                        else e
                    )
                )
