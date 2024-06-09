# -*- coding: utf-8 -*-
#
# Copyright (C) 2014-2016 by frePPLe bv
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
        if company_name and req.env:
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
                    delta=int(kwargs.get("delta", 999)),
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
